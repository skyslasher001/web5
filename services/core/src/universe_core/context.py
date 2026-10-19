"""Everything a running Core holds, built once in the app lifespan."""

import asyncio
import importlib
import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path

import httpx

from universe_agents.providers import OpenAICompatibleProvider
from universe_agents.registry import AgentDefinition, load_agents
from universe_agents.router import ModelRouter
from universe_agents.runtime import AgentRuntime, Policy
from universe_agents.tools import ToolRegistry
from universe_common.egress import EgressGate
from universe_common.errors import capture_exception
from universe_common.log import get_logger, register_secret
from universe_common.timeutil import utcnow
from universe_core.agent_engine import AgentEngine
from universe_core.agent_roster import AgentRoster
from universe_core.agent_tools import builtin_tools
from universe_core.backups import BackupService
from universe_core.chat import ChatService
from universe_core.db import Databases
from universe_core.errors import ErrorStore
from universe_core.events import EventBus
from universe_core.forge import Forge
from universe_core.forge_tools import forge_tools
from universe_core.mcp_client import MCPManager
from universe_core.memory import MemoryStore
from universe_core.protected.audit import AuditWriter
from universe_core.research_tools import research_tools
from universe_core.security import TicketStore
from universe_core.seed import ensure_seed_galaxies
from universe_core.settings import CoreSettings
from universe_core.vault_runtime import Governor, VaultDb, WorkerManager, worker_env
from universe_core.watchlists import WatchlistRunner
from universe_models.hardware import HardwareInfo, detect
from universe_models.ollama import OllamaClient
from universe_models.recommend import Recommendation, recommend
from universe_vault import jobs, purge
from universe_vault.layout import Vault
from universe_vault.models import ModelInfo, pick_embedder, query_prefix
from universe_vault.vectors import VectorStore, table_name
from universe_vault.watch import Folder, Watcher

log = get_logger(__name__)

ROUTER_TIERS = ("local-fast", "local-large")
SAFETY_MODULE = "universe_core.protected.policy"
NO_SAFETY = (
    "Agent tools need the Phase 3 protected-core patch (docs/proposals/phase-3-protected-core.md). "
    "Until it's applied, agents answer without tools."
)


def load_safety(ctx: "CoreContext") -> tuple[Policy | None, str | None]:
    """The protected policy engine, if the owner has applied it (ADR-0011 §1)."""
    try:
        module = importlib.import_module(SAFETY_MODULE)
    except ModuleNotFoundError as exc:
        if exc.name != SAFETY_MODULE:
            raise
        return None, NO_SAFETY
    return module.build(ctx), None


