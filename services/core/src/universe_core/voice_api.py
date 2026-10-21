"""REST for voice (Phase 7, ADR-0016): turn voice on and off, settings, per-agent voices, model installs, and
saving a voice memo to the vault; plus the audio socket.

Audio streams over `WS /ws/voice` (a Core session ticket, like `/ws`): Core relays it to the voice process on
loopback, so the process's port stays private and the renderer's CSP only ever allows Core. Nothing is stored,
except a memo: you pressed record and then save, so the WAV is kept as a `voice_memo` item and the pipeline
transcribes it.
"""

import asyncio
import contextlib
import sqlite3
from typing import Annotated, Literal

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query, Request, WebSocket, WebSocketDisconnect, status
from pydantic import BaseModel, Field
from websockets.asyncio.client import ClientConnection, connect
from websockets.exceptions import ConnectionClosed, InvalidStatus

from universe_common.ids import uuid7
from universe_common.schema import ApiModel
from universe_common.timeutil import utcnow
from universe_core.context import CoreContext
from universe_core.voice_runtime import VoiceConfig, agent_voice, dump_config
from universe_vault import ingest
from universe_voice import models

router = APIRouter(prefix="/api/v1")
ws_router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_VOICE_OFF = 4503

MAX_MEMO_BYTES = 200 * 1024 * 1024  # ~1h50m of 16 kHz mono PCM16
SETTINGS_KEY = "voice.config"


def get_ctx(request: Request) -> CoreContext:
    return request.app.state.ctx


Ctx = Annotated[CoreContext, Depends(get_ctx)]


class VoiceModelInfo(ApiModel):
    id: str
    kind: Literal["stt", "tts", "vad"]
    title: str
    license: str
    source: str
    size: int
    installed: bool
    install_state: Literal["downloading", "installing", "done", "failed"] | None = None
    install_done: int = 0
    install_error: str | None = None


class VoiceSettings(ApiModel):
    stt: str | None
    wake_phrase: str
    voice: str
    mode: Literal["push_to_talk", "wake", "continuous"]
    speed: float
    agents: dict[str, str]


class VoiceStatus(ApiModel):
    state: Literal["off", "starting", "ready", "failed"]
    reason: str | None
    pid: int | None
    stt: str | None
    tts: str | None
    voices: list[str]
    settings: VoiceSettings
    models: list[VoiceModelInfo]


class AgentVoice(ApiModel):
    agent_id: str
    name: str
    voice: str
    color: str | None


class VoicesResponse(ApiModel):
    voices: list[str]
    default: str
    agents: list[AgentVoice]


class VoiceSettingsUpdate(BaseModel):
    stt: str | None = Field(default=None, description="A Whisper model id; null for the best installed")
    wake_phrase: str | None = Field(default=None, min_length=3, max_length=60)
    voice: str | None = Field(default=None, min_length=2, max_length=40)
    mode: Literal["push_to_talk", "wake", "continuous"] | None = None
    speed: float | None = Field(default=None, ge=0.5, le=2.0)
    agents: dict[str, str] | None = None


class MemoSaved(ApiModel):
    item_id: str
    status: Literal["created", "duplicate"]


def _settings(config: VoiceConfig) -> VoiceSettings:
    return VoiceSettings(
        stt=config.stt,
        wake_phrase=config.wake_phrase,
        voice=config.voice,
        mode=config.mode,
        speed=config.speed,
        agents=dict(config.agents),
    )


def _models(ctx: CoreContext) -> list[VoiceModelInfo]:
    voice = ctx.require_voice()
    out = []
    for model in models.CATALOG:
        install = voice.installer.installs.get(model.id)
        out.append(
            VoiceModelInfo(
                id=model.id,
                kind=model.kind,
                title=model.title,
                license=model.license,
                source=model.source,
                size=model.size,
                installed=models.installed(voice.models_dir, model),
                install_state=install.state if install else None,
                install_done=install.done if install else 0,
                install_error=install.error if install else None,
            )
        )
    return out


def _status(ctx: CoreContext) -> VoiceStatus:
    voice = ctx.require_voice()
    s = voice.manager.status()
    return VoiceStatus(**s, settings=_settings(voice.config()), models=_models(ctx))


