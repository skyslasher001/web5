"""A minimal MCP client over stdio (ADR-0011 §8): initialize, tools/list, tools/call.

Each MCP server you add is a local program UNIVERSE starts. Its tools become agent tools named
`mcp.<server>.<tool>`: tier `write`, with side effects and possibly network access, and their output is
untrusted, so the policy engine asks you before each call until you set a rule.

Protocol: JSON-RPC 2.0, one JSON message per line on stdin/stdout, the `initialize` handshake of the
2024-11-05 … 2025-11-25 revisions.
"""

import asyncio
import contextlib
import json
import os
import re
import shutil
import sqlite3
import sys
from typing import TYPE_CHECKING, Any

from pydantic import BaseModel, ConfigDict, Field

from universe_agents.tools import Tool, ToolContext, ToolResult
from universe_common.ids import uuid7
from universe_common.log import get_logger
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow

if TYPE_CHECKING:
    from universe_core.context import CoreContext

log = get_logger(__name__)

PROTOCOL_VERSION = "2025-11-25"
HANDSHAKE_VERSIONS = {"2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"}
MAX_LINE = 16 * 1024 * 1024
_NAME = re.compile(r"^[a-z][a-z0-9-]{0,31}$")


class MCPError(RuntimeError):
    """The server failed, refused, or spoke something else. User-presentable."""


class RawArgs(BaseModel):
    """MCP tools describe their own arguments (JSON Schema); the server validates them."""

    model_config = ConfigDict(extra="allow")


# Core's own secrets: an MCP server is someone else's program and must not be able to call Core or the supervisor.
_SCRUBBED_ENV = ("UNIVERSE_SESSION", "UNIVERSE_SUPERVISOR", "UNIVERSE_INTERNAL")
_CREATE_NO_WINDOW = 0x08000000


def server_env(extra: dict[str, str]) -> dict[str, str]:
    return {**{k: v for k, v in os.environ.items() if not k.startswith(_SCRUBBED_ENV)}, **extra}


def resolve_command(command: str) -> str:
    """Find a bare command on PATH the way a shell would: on Windows `npx` is `npx.cmd`, which CreateProcess
    won't find by itself. Paths, and commands not found (the start then fails with a clear error), stay as they are."""
    if os.path.dirname(command):
        return command
    return shutil.which(command) or command


def spawn_options(platform: str = sys.platform) -> dict[str, Any]:
    """No console window flashing up for each server on Windows."""
    return {"creationflags": _CREATE_NO_WINDOW} if platform == "win32" else {}


