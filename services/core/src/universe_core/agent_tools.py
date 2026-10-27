"""Built-in agent tools over the vault, galaxies, memory and the interface (ARCHITECTURE.md §5.4).

Read tools return what's stored; text that came from your files is marked untrusted (it taints the task).
Write tools change things and say so (`side_effects`), so the policy engine can ask you first.
"""

import json
import sqlite3
from typing import TYPE_CHECKING, Literal

from pydantic import BaseModel, Field

from universe_agents.tools import Tool, ToolContext, ToolResult
from universe_vault import ingest, jobs, store
from universe_vault.filetypes import ItemType

if TYPE_CHECKING:
    from universe_core.context import CoreContext


class SearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300, description="Words or a description of what to find")
    types: list[ItemType] = Field(default_factory=list, description="Only these item types, e.g. ['note']")
    limit: int = Field(default=8, ge=1, le=25)


class ReadArgs(BaseModel):
    item_id: str = Field(min_length=8, max_length=64, description="An item id from vault.search")
    max_chars: int = Field(default=6000, ge=200, le=20000)


class AddItemsArgs(BaseModel):
    project: str = Field(min_length=1, max_length=120, description="Galaxy (project) name or id")
    item_ids: list[str] = Field(min_length=1, max_length=50, description="Item ids from vault.search")


class NoteArgs(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=1, max_length=50_000, description="Markdown")
    project: str | None = Field(default=None, description="Optional galaxy name or id to add it to")
    tags: list[str] = Field(default_factory=list, max_length=20)


class MemorySearchArgs(BaseModel):
    query: str = Field(min_length=1, max_length=300)


class MemorySaveArgs(BaseModel):
    content: str = Field(min_length=1, max_length=2000, description="One fact or lesson, in a sentence or two")
    about: Literal["me", "user", "everyone"] = Field(
        default="me", description="me: your own notes; user: a fact about the user; everyone: for all agents"
    )
    type: Literal["episodic", "semantic", "procedural"] = "semantic"


class ShowArgs(BaseModel):
    target: Literal["item", "project", "search"] = Field(description="What to show in UNIVERSE")
    value: str = Field(min_length=1, max_length=300, description="An item id, a galaxy name or id, or a search")


class ListProjectsArgs(BaseModel):
    pass


def _resolve_project(conn: sqlite3.Connection, name_or_id: str) -> sqlite3.Row:
    wanted = name_or_id.strip()
    row = conn.execute(
        "SELECT * FROM projects WHERE id = ? OR lower(name) = lower(?) OR slug = lower(?)", (wanted, wanted, wanted)
    ).fetchone()
    if row is None:
        row = conn.execute(
            "SELECT * FROM projects WHERE lower(name) LIKE lower(?) ORDER BY length(name) LIMIT 1", (f"%{wanted}%",)
        ).fetchone()
    if row is None:
        names = ", ".join(r["name"] for r in conn.execute("SELECT name FROM projects ORDER BY name"))
        raise LookupError(f"no galaxy named '{name_or_id}'. Galaxies: {names}")
    return row