@router.get("/voice/status", response_model=VoiceStatus)
async def voice_status(ctx: Ctx) -> VoiceStatus:
    return _status(ctx)


@router.post("/voice/start", response_model=VoiceStatus)
async def voice_start(ctx: Ctx) -> VoiceStatus:
    voice = ctx.require_voice()
    if ctx.gate.killed:
        raise HTTPException(status.HTTP_409_CONFLICT, "The kill switch is engaged; voice stays off")
    if ctx.settings.safe_mode:
        raise HTTPException(status.HTTP_409_CONFLICT, "Voice is off in safe mode")
    await voice.manager.start(voice.config())
    ctx.audit.append(actor="user", action="voice.started", target_type="service", target_id="voice", details={})
    return _status(ctx)


@router.post("/voice/stop", response_model=VoiceStatus)
async def voice_stop(ctx: Ctx) -> VoiceStatus:
    voice = ctx.require_voice()
    await voice.manager.stop()
    ctx.audit.append(actor="user", action="voice.stopped", target_type="service", target_id="voice", details={})
    return _status(ctx)


@router.put("/voice/settings", response_model=VoiceStatus)
async def voice_settings(ctx: Ctx, body: VoiceSettingsUpdate) -> VoiceStatus:
    voice = ctx.require_voice()
    config = voice.config()
    changes = body.model_dump(exclude_unset=True)
    if "stt" in changes and changes["stt"] is not None:
        model = models.BY_ID.get(changes["stt"])
        if model is None or model.kind != "stt":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown speech-to-text model {changes['stt']!r}")
    for key, value in changes.items():
        if key == "wake_phrase" and value is not None:
            value = " ".join(value.lower().split())
        if value is not None or key == "stt":
            setattr(config, key, value)
    ctx.dbs.universe.execute(
        "INSERT INTO settings (key, value, updated_at) VALUES (?, ?, ?)"
        " ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (SETTINGS_KEY, dump_config(config), utcnow()),
    )
    ctx.audit.append(
        actor="user", action="setting.changed", target_type="setting", target_id=SETTINGS_KEY, details=changes
    )
    ctx.bus.publish("voice.settings.changed", {"changed": sorted(changes)}, actor="user")
    # The process reads the engine settings at start; mode, speed and voices travel with each message.
    if {"stt", "wake_phrase", "voice"} & changes.keys() and voice.manager.state in ("ready", "starting"):
        await voice.manager.restart(config)
    return _status(ctx)


@router.get("/voices", response_model=VoicesResponse)
async def voices(ctx: Ctx) -> VoicesResponse:
    voice = ctx.require_voice()
    config = voice.config()
    available = voice.manager.status()["voices"]
    agents = [
        AgentVoice(agent_id=a.id, name=a.name, voice=agent_voice(config, a.id, a.voice), color=a.color)
        for a in sorted(ctx.agents.values(), key=lambda a: a.id)
    ]
    return VoicesResponse(voices=available, default=config.voice, agents=agents)


@router.post("/voice/models/{model_id}/install", response_model=VoiceModelInfo, status_code=202)
async def install_model(ctx: Ctx, model_id: str) -> VoiceModelInfo:
    voice = ctx.require_voice()
    model = models.BY_ID.get(model_id)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unknown voice model {model_id!r}")
    if ctx.gate.offline or ctx.gate.killed:
        why = "offline mode is on" if ctx.gate.offline else "the kill switch is engaged"
        raise HTTPException(status.HTTP_409_CONFLICT, f"Can't download while {why}")
    if not models.installed(voice.models_dir, model):
        voice.installer.start(model)
        ctx.audit.append(
            actor="user",
            action="model.pulled",
            target_type="voice_model",
            target_id=model.id,
            details={"urls": [d.url for d in model.downloads], "sha256": [d.sha256 for d in model.downloads]},
        )
    return next(m for m in _models(ctx) if m.id == model_id)


