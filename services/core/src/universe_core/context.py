"""Everything a running Core holds, built once in the app lifespan."""

import asyncio
import os
import time
from dataclasses import dataclass, field

from universe_agents.providers import OpenAICompatibleProvider
from universe_agents.registry import AgentDefinition, load_agents
from universe_agents.router import ModelRouter
from universe_common.egress import EgressGate
from universe_common.log import get_logger
from universe_common.timeutil import utcnow
from universe_core.chat import ChatService
from universe_core.db import Databases
from universe_core.errors import ErrorStore
from universe_core.events import EventBus
from universe_core.protected.audit import AuditWriter
from universe_core.security import TicketStore
from universe_core.seed import ensure_seed_galaxies
from universe_core.settings import CoreSettings
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

    async def close(self) -> None:
        await self.chat.shutdown()
        await self.ollama.aclose()
        if self.provider is not None:
            await self.provider.aclose()
        self.dbs.close()
