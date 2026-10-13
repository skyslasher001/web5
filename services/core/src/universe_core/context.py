"""Everything a running Core holds, built once in the app lifespan."""

import asyncio
import os
import secrets
import time
from dataclasses import dataclass, field

import httpx
from universe_vault import purge
from universe_vault.layout import Vault
from universe_vault.models import ModelInfo, pick_embedder, query_prefix
from universe_vault.vectors import VectorStore, table_name

from universe_agents.providers import OpenAICompatibleProvider
from universe_agents.registry import AgentDefinition, load_agents
from universe_agents.router import ModelRouter
from universe_common.egress import EgressGate
from universe_common.log import get_logger, register_secret
from universe_common.timeutil import utcnow
from universe_core.chat import ChatService
from universe_core.db import Databases
from universe_core.errors import ErrorStore
from universe_core.events import EventBus
from universe_core.protected.audit import AuditWriter
from universe_core.security import TicketStore
from universe_core.seed import ensure_seed_galaxies
from universe_core.settings import CoreSettings
from universe_core.vault_runtime import Governor, VaultDb, WorkerManager, worker_env
from universe_models.hardware import HardwareInfo, detect
from universe_models.ollama import OllamaClient
from universe_models.recommend import Recommendation, recommend

log = get_logger(__name__)

ROUTER_TIERS = ("local-fast", "local-large")


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
    governor: Governor | None = None
    started: float = field(default_factory=time.monotonic)
    pid: int = field(default_factory=os.getpid)
    provider: OpenAICompatibleProvider | None = None
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
        ctx.provider = provider
        ensure_seed_galaxies(dbs.universe, bus)
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
        await self.workers.start()
        self.governor = Governor(
            conn=self.dbs.universe,
            vault=self.vault,
            chat_active=lambda: len(self.chat.active_conversations),
            current_embedder=self.current_embedder,
            purge_item=self.purge_item,
            publish=lambda event_type, payload: self.bus.publish(event_type, payload),
        )
        self.governor.start()

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
        if self.governor is not None:
            await self.governor.stop()
        await self.workers.stop()
        self.vdb.close()
        await self.chat.shutdown()
        await self.ollama.aclose()
        if self.provider is not None:
            await self.provider.aclose()
        self.dbs.close()
