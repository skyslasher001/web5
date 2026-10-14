"""WebSocket hub `/ws` (ARCHITECTURE.md §5.2): event stream plus chat ops on one connection."""

import asyncio
import contextlib
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from universe_common.log import get_logger
from universe_core.chat import ChatError, ChatUnavailable
from universe_core.context import CoreContext

log = get_logger(__name__)
router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_OVERFLOW = 4409


@router.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket, ticket: str = "", since_seq: int | None = None) -> None:
    ctx: CoreContext = websocket.app.state.ctx
    if not ctx.tickets.consume(ticket):
        await websocket.close(code=CLOSE_UNAUTHORIZED)
        return
    await websocket.accept()
    # Subscribe before replaying so nothing published in between is lost; clients dedupe by seq.
    sub = ctx.bus.subscribe(["*"])
    try:
        if since_seq is not None:
            for event in ctx.bus.replay(since_seq, limit=2000):
                await websocket.send_json({"kind": "event", "event": event.model_dump(), "replay": True})
        writer = asyncio.create_task(_writer(websocket, sub))
        try:
            while True:
                message = await websocket.receive_json()
                await websocket.send_json(await _handle(ctx, sub, message))
        finally:
            writer.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await writer
    except WebSocketDisconnect:
        pass
    finally:
        ctx.bus.unsubscribe(sub)


async def _writer(websocket: WebSocket, sub: Any) -> None:
    while True:
        event = await sub.queue.get()
        await websocket.send_json({"kind": "event", "event": event.model_dump()})
        if sub.overflowed:
            await websocket.close(code=CLOSE_OVERFLOW)
            return


async def _handle(ctx: CoreContext, sub: Any, message: Any) -> dict[str, Any]:
    if not isinstance(message, dict) or not isinstance(message.get("op"), str):
        return {"kind": "ack", "op": None, "ok": False, "error": "expected {op: string, ...}"}
    op = message["op"]
    request_id = message.get("id")
    reply: dict[str, Any] = {"kind": "ack", "op": op, "id": request_id, "ok": True}
    try:
        if op == "ping":
            reply["kind"] = "pong"
        elif op == "subscribe":
            topics = message.get("topics")
            if not isinstance(topics, list) or not all(isinstance(t, str) for t in topics):
                raise ChatError("topics must be a list of strings")
            sub.patterns = topics
        elif op == "chat.send":
            result = await ctx.chat.send(
                text=str(message.get("text", "")),
                conversation_id=message.get("conversation_id"),
                agent_id=str(message.get("agent_id") or "core"),
            )
            reply["result"] = result.__dict__
        elif op == "chat.cancel":
            reply["result"] = {"cancelled": ctx.chat.cancel(str(message.get("conversation_id", "")))}
        else:
            reply.update(ok=False, error=f"unknown op '{op}'")
    except (ChatError, ChatUnavailable) as exc:
        reply.update(ok=False, error=str(exc))
    return reply
