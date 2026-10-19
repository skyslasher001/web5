"""The voice process: one WebSocket per open microphone (ARCHITECTURE §5, `WS /ws/voice`).

Up: binary frames of 16 kHz mono PCM16 from the renderer (captured with Chromium's echo cancellation), and JSON
controls — `mode`, `push`, `speak`, `stop`, `playing`. Down: JSON events (`ready`, `level`, `state`, `final`,
`wake`, `ignored`, `barge_in`, `timeout`, `error`) and the spoken answer as `audio` headers each followed by one
binary frame of 24 kHz PCM16.

Listening (VAD + STT) and speaking (TTS) each run on their own worker thread, so the endpointer keeps hearing
you while an answer is being synthesised — that's what makes barge-in possible. Nothing is written to disk.
"""

import asyncio
import contextlib
import threading
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from universe_voice.audio import float_to_pcm16, pcm16_to_float
from universe_voice.session import MODES, Event, VoiceSession
from universe_voice.stt import STT
from universe_voice.tickets import TicketChecker
from universe_voice.tts import TTS
from universe_voice.vad import VAD, Endpointer
from universe_voice.wake import TranscriptWake

MAX_FRAME_BYTES = 64 * 1024  # ~2 s of audio per message is far more than the renderer sends


@dataclass
class Engines:
    stt: STT | None
    tts: TTS | None
    vad: Callable[[], VAD]  # a fresh VAD per connection: Silero carries recurrent state
    default_voice: str = "af_heart"
    wake_phrase: str = "hey universe"


def create_app(engines: Engines, key: bytes) -> Starlette:
    tickets = TicketChecker(key)

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "ok": True,
                "stt": engines.stt.name if engines.stt else None,
                "tts": engines.tts.name if engines.tts else None,
                "voices": engines.tts.voices() if engines.tts else [],
            }
        )

    async def voice(ws: WebSocket) -> None:
        if not tickets.check(ws.query_params.get("ticket", "")):
            await ws.close(code=4401)
            return
        await ws.accept()
        await Connection(ws, engines).run()

    return Starlette(routes=[Route("/health", health), WebSocketRoute("/ws", voice)])


class Connection:
    def __init__(self, ws: WebSocket, engines: Engines) -> None:
        self.ws, self.engines = ws, engines
        self.loop = asyncio.get_running_loop()
        self.out: asyncio.Queue[Event | bytes | None] = asyncio.Queue()
        self.listen_pool = ThreadPoolExecutor(1, thread_name_prefix="voice-listen")
        self.speak_pool = ThreadPoolExecutor(1, thread_name_prefix="voice-speak")
        self.cancel_speech = threading.Event()
        self.session: VoiceSession | None = None
        if engines.stt is not None:
            self.session = VoiceSession(
                stt=engines.stt,
                endpointer=Endpointer(engines.vad()),
                emit=self.emit,
                wake=TranscriptWake(engines.wake_phrase),
            )

    def emit(self, item: Event | bytes) -> None:
        """Thread-safe: worker threads hand events to the sender task."""
        self.loop.call_soon_threadsafe(self.out.put_nowait, item)

    async def run(self) -> None:
        sender = asyncio.create_task(self._send())
        self.emit(
            {
                "type": "ready",
                "stt": self.engines.stt.name if self.engines.stt else None,
                "tts": self.engines.tts.name if self.engines.tts else None,
                "voices": self.engines.tts.voices() if self.engines.tts else [],
                "mode": self.session.mode if self.session else None,
                "rate": 16000,
            }
        )
        try:
            while True:
                message = await self.ws.receive()
                if message["type"] == "websocket.disconnect":
                    break
                if (data := message.get("bytes")) is not None:
                    self._audio(data)
                elif (text := message.get("text")) is not None:
                    self._control(text)
        except WebSocketDisconnect:
            pass
        finally:
            self.cancel_speech.set()
            self.listen_pool.shutdown(wait=False, cancel_futures=True)
            self.speak_pool.shutdown(wait=False, cancel_futures=True)
            self.out.put_nowait(None)
            with contextlib.suppress(Exception):
                await sender

    async def _send(self) -> None:
        while (item := await self.out.get()) is not None:
            try:
                if isinstance(item, bytes):
                    await self.ws.send_bytes(item)
                else:
                    await self.ws.send_json(item)
            except (WebSocketDisconnect, RuntimeError):
                return

    def _audio(self, data: bytes) -> None:
        if self.session is None or not data or len(data) > MAX_FRAME_BYTES or len(data) % 2:
            return
        self._submit(self.listen_pool, self.session.feed, pcm16_to_float(data))

    def _submit(self, pool: ThreadPoolExecutor, fn: Callable[..., Any], *args: Any) -> None:
        def run() -> None:
            try:
                fn(*args)
            except Exception as exc:  # report, don't kill the connection
                self.emit({"type": "error", "message": f"{type(exc).__name__}: {exc}"})

        with contextlib.suppress(RuntimeError):  # the pool is shut down: the socket is closing
            pool.submit(run)

    def _control(self, text: str) -> None:
        import json

        try:
            msg = json.loads(text)
        except json.JSONDecodeError:
            self.emit({"type": "error", "message": "bad control message"})
            return
        kind = msg.get("type")
        session = self.session
        if kind == "mode" and session and msg.get("mode") in MODES:
            self._submit(self.listen_pool, session.set_mode, msg["mode"])
        elif kind == "push" and session:
            self._submit(self.listen_pool, session.push, bool(msg.get("down")))
        elif kind == "playing" and session:
            session.set_playing(bool(msg.get("playing")))
        elif kind == "stop":
            self.cancel_speech.set()
        elif kind == "speak":
            self.cancel_speech.clear()
            self._submit(self.speak_pool, self._speak, str(msg.get("text", ""))[:4000], msg)
        else:
            self.emit({"type": "error", "message": f"unknown control {kind!r}"})

    def _speak(self, text: str, msg: dict[str, Any]) -> None:
        tts = self.engines.tts
        speech_id = str(msg.get("id", ""))
        if tts is None:
            self.emit({"type": "error", "id": speech_id, "message": "no text-to-speech model is installed"})
            return
        voice = str(msg.get("voice") or self.engines.default_voice)
        if voice not in tts.voices():
            voice = self.engines.default_voice
        seq = 0
        for audio in tts.speak(text, voice, float(msg.get("speed", 1.0))):
            if self.cancel_speech.is_set():
                break
            self.emit({"type": "audio", "id": speech_id, "seq": seq, "rate": tts.rate})
            self.emit(float_to_pcm16(audio))
            seq += 1
        self.emit({"type": "speech_end", "id": speech_id, "chunks": seq, "cancelled": self.cancel_speech.is_set()})