@router.post("/voice/memo", response_model=MemoSaved, status_code=status.HTTP_201_CREATED)
async def save_memo(
    ctx: Ctx,
    request: Request,
    title: Annotated[str | None, Query(max_length=120)] = None,
    project_id: Annotated[str | None, Query()] = None,
) -> MemoSaved:
    """A recorded WAV (the request body, `audio/wav`). Stored as a `voice_memo`; the pipeline transcribes it."""
    if request.headers.get("content-type", "").split(";")[0].strip() not in ("audio/wav", "audio/x-wav"):
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Send the memo as audio/wav")
    staging = ctx.vault.cache / "uploads"
    staging.mkdir(parents=True, exist_ok=True)
    name = "".join(c for c in (title or "") if c.isalnum() or c in " -_").strip() or f"Voice memo {utcnow()[:16]}"
    name = name.replace(":", "-")
    staged = staging / f"{uuid7()}.wav"
    size, head = 0, b""
    try:
        with staged.open("wb") as out:
            async for chunk in request.stream():
                size += len(chunk)
                if size > MAX_MEMO_BYTES:
                    raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "The memo is too long")
                head = head or chunk[:12]
                out.write(chunk)
        if size < 44 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Not a WAV file")

        def save(conn: sqlite3.Connection) -> ingest.ImportResult:
            return ingest.import_file(
                conn,
                ctx.vault,
                staged,
                source_kind="quick_capture",
                origin="voice memo",
                name=f"{name}.wav",
                project_ids=[project_id] if project_id else [],
                item_type="voice_memo",
            )

        result = await ctx.vdb.run(save)
    finally:
        await asyncio.to_thread(staged.unlink, missing_ok=True)
    if result.item_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, result.reason or "The memo couldn't be saved")
    if result.status == "created":
        ctx.bus.publish(
            "item.created",
            {"item_id": result.item_id, "type": "voice_memo", "title": name, "path": result.path},
            actor="user",
            subject_type="item",
            subject_id=result.item_id,
        )
    return MemoSaved(item_id=result.item_id, status="duplicate" if result.status == "duplicate" else "created")


# ---------- the audio socket ----------


@ws_router.websocket("/ws/voice")
async def voice_socket(websocket: WebSocket, ticket: str = "") -> None:
    """Relay between the renderer and the voice process: PCM and control JSON up, events and speech down."""
    ctx: CoreContext = websocket.app.state.ctx
    if not ctx.tickets.consume(ticket):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    voice = ctx.voice
    url = voice.manager.url if voice is not None else None
    if voice is None or url is None:
        await websocket.close(code=CLOSE_VOICE_OFF, reason="voice is not running")
        return
    ctx.gate.check(httpx.URL(url), purpose="voice", local_only=True, actor="user")  # loopback only, by construction
    await websocket.accept()
    try:
        async with connect(
            f"{url}?ticket={voice.manager.ticket()}",
            max_size=4 * 1024 * 1024,
            compression=None,
            open_timeout=10,
            proxy=None,  # loopback only: never via a system or corporate proxy (websockets reads env/registry)
        ) as upstream:
            down = asyncio.create_task(_relay_down(upstream, websocket))
            try:
                while True:
                    message = await websocket.receive()
                    if message["type"] == "websocket.disconnect":
                        break
                    if (data := message.get("bytes")) is not None:
                        await upstream.send(data)
                    elif (text := message.get("text")) is not None:
                        await upstream.send(text)
            finally:
                down.cancel()
                with contextlib.suppress(asyncio.CancelledError, ConnectionClosed):
                    await down
    except (OSError, ConnectionClosed, InvalidStatus, TimeoutError) as exc:
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=CLOSE_VOICE_OFF, reason=f"voice connection lost ({type(exc).__name__})")
    except WebSocketDisconnect:
        pass


async def _relay_down(upstream: ClientConnection, websocket: WebSocket) -> None:
    async for message in upstream:
        if isinstance(message, bytes):
            await websocket.send_bytes(message)
        else:
            await websocket.send_text(message)
    with contextlib.suppress(RuntimeError):  # the voice process went away: tell the renderer
        await websocket.close(code=CLOSE_VOICE_OFF, reason="voice stopped")