class MCPConnection:
    def __init__(self, name: str, command: str, args: list[str], env: dict[str, str]) -> None:
        self.name = name
        self.command = command
        self.args = args
        self.env = env
        self.server_info: dict[str, Any] = {}
        self.protocol: str | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._reader: asyncio.Task[None] | None = None
        self._pending: dict[int, asyncio.Future[dict[str, Any]]] = {}
        self._next = 0
        self._write_lock = asyncio.Lock()
        self.stderr_tail: list[str] = []

    async def start(self, wait_s: float = 20.0) -> None:
        try:
            self._proc = await asyncio.create_subprocess_exec(
                resolve_command(self.command),
                *self.args,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env=server_env(self.env),
                limit=MAX_LINE,
                **spawn_options(),
            )
        except OSError as exc:
            raise MCPError(f"cannot start '{self.command}': {exc}") from exc
        self._reader = asyncio.create_task(self._read(), name=f"mcp:{self.name}")
        asyncio.create_task(self._drain_stderr(), name=f"mcp-stderr:{self.name}")  # noqa: RUF006
        result = await self.request(
            "initialize",
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {},
                "clientInfo": {"name": "UNIVERSE", "version": "0.3"},
            },
            wait_s=wait_s,
        )
        version = result.get("protocolVersion")
        if version not in HANDSHAKE_VERSIONS:
            await self.close()
            raise MCPError(f"{self.name} speaks MCP {version}, which UNIVERSE doesn't support yet")
        self.protocol = version
        self.server_info = result.get("serverInfo") or {}
        await self.notify("notifications/initialized", {})

    async def _drain_stderr(self) -> None:
        assert self._proc is not None and self._proc.stderr is not None
        while line := await self._proc.stderr.readline():
            self.stderr_tail = [*self.stderr_tail, line.decode("utf-8", errors="replace").rstrip()][-20:]

    async def _read(self) -> None:
        assert self._proc is not None and self._proc.stdout is not None
        try:
            while line := await self._proc.stdout.readline():
                try:
                    message = json.loads(line)
                except json.JSONDecodeError:
                    continue  # servers may log to stdout by mistake; skip what isn't JSON-RPC
                if not isinstance(message, dict):
                    continue
                if "method" in message:
                    if "id" in message:  # a request from the server (sampling, roots…): not offered
                        await self._send(
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "error": {"code": -32601, "message": "UNIVERSE does not support this request"},
                            }
                        )
                    continue
                future = self._pending.pop(message.get("id"), None)  # type: ignore[arg-type]
                if future is not None and not future.done():
                    future.set_result(message)
        finally:
            for future in self._pending.values():
                if not future.done():
                    future.set_exception(MCPError(f"{self.name} stopped: {' '.join(self.stderr_tail[-3:])}"))
            self._pending.clear()

    async def _send(self, message: dict[str, Any]) -> None:
        if self._proc is None or self._proc.stdin is None or self._proc.returncode is not None:
            raise MCPError(f"{self.name} is not running")
        async with self._write_lock:
            self._proc.stdin.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
            await self._proc.stdin.drain()

    async def request(self, method: str, params: dict[str, Any], *, wait_s: float = 60.0) -> dict[str, Any]:
        self._next += 1
        request_id = self._next
        future: asyncio.Future[dict[str, Any]] = asyncio.get_running_loop().create_future()
        self._pending[request_id] = future
        await self._send({"jsonrpc": "2.0", "id": request_id, "method": method, "params": params})
        try:
            message = await asyncio.wait_for(future, timeout=wait_s)
        except TimeoutError as exc:
            self._pending.pop(request_id, None)
            raise MCPError(f"{self.name} didn't answer {method} within {wait_s:.0f} s") from exc
        if "error" in message:
            error = message["error"]
            if not isinstance(error, dict):
                raise MCPError(f"{self.name}: {str(error)[:200] or 'error'}")
            raise MCPError(f"{self.name}: {error.get('message', 'error')} ({error.get('code')})")
        result = message.get("result") or {}
        if not isinstance(result, dict):
            raise MCPError(f"{self.name} answered {method} with something other than an object")
        return result

    async def notify(self, method: str, params: dict[str, Any]) -> None:
        await self._send({"jsonrpc": "2.0", "method": method, "params": params})

    async def list_tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        cursor: str | None = None
        for _ in range(50):  # pages
            result = await self.request("tools/list", {"cursor": cursor} if cursor else {})
            tools.extend(t for t in result.get("tools") or [] if isinstance(t, dict) and t.get("name"))
            cursor = result.get("nextCursor")
            if not cursor:
                break
        return tools

    async def call_tool(self, name: str, arguments: dict[str, Any], wait_s: float = 120.0) -> tuple[str, bool]:
        """Returns (text, is_error)."""
        result = await self.request("tools/call", {"name": name, "arguments": arguments}, wait_s=wait_s)
        parts: list[str] = []
        for block in result.get("content") or []:
            kind = block.get("type")
            if kind == "text":
                parts.append(str(block.get("text", "")))
            elif kind == "resource" and isinstance(block.get("resource"), dict):
                parts.append(str(block["resource"].get("text") or f"[resource {block['resource'].get('uri')}]"))
            else:
                parts.append(f"[{kind} content]")
        if not parts and result.get("structuredContent") is not None:
            parts.append(json.dumps(result["structuredContent"], ensure_ascii=False))
        return "\n".join(parts), bool(result.get("isError"))

    @property
    def running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def close(self) -> None:
        proc = self._proc
        if proc is None:
            return
        if proc.stdin is not None:
            with contextlib.suppress(Exception):
                proc.stdin.close()
        if proc.returncode is None:
            with contextlib.suppress(ProcessLookupError):
                proc.terminate()
            try:
                await asyncio.wait_for(proc.wait(), timeout=3)
            except TimeoutError:
                with contextlib.suppress(ProcessLookupError):
                    proc.kill()
                await proc.wait()
        if self._reader is not None:
            self._reader.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._reader


