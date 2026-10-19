"""FastAPI application factory."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from universe_common.errors import capture_exception
from universe_common.log import get_logger
from universe_core import __version__
from universe_core.agents_api import router as agents_router
from universe_core.api import public, router
from universe_core.chat import ChatError, ChatUnavailable
from universe_core.context import CoreContext
from universe_core.forge_api import router as forge_router
from universe_core.research_api import router as research_router
from universe_core.security import LocalGuard, TokenAuth
from universe_core.settings import CoreSettings
from universe_core.universe_api import router as universe_router
from universe_core.vault_admin_api import router as vault_admin_router
from universe_core.vault_api import internal as vault_internal
from universe_core.vault_api import local_api as vault_local_api
from universe_core.vault_api import router as vault_router
from universe_core.voice_api import router as voice_router
from universe_core.voice_api import ws_router as voice_ws_router
from universe_core.ws import router as ws_router

log = get_logger(__name__)


def _problem(status: int, title: str, detail: str) -> JSONResponse:
    return JSONResponse(
        {"type": "about:blank", "title": title, "status": status, "detail": detail},
        status_code=status,
        media_type="application/problem+json",
    )


def create_app(settings: CoreSettings) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        ctx = CoreContext.build(settings)
        app.state.ctx = ctx
        loop = asyncio.get_running_loop()

        def on_loop_error(_loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
            exc = context.get("exception")
            if isinstance(exc, BaseException):
                captured = capture_exception(exc, {"where": str(context.get("message", ""))})
                ctx.errors.record(
                    service="core",
                    kind=captured.kind,
                    message=captured.message,
                    stack=captured.stack,
                    fingerprint=captured.fingerprint,
                    context=captured.context,
                )
            log.error("event_loop_error", message=context.get("message"))

        loop.set_exception_handler(on_loop_error)
        ctx.bus.publish(
            "service.started",
            {"service": "core", "pid": ctx.pid, "version": __version__, "safe_mode": settings.safe_mode},
        )
        if settings.start_reason != "boot":
            ctx.bus.publish(
                "service.restarted",
                {
                    "service": "core",
                    "reason": settings.start_reason,
                    "restarts": settings.restart_count,
                    "last_exit": settings.last_exit or None,
                },
            )
        if settings.safe_mode:
            ctx.bus.publish("safe_mode.entered", {"service": "core", "reason": settings.start_reason})
        warm = asyncio.create_task(ctx.hardware())  # warm the cache for model recommendations
        await ctx.start_background()
        log.info("core_started", port=settings.port, safe_mode=settings.safe_mode, vault=str(settings.vault_dir))
        try:
            yield
        finally:
            warm.cancel()
            await ctx.close()

    app = FastAPI(title="UNIVERSE Core", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.include_router(public)
    app.include_router(router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(vault_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(agents_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(universe_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(forge_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(research_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(voice_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(vault_admin_router, dependencies=[Depends(TokenAuth(settings.session_token))])
    app.include_router(vault_local_api)  # session token or a scoped local API key, checked per endpoint
    app.include_router(vault_internal)  # Core's own workers (per-boot internal token)
    app.include_router(ws_router)
    app.include_router(voice_ws_router)  # /ws/voice: session ticket, relayed to the voice process

    @app.exception_handler(ChatError)
    async def chat_error(_request: Request, exc: ChatError) -> JSONResponse:
        return _problem(400, "Bad request", str(exc))

    @app.exception_handler(ChatUnavailable)
    async def chat_unavailable(_request: Request, exc: ChatUnavailable) -> JSONResponse:
        return _problem(503, "Unavailable", str(exc))

    @app.exception_handler(Exception)
    async def unexpected(request: Request, exc: Exception) -> JSONResponse:
        ctx: CoreContext | None = getattr(request.app.state, "ctx", None)
        captured = capture_exception(exc, {"path": request.url.path, "method": request.method})
        if ctx is not None:
            ctx.errors.record(
                service="core",
                kind=captured.kind,
                message=captured.message,
                stack=captured.stack,
                fingerprint=captured.fingerprint,
                context=captured.context,
            )
        log.exception("unhandled_request_error", path=request.url.path)
        return _problem(500, "Internal error", "The error was recorded.")

    # Order matters: LocalGuard (outermost) → CORS (only our own origins) → app.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=list(settings.allowed_origins),
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type"],
        max_age=600,
    )
    app.add_middleware(LocalGuard, port=settings.port, allowed_origins=settings.allowed_origins)
    return app