@dataclass
class CoreContext:
    settings: CoreSettings
    dbs: Databases
    bus: EventBus
    audit: AuditWriter
    errors: ErrorStore
    gate: EgressGate
    ollama: OllamaClient
    router: ModelRouter
    agents: dict[str, AgentDefinition]
    chat: ChatService
    tickets: TicketStore
    vault: Vault
    vectors: VectorStore
    vdb: VaultDb
    workers: WorkerManager
    internal_token: str
    backups: BackupService | None = None
    governor: Governor | None = None
    watcher: Watcher | None = None
    watchlists: WatchlistRunner | None = None
    started: float = field(default_factory=time.monotonic)
    pid: int = field(default_factory=os.getpid)
    provider: OpenAICompatibleProvider | None = None
    memory: MemoryStore = field(init=False)
    tools: ToolRegistry = field(default_factory=ToolRegistry)
    engine: AgentEngine | None = None
    mcp: MCPManager | None = None
    roster: AgentRoster | None = None
    forge: Forge | None = None
    safety: object | None = None  # the protected policy engine (policy, permissions, budget, kill switch)
    _hardware: HardwareInfo | None = None
    _hardware_lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    @classmethod
    def build(cls, settings: CoreSettings) -> "CoreContext":
        dbs = Databases.open(settings.index_dir)
        bus = EventBus(dbs.events)
        audit = AuditWriter(dbs.audit)
        errors = ErrorStore(dbs.universe, bus)
        gate = EgressGate(offline=settings.offline, audit=lambda entry: audit.append(**entry))
        ollama = OllamaClient(settings.ollama_url, gate)
        agents = load_agents(settings.agents_dir)
        if "core" not in agents:
            raise RuntimeError(f"agents/core.yaml is missing from {settings.agents_dir}")
        # Your own agents and the ones you turned off (the Agents tab); `agents` stays the live dict.
        roster = AgentRoster(dbs.universe, dict(agents), settings.data_dir / "agents", agents)
        ctx_ref: dict[str, CoreContext] = {}

        def assignment(tier: str) -> str | None:
            row = dbs.universe.execute("SELECT value FROM settings WHERE key = ?", (f"model.{tier}",)).fetchone()
            return row["value"] if row else None

        def preferences(tier: str) -> list[str]:
            ctx = ctx_ref.get("ctx")
            rec = ctx.cached_recommendation() if ctx else None
            if rec is None:
                return []
            return [c.tag for c in (rec.local_fast if tier == "local-fast" else rec.local_large)]

        router = ModelRouter(ollama, assignment=assignment, override=settings.model_override, preferences=preferences)
        provider = OpenAICompatibleProvider(
            gate.async_client(purpose="chat", local_only=True, base_url=settings.ollama_url, timeout=120.0)
        )
        chat = ChatService(dbs.universe, bus, agents, router, provider, errors, safe_mode=settings.safe_mode)
        vault = Vault(settings.vault_dir)
        vault.ensure()
        internal_token = secrets.token_urlsafe(32)
        register_secret(internal_token)
        workers = WorkerManager(
            count=0 if settings.safe_mode else settings.workers,
            env=worker_env(
                vault_dir=settings.vault_dir,
                data_dir=settings.data_dir,
                core_url=f"http://127.0.0.1:{settings.port}",
                internal_token=internal_token,
                ollama_url=settings.ollama_url,
                offline=settings.offline,
            ),
            log_dir=settings.log_dir,
        )
        ctx = cls(
            settings=settings,
            dbs=dbs,
            bus=bus,
            audit=audit,
            errors=errors,
            gate=gate,
            ollama=ollama,
            router=router,
            agents=agents,
            chat=chat,
            tickets=TicketStore(),
            vault=vault,
            vectors=VectorStore(vault.vectors),
            vdb=VaultDb(vault.db_path),
            workers=workers,
            internal_token=internal_token,
        )
        ctx_ref["ctx"] = ctx
        ctx.roster = roster
        ctx.provider = provider
        ctx.backups = BackupService(
            vault=vault,
            run_db=ctx.vdb.run,
            publish=lambda event_type, payload: ctx.bus.publish(event_type, payload),
            record_error=ctx.record_exception,
        )
        ensure_seed_galaxies(dbs.universe, bus)
        ctx.memory = MemoryStore(dbs.universe)
        for tool in builtin_tools(ctx):
            ctx.tools.add(tool)
        # Research (Phase 6, ADR-0015): the researcher agent's web.search / web.fetch / vault.save, all gated.
        for tool in research_tools(ctx):
            ctx.tools.add(tool)
        # Forge (Phase 5, ADR-0014): issues, worktrees, verification, proposals. Its agent YAML is protected.
        ctx.forge = Forge(settings.index_dir / "universe.db", settings.repo_dir, settings.data_dir)
        for tool in forge_tools(ctx):
            ctx.tools.add(tool)
        safety, reason = load_safety(ctx)
        if settings.safe_mode:
            safety, reason = None, "Agents are disabled in safe mode"
        ctx.safety = safety
        runtime = (
            AgentRuntime(router=router, model=provider, tools=ctx.tools, policy=safety) if safety is not None else None
        )
        ctx.engine = AgentEngine(
            dbs.universe, bus, audit, agents, ctx.memory, errors, runtime, unavailable_reason=reason
        )
        ctx.tools.add(ctx.engine.delegate_tool())
        ctx.mcp = MCPManager(ctx)
        ctx.engine.recover_after_restart()
        chat.engine = ctx.engine
        return ctx

    async def hardware(self, *, refresh: bool = False) -> HardwareInfo:
        async with self._hardware_lock:
            if self._hardware is None or refresh:
                self._hardware = await asyncio.to_thread(detect)
            return self._hardware

    def cached_recommendation(self) -> Recommendation | None:
        return recommend(self._hardware) if self._hardware else None

    async def recommendation(self) -> Recommendation:
        hardware = await self.hardware()
        try:
            installed = {m.name for m in await self.ollama.list_models()}
        except Exception:
            installed = set()
        return recommend(hardware, installed)

    def assignments(self) -> dict[str, str]:
        rows = self.dbs.universe.execute("SELECT key, value FROM settings WHERE key LIKE 'model.%'")
        return {row["key"].removeprefix("model."): row["value"] for row in rows}

    def set_assignment(self, tier: str, model: str, *, actor: str) -> None:
        self.dbs.universe.execute(
            "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
            " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
            (f"model.{tier}", model, utcnow()),
        )
        self.audit.append(
            actor=actor,
            action="setting.changed",
            target_type="setting",
            target_id=f"model.{tier}",
            details={"value": model},
        )
        self.bus.publish("model.assignment_changed", {"tier": tier, "model": model}, actor=actor)

    def clear_assignment(self, tier: str, *, actor: str) -> bool:
        cursor = self.dbs.universe.execute("DELETE FROM settings WHERE key = ?", (f"model.{tier}",))
        if not cursor.rowcount:
            return False
        self.audit.append(
            actor=actor,
            action="setting.changed",
            target_type="setting",
            target_id=f"model.{tier}",
            details={"value": None},
        )
        self.bus.publish("model.assignment_changed", {"tier": tier, "model": None}, actor=actor)
        return True

    # ---------- vault ----------

    async def start_background(self) -> None:
        """Pipeline workers and the governor (not in safe mode: agents and background work stay off)."""
        if self.settings.safe_mode:
            return
        if self.mcp is not None:
            await self.mcp.start_all()
        await self.workers.start()
        self.governor = Governor(
            conn=self.dbs.universe,
            vault=self.vault,
            chat_active=lambda: len(self.chat.active_conversations),
            current_embedder=self.current_embedder,
            purge_item=self.purge_item,
            publish=lambda event_type, payload: self.bus.publish(event_type, payload),
            extra_tick=self.backups.tick if self.backups else None,
        )
        self.governor.start()
        self.watcher = Watcher(self.vault, self._enqueue_from_watcher)
        self.watcher.start()
        self.refresh_watched(scan=True)
        # Research (Phase 6): re-run watched topics/pages on a schedule; gated by offline/kill like everything else.
        self.watchlists = WatchlistRunner(self)
        self.watchlists.start()

    def _enqueue_from_watcher(self, kind: str, payload: dict[str, object]) -> None:
        """Called on the watcher's thread: uses that thread's own connection."""
        jobs.enqueue(self.vdb.conn(), kind, payload=payload, priority_class="background", priority=-1)

    def refresh_watched(self, *, scan: bool = False, only: str | None = None) -> None:
        """Point the watcher at the enabled watched folders; optionally queue a scan for changes made while off."""
        rows = self.dbs.universe.execute("SELECT * FROM watched_folders WHERE enabled = 1").fetchall()
        folders = [
            Folder(
                id=r["id"],
                path=Path(r["path"]),
                recursive=bool(r["recursive"]),
                include=tuple(json.loads(r["include_globs"])),
                exclude=tuple(json.loads(r["exclude_globs"])),
                project_id=r["default_project_id"],
            )
            for r in rows
            if Path(r["path"]).is_dir()
        ]
        if self.watcher is not None:
            self.watcher.set_folders(folders)
        if scan:
            for folder in folders:
                if only is None or folder.id == only:
                    jobs.enqueue(
                        self.dbs.universe,
                        "import",
                        payload={
                            "path": str(folder.path),
                            "folder_id": folder.id,
                            "project_ids": [folder.project_id] if folder.project_id else [],
                            "interactive": False,
                        },
                        priority_class="background",
                        idempotency_key=f"scan:{folder.id}",
                    )

    def record_exception(self, exc: BaseException) -> None:
        captured = capture_exception(exc)
        self.errors.record(
            service="core",
            kind=captured.kind,
            message=captured.message,
            stack=captured.stack,
            fingerprint=captured.fingerprint,
            context=captured.context,
        )

    async def current_embedder(self) -> ModelInfo | None:
        try:
            installed = await self.ollama.list_models()
        except httpx.HTTPError:
            return None
        models = [ModelInfo(m.name, m.digest, tuple(m.capabilities)) for m in installed]
        return pick_embedder(models, self.assignments().get("embed_text"))

    async def embed_query(self, text: str) -> tuple[list[float], str] | str:
        """The query vector and its LanceDB table, or a note explaining why search is keyword-only."""
        embedder = await self.current_embedder()
        if embedder is None:
            return "Semantic search is off: no embedding model in Ollama (try: ollama pull nomic-embed-text)."
        try:
            vectors = await self.ollama.embed(
                embedder.name, [query_prefix(embedder.name) + text], request_timeout_s=5.0
            )
        except httpx.HTTPError as exc:
            return f"Semantic search is unavailable right now ({type(exc).__name__}); showing keyword matches."
        return [float(x) for x in vectors[0]], table_name(embedder.name, embedder.digest)

    async def purge_item(self, item_id: str) -> bool:
        deleted = await self.vdb.run(purge.purge, self.vault, self.vectors, item_id)
        if deleted:
            self.bus.publish("item.deleted", {"item_id": item_id}, subject_type="item", subject_id=item_id)
        return deleted

    async def close(self) -> None:
        if self.watchlists is not None:
            await self.watchlists.stop()
        if self.watcher is not None:
            await asyncio.to_thread(self.watcher.stop)
        if self.governor is not None:
            await self.governor.stop()
        await self.workers.stop()
        self.vdb.close()
        await self.chat.shutdown()
        if self.engine is not None:
            await self.engine.shutdown()
        if self.mcp is not None:
            await self.mcp.close()
        await self.ollama.aclose()
        if self.provider is not None:
            await self.provider.aclose()
        self.dbs.close()