def builtin_tools(ctx: "CoreContext") -> list[Tool]:
    from universe_core.vault_api import _text, run_search
    from universe_vault import search as search_module

    async def vault_search(args: BaseModel, _tc: ToolContext) -> ToolResult:
        assert isinstance(args, SearchArgs)
        response = await run_search(
            ctx, args.query, mode="hybrid", filters=search_module.Filters(types=args.types), limit=args.limit
        )
        hits = [
            {"id": h.item.id, "title": h.item.title, "type": h.item.type, "snippet": (h.snippet or "")[:300]}
            for h in response.hits
        ]
        if not hits:
            return ToolResult(f"Nothing found for '{args.query}'.", data={"hits": []})
        return ToolResult(json.dumps(hits, ensure_ascii=False), data={"hits": [h["id"] for h in hits]}, untrusted=True)

    async def vault_read(args: BaseModel, _tc: ToolContext) -> ToolResult:
        assert isinstance(args, ReadArgs)
        try:
            text = await ctx.vdb.run(_text, args.item_id, args.max_chars)
        except Exception as exc:  # the item is gone or the id is wrong
            raise LookupError(f"no item with id {args.item_id}") from exc
        row = await ctx.vdb.run(store.get_row, args.item_id)
        title = row["title"] if row else args.item_id
        body = text.text or "(this item has no text)"
        suffix = "\n… (cut)" if text.truncated else ""
        return ToolResult(f"# {title}\n\n{body}{suffix}", data={"item_id": args.item_id}, untrusted=True)

    async def project_list(_args: BaseModel, _tc: ToolContext) -> ToolResult:
        rows = await ctx.vdb.run(
            lambda c: c.execute("SELECT id, name, description FROM projects ORDER BY name").fetchall()
        )
        return ToolResult(json.dumps([dict(r) for r in rows], ensure_ascii=False))

    async def project_add(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, AddItemsArgs)

        def work(conn: sqlite3.Connection) -> tuple[sqlite3.Row, list[str], list[str]]:
            project = _resolve_project(conn, args.project)
            added, missing = [], []
            for item_id in dict.fromkeys(args.item_ids):
                if store.get_row(conn, item_id) is None:
                    missing.append(item_id)
                elif store.add_to_projects(conn, item_id, [project["id"]], tc.actor):
                    added.append(item_id)
                    store.reindex_item(conn, item_id)
                    jobs.enqueue(conn, "sidecar", item_id=item_id, priority=5, idempotency_key=f"sidecar:{item_id}")
            return project, added, missing

        project, added, missing = await ctx.vdb.run(work)
        for item_id in added:
            ctx.bus.publish(
                "item.updated",
                {"item_id": item_id, "projects_added": [project["id"]]},
                actor=tc.actor,
                subject_type="item",
                subject_id=item_id,
            )
        ctx.audit.append(
            actor=tc.actor,
            action="item.linked",
            target_type="project",
            target_id=project["id"],
            details={"items": added},
            task_id=tc.task_id,
        )
        parts = [f"Added {len(added)} item(s) to {project['name']}."]
        if len(added) < len(args.item_ids) - len(missing):
            parts.append("The others were already in it.")
        if missing:
            parts.append(f"Unknown ids: {', '.join(missing)}.")
        return ToolResult(" ".join(parts), data={"project_id": project["id"], "added": added, "missing": missing})

    async def note_create(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, NoteArgs)

        def work(conn: sqlite3.Connection) -> tuple[str, str | None]:
            project_ids, slugs = [], []
            if args.project:
                project = _resolve_project(conn, args.project)
                project_ids, slugs = [project["id"]], [project["slug"]]
            item_id = ingest.create_note(
                conn,
                ctx.vault,
                args.text,
                title=args.title,
                project_ids=project_ids,
                project_slugs=slugs,
                tags=args.tags,
                source_kind="agent",
                actor=tc.actor,
            )
            return item_id, project_ids[0] if project_ids else None

        item_id, project_id = await ctx.vdb.run(work)
        row = await ctx.vdb.run(store.get_row, item_id)
        ctx.bus.publish(
            "item.created",
            {"item_id": item_id, "type": "note", "title": args.title, "path": row["path"] if row else None},
            actor=tc.actor,
            subject_type="item",
            subject_id=item_id,
        )
        ctx.audit.append(
            actor=tc.actor,
            action="file.write",
            target_type="item",
            target_id=item_id,
            details={"project_id": project_id},
            task_id=tc.task_id,
        )
        return ToolResult(f"Saved the note '{args.title}' (id {item_id}).", data={"item_id": item_id})

    async def memory_search(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, MemorySearchArgs)
        from universe_core.memory import scopes_for

        agent = ctx.agents.get(tc.agent_id)
        found = ctx.memory.search(args.query, scopes_for(tc.agent_id, agent.memory if agent else []))
        if not found:
            return ToolResult("No memories match.")
        return ToolResult("\n".join(f"- [{m.scope}] {m.content}" for m in found), data={"ids": [m.id for m in found]})

    async def memory_save(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, MemorySaveArgs)
        scope = {"me": tc.actor, "user": "self", "everyone": "shared"}[args.about]
        memory = ctx.memory.save(
            content=args.content, scope=scope, type=args.type, created_by=tc.actor, source_task_id=tc.task_id
        )
        event = "memory.proposed" if memory.status == "proposed" else "memory.created"
        ctx.bus.publish(
            event,
            {"memory_id": memory.id, "scope": scope, "task_id": tc.task_id},
            actor=tc.actor,
            subject_type="memory",
            subject_id=memory.id,
        )
        ctx.audit.append(
            actor=tc.actor,
            action=event,
            target_type="memory",
            target_id=memory.id,
            details={"scope": scope, "status": memory.status},
            task_id=tc.task_id,
        )
        if memory.status == "proposed":
            return ToolResult(
                "Saved as a proposal: the user approves memories about them or shared with everyone.",
                data={"memory_id": memory.id},
            )
        return ToolResult("Remembered.", data={"memory_id": memory.id})

    async def ui_show(args: BaseModel, tc: ToolContext) -> ToolResult:
        assert isinstance(args, ShowArgs)
        value = args.value
        if args.target == "project":
            project = await ctx.vdb.run(_resolve_project, value)
            value = project["id"]
        elif args.target == "item" and await ctx.vdb.run(store.get_row, value) is None:
            raise LookupError(f"no item with id {value}")
        ctx.bus.publish(
            "navigator.action", {"target": args.target, "value": value, "task_id": tc.task_id}, actor=tc.actor
        )
        return ToolResult(f"Showing the {args.target} in UNIVERSE.")

    return [
        Tool(
            "vault.search",
            "Search the vault by words and meaning. Returns ids, titles and snippets.",
            SearchArgs,
            "read",
            vault_search,
            summarize=lambda a: f"Search the vault for '{getattr(a, 'query', '')}'",
        ),
        Tool(
            "vault.read",
            "Read the text of one item (a note, document, transcript…).",
            ReadArgs,
            "read",
            vault_read,
            summarize=lambda a: f"Read item {getattr(a, 'item_id', '')}",
        ),
        Tool("project.list", "List the galaxies (projects) with their ids.", ListProjectsArgs, "read", project_list),
        Tool(
            "project.add_items",
            "Add items to a galaxy (project). Items can belong to several galaxies.",
            AddItemsArgs,
            "write",
            project_add,
            side_effects=True,
            summarize=lambda a: (
                f"Add {len(getattr(a, 'item_ids', []))} item(s) to the galaxy '{getattr(a, 'project', '')}'"
            ),
        ),
        Tool(
            "note.create",
            "Write a new Markdown note into the vault.",
            NoteArgs,
            "write",
            note_create,
            side_effects=True,
            summarize=lambda a: f"Save a note titled '{getattr(a, 'title', '')}'",
        ),
        Tool("memory.search", "Look up what you remember.", MemorySearchArgs, "read", memory_search),
        Tool(
            "memory.save",
            "Remember a fact or lesson for later.",
            MemorySaveArgs,
            "write",
            memory_save,
            summarize=lambda a: f"Remember: {getattr(a, 'content', '')[:120]}",
        ),
        Tool(
            "ui.show",
            "Show an item, a galaxy or search results in the UNIVERSE window.",
            ShowArgs,
            "read",
            ui_show,
            summarize=lambda a: f"Show {getattr(a, 'target', '')} {getattr(a, 'value', '')}",
        ),
    ]
