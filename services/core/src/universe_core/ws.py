"""WebSocket hub `/ws` (ARCHITECTURE.md §5.2): event stream plus chat ops on one connection."""

import asyncio
import contextlib
import json
from typing import Any

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from universe_common.log import get_logger
from universe_core.chat import ChatError, ChatUnavailable
from universe_core.context import CoreContext

log = get_logger(__name__)
router = APIRouter()

CLOSE_UNAUTHORIZED = 4401
CLOSE_OVERFLOW = 4409
REPLAY_PAGE = 2000
_NOT_JSON = object()


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
            # Page through everything missed before going live: a live event's seq would otherwise move the
            # client's lastSeq past whatever wasn't replayed.
            cursor = since_seq
            while page := ctx.bus.replay(cursor, limit=REPLAY_PAGE):
                for event in page:
                    await websocket.send_json({"kind": "event", "event": event.model_dump(), "replay": True})
                cursor = page[-1].seq or cursor
                if len(page) < REPLAY_PAGE:
                    break
        writer = asyncio.create_task(_writer(websocket, sub))
        try:
            while True:
                frame = await websocket.receive()
                if frame["type"] == "websocket.disconnect":
                    raise WebSocketDisconnect(frame.get("code", 1000))
                try:
                    message = json.loads(frame["text"]) if frame.get("text") is not None else _NOT_JSON
                except json.JSONDecodeError:
                    message = _NOT_JSON
                if message is _NOT_JSON:
                    reply = {"kind": "ack", "op": None, "ok": False, "error": "expected a JSON message"}
                else:
                    reply = await _handle(ctx, sub, message)
                await websocket.send_json(reply)
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
            conversation_id = message.get("conversation_id")
            if conversation_id is not None and not isinstance(conversation_id, str):
                raise ChatError("conversation_id must be a string")
            result = await ctx.chat.send(
                text=str(message.get("text", "")),
                conversation_id=conversation_id,
                agent_id=str(message.get("agent_id") or "core"),
            )
            reply["result"] = result.__dict__
        elif op == "chat.cancel":
            conversation_id = message.get("conversation_id", "")
            if not isinstance(conversation_id, str):
                raise ChatError("conversation_id must be a string")
            reply["result"] = {"cancelled": ctx.chat.cancel(conversation_id)}
        else:
            reply.update(ok=False, error=f"unknown op '{op}'")
    except (ChatError, ChatUnavailable) as exc:
        reply.update(ok=False, error=str(exc))
    except Exception as exc:  # one bad message must not end the connection
        ctx.record_exception(exc)
        reply.update(ok=False, error="Something went wrong; the error was recorded.")
    return reply
