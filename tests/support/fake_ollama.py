"""A protocol-faithful stand-in for Ollama, used by tests and the Electron E2E run.

Speaks the parts of Ollama's API that UNIVERSE uses: /api/version, /api/tags, /api/show and the
OpenAI-compatible streaming /v1/chat/completions. Replies echo the last user message word by word.
Special inputs: "[[fail]]" → HTTP 500, "[[slow]]" → 200 tokens at 50 ms each (for cancel tests).

Run standalone: python tests/support/fake_ollama.py --port 11500
"""

import argparse
import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

CHAT_MODEL = "fake-chat:latest"
EMBED_MODEL = "fake-embed:latest"


class FakeOllama(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0, *, delay_s: float = 0.01, with_models: bool = True) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.delay_s = delay_s
        self.with_models = with_models
        self.chat_requests: list[dict] = []
        self.show_requests = 0
        self.capabilities_in_tags = False  # Ollama >= 0.12 lists capabilities in /api/tags
        self.tags_status = 200  # set to 500 to make /api/tags fail while /api/version still answers

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.server_address[1]}"

    def start(self) -> "FakeOllama":
        threading.Thread(target=self.serve_forever, daemon=True).start()
        return self

    def stop(self) -> None:
        self.shutdown()
        self.server_close()


class _Handler(BaseHTTPRequestHandler):
    @property
    def srv(self) -> FakeOllama:
        return cast(FakeOllama, self.server)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _json(self, status: int, body: object) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}")

    def do_GET(self) -> None:
        if self.path == "/api/version":
            self._json(200, {"version": "0.0.0-fake"})
        elif self.path == "/api/tags" and self.srv.tags_status != 200:
            self._json(self.srv.tags_status, {"error": "simulated failure"})
        elif self.path == "/api/tags":
            models = []
            if self.srv.with_models:
                models = [
                    {
                        "name": CHAT_MODEL,
                        "size": 1_000_000,
                        "digest": "aaa",
                        "details": {"family": "fake", "parameter_size": "1B", "quantization_level": "Q4_K_M"},
                    },
                    {"name": EMBED_MODEL, "size": 100_000, "digest": "bbb", "details": {"family": "nomic-bert"}},
                ]
                if self.srv.capabilities_in_tags:
                    models[0]["capabilities"] = ["completion", "tools"]
                    models[1]["capabilities"] = ["embedding"]
            self._json(200, {"models": models})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._body()
        if self.path == "/api/show":
            self.srv.show_requests += 1
            caps = ["embedding"] if body.get("model") == EMBED_MODEL else ["completion"]
            self._json(200, {"capabilities": caps})
            return
        if self.path != "/v1/chat/completions":
            self._json(404, {"error": "not found"})
            return
        self.srv.chat_requests.append(body)
        if body.get("model") not in (CHAT_MODEL, "fake-chat"):
            self._json(404, {"error": {"message": f"model '{body.get('model')}' not found"}})
            return
        last_user = next((m["content"] for m in reversed(body["messages"]) if m["role"] == "user"), "")
        if "[[fail]]" in last_user:
            self._json(500, {"error": {"message": "simulated failure"}})
            return
        if "[[slow]]" in last_user:
            words, delay = [f"tick{i} " for i in range(200)], 0.05
        else:
            words, delay = (
                [w + " " for w in f"Echo from the fake model: {last_user}".split()],
                self.srv.delay_s,
            )
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-cache")
        self.end_headers()
        try:
            for word in words:
                chunk = {
                    "id": "chatcmpl-fake",
                    "object": "chat.completion.chunk",
                    "model": body["model"],
                    "choices": [{"index": 0, "delta": {"content": word}, "finish_reason": None}],
                }
                self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
                self.wfile.flush()
                time.sleep(delay)
            final = {
                "id": "chatcmpl-fake",
                "object": "chat.completion.chunk",
                "model": body["model"],
                "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
            }
            self.wfile.write(f"data: {json.dumps(final)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass  # client cancelled


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--port", type=int, default=11500)
    parser.add_argument("--delay-ms", type=float, default=30)
    parser.add_argument("--no-models", action="store_true")
    args = parser.parse_args()
    server = FakeOllama(args.port, delay_s=args.delay_ms / 1000, with_models=not args.no_models)
    print(json.dumps({"event": "ready", "url": server.url}), flush=True)
    server.serve_forever()


if __name__ == "__main__":
    main()