# ---------- servers you add (Core) ----------


class MCPServerRequest(BaseModel):
    name: str = Field(pattern=_NAME.pattern, description="Short name: lowercase letters, digits and '-'")
    command: str = Field(min_length=1, max_length=1000)
    args: list[str] = Field(default_factory=list, max_length=50)
    env: dict[str, str] = Field(default_factory=dict, max_length=50)


class MCPServerInfo(ApiModel):
    id: str
    name: str
    command: str
    args: list[str]
    enabled: bool
    running: bool
    tools: list[str]
    error: str | None
    created_at: str


def _tool_name(server: str, tool: str) -> str:
    return f"mcp.{server}.{re.sub(r'[^A-Za-z0-9_-]', '_', tool)}"


class MCPManager:
    """Starts the servers you added, keeps their tools registered, and stops them with Core."""

    def __init__(self, ctx: "CoreContext") -> None:
        self._ctx = ctx
        self._connections: dict[str, MCPConnection] = {}
        self._errors: dict[str, str] = {}
        self._tools: dict[str, list[str]] = {}
        self._starting: asyncio.Task[None] | None = None

    @property
    def _conn(self) -> sqlite3.Connection:
        return self._ctx.dbs.universe

    def _rows(self) -> list[sqlite3.Row]:
        return self._conn.execute("SELECT * FROM mcp_servers ORDER BY name").fetchall()

    def list(self) -> list[MCPServerInfo]:
        return [self._info(r) for r in self._rows()]

    def _info(self, row: sqlite3.Row) -> MCPServerInfo:
        connection = self._connections.get(row["id"])
        return MCPServerInfo(
            id=row["id"],
            name=row["name"],
            command=row["command"],
            args=json.loads(row["args"]),
            enabled=bool(row["enabled"]),
            running=bool(connection and connection.running),
            tools=self._tools.get(row["id"], []),
            error=self._errors.get(row["id"]),
            created_at=row["created_at"],
        )

    async def start_all(self) -> None:
        await asyncio.gather(*(self._start(row) for row in self._rows() if row["enabled"]))

    def start_in_background(self) -> None:
        """At boot: Core must answer /health within the supervisor's timeout, and a server may take 20 s or more."""
        self._starting = asyncio.create_task(self.start_all(), name="mcp-start")

    async def add(self, request: MCPServerRequest) -> MCPServerInfo:
        """From your UI session only: running a program is your decision, and it's audited."""
        if self._conn.execute("SELECT 1 FROM mcp_servers WHERE name = ?", (request.name,)).fetchone():
            raise ValueError(f"an MCP server named '{request.name}' already exists")
        now = utcnow()
        row = self._conn.execute(
            "INSERT INTO mcp_servers (id, name, command, args, env, enabled, created_at, updated_at)"
            " VALUES (?, ?, ?, ?, ?, 1, ?, ?) RETURNING *",
            (uuid7(), request.name, request.command, json.dumps(request.args), json.dumps(request.env), now, now),
        ).fetchone()
        # The command and arguments are ids of what runs, not vault content; env values may be secrets.
        self._ctx.audit.append(
            actor="user",
            action="mcp.server_added",
            target_type="mcp_server",
            target_id=row["id"],
            details={
                "name": request.name,
                "command": request.command,
                "args": request.args,
                "env_keys": sorted(request.env),
            },
        )
        await self._start(row)
        return self._info(row)

    async def remove(self, server_id: str) -> bool:
        await self._stop(server_id)
        removed = bool(self._conn.execute("DELETE FROM mcp_servers WHERE id = ?", (server_id,)).rowcount)
        if removed:
            self._ctx.audit.append(
                actor="user", action="mcp.server_removed", target_type="mcp_server", target_id=server_id, details={}
            )
        return removed

    async def set_enabled(self, server_id: str, enabled: bool) -> MCPServerInfo | None:
        self._conn.execute(
            "UPDATE mcp_servers SET enabled = ?, updated_at = ? WHERE id = ?", (int(enabled), utcnow(), server_id)
        )
        row = self._conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            return None
        if enabled:
            await self._start(row)
        else:
            await self._stop(server_id)
        return self._info(row)

    async def restart(self, server_id: str) -> MCPServerInfo | None:
        row = self._conn.execute("SELECT * FROM mcp_servers WHERE id = ?", (server_id,)).fetchone()
        if row is None:
            return None
        await self._stop(server_id)
        await self._start(row)
        return self._info(row)

    async def _start(self, row: sqlite3.Row) -> None:
        server_id, name = row["id"], row["name"]
        await self._stop(server_id)
        connection = MCPConnection(name, row["command"], json.loads(row["args"]), json.loads(row["env"]))
        try:
            await connection.start()
            tools = await connection.list_tools()
        except asyncio.CancelledError:  # Core is stopping: don't leave the program running
            await connection.close()
            raise
        except Exception as exc:  # one broken server must not stop the others (or Core's boot)
            await connection.close()
            error = str(exc) if isinstance(exc, MCPError) else f"{name} failed to start ({type(exc).__name__})"
            self._errors[server_id] = error
            log.warning("mcp_server_failed", server=name, error=error)
            if not isinstance(exc, MCPError):
                self._ctx.record_exception(exc)
            return
        self._connections[server_id] = connection
        self._errors.pop(server_id, None)
        registered = []
        for spec in tools:
            tool = self._wrap(connection, spec)
            self._ctx.tools.remove(tool.name)
            self._ctx.tools.add(tool)
            registered.append(tool.name)
        self._tools[server_id] = sorted(registered)
        log.info("mcp_server_started", server=name, tools=len(registered), protocol=connection.protocol)

    async def _stop(self, server_id: str) -> None:
        connection = self._connections.pop(server_id, None)
        for name in self._tools.pop(server_id, []):
            self._ctx.tools.remove(name)
        if connection is not None:
            await connection.close()

    async def close(self) -> None:
        if self._starting is not None:
            self._starting.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._starting
        for server_id in list(self._connections):
            await self._stop(server_id)

    def _wrap(self, connection: MCPConnection, spec: dict[str, Any]) -> Tool:
        remote = str(spec["name"])
        schema = spec.get("inputSchema") if isinstance(spec.get("inputSchema"), dict) else {"type": "object"}

        async def run(args: BaseModel, _ctx: ToolContext) -> ToolResult:
            if not connection.running:
                raise LookupError(f"the MCP server {connection.name} is not running")
            try:
                text, is_error = await connection.call_tool(remote, args.model_dump())
            except MCPError as exc:
                return ToolResult(f"Error: {exc}", error=True)
            return ToolResult(text or "(no output)", untrusted=True, error=is_error)

        return Tool(
            name=_tool_name(connection.name, remote),
            description=f"[MCP server {connection.name}] {str(spec.get('description') or remote)[:500]}",
            input_model=RawArgs,
            tier="write",
            run=run,
            side_effects=True,
            network=True,  # unknown: assume it may reach the internet
            timeout_s=120,
            raw_schema=schema,
            ask_first=True,
            summarize=lambda a, server=connection.name, tool=remote: (
                f"Run {tool} on the MCP server {server} with {json.dumps(a.model_dump())[:160]}"
            ),
        )
