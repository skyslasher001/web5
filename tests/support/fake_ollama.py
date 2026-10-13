"""A protocol-faithful stand-in for Ollama, used by tests and the Electron E2E run.

Speaks the parts of Ollama's API that UNIVERSE uses: /api/version, /api/tags, /api/show, /api/embed,
/api/chat (non-streaming, for image captions) and the OpenAI-compatible streaming /v1/chat/completions.
Replies echo the last user message word by word.
Special inputs: "[[fail]]" → HTTP 500, "[[slow]]" → 200 tokens at 50 ms each (for cancel tests).

Embeddings are deterministic "concept" vectors: words are mapped through a small synonym table, so
"automobile" lands near "car" and "dusk" near "sunset". That lets tests check meaning-based retrieval
without a real model (the real-model path is covered by tests/integration/test_real_ollama.py).

Run standalone: python tests/support/fake_ollama.py --port 11500
"""

import argparse
import hashlib
import json
import math
import re
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import cast

CHAT_MODEL = "fake-chat:latest"
EMBED_MODEL = "fake-embed:latest"
VISION_MODEL = "fake-vision:latest"
EMBED_DIM = 1024  # like real embedders (768–4096); a small space makes unrelated words collide
CAPTION = "A wooden dock on a calm lake at sunset"

CONCEPTS = {
    "car": "vehicle", "automobile": "vehicle", "truck": "vehicle", "vehicle": "vehicle", "sedan": "vehicle",
    "sunset": "dusk", "dusk": "dusk", "twilight": "dusk", "evening": "dusk",
    "lake": "water", "pond": "water", "ocean": "water", "sea": "water", "river": "water",
    "invoice": "bill", "bill": "bill", "receipt": "bill", "payment": "bill",
    "dog": "pet", "puppy": "pet", "cat": "pet", "kitten": "pet", "pet": "pet",
    "song": "music", "melody": "music", "tune": "music", "music": "music", "chorus": "music",
    "contract": "agreement", "agreement": "agreement", "deal": "agreement",
    "budget": "finance", "price": "finance", "pricing": "finance", "cost": "finance", "money": "finance",
    "doctor": "health", "clinic": "health", "medicine": "health", "health": "health",
}  # fmt: skip


def fake_embedding(text: str) -> list[float]:
    vector = [0.0] * EMBED_DIM
    for raw in re.findall(r"[a-z0-9]+", text.lower()):
        word = raw[:-1] if raw.endswith("s") and len(raw) > 3 else raw
        concept = CONCEPTS.get(word) or word
        vector[int(hashlib.sha256(concept.encode()).hexdigest(), 16) % EMBED_DIM] += 1.0
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


class FakeOllama(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, port: int = 0, *, delay_s: float = 0.01, with_models: bool = True) -> None:
        super().__init__(("127.0.0.1", port), _Handler)
        self.delay_s = delay_s
        self.with_models = with_models
        self.chat_requests: list[dict] = []
        self.show_requests = 0
        self.embed_requests = 0
        self.caption_requests = 0
        self.with_vision = False
        self.embed_status = 200  # set to 500 to make /api/embed fail
        self.capabilities_in_tags = False  # Ollama >= 0.12 lists capabilities in /api/tags
        self.tags_status = 200  # set to 500 to make /api/tags fail while /api/version still answers
        self.chat_tools = True  # the chat model can call tools (False: a model whose card doesn't list 'tools')

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
                if self.srv.with_vision:
                    models.append(
                        {"name": VISION_MODEL, "size": 2_000_000, "digest": "ccc", "details": {"family": "fake"}}
                    )
                if self.srv.capabilities_in_tags:
                    models[0]["capabilities"] = ["completion", "tools"] if self.srv.chat_tools else ["completion"]
                    models[1]["capabilities"] = ["embedding"]
                    if self.srv.with_vision:
                        models[2]["capabilities"] = ["completion", "vision"]
            self._json(200, {"models": models})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self) -> None:
        body = self._body()
        if self.path == "/api/show":
            self.srv.show_requests += 1
            known = {EMBED_MODEL: ["embedding"], VISION_MODEL: ["completion", "vision"]}
            chat_caps = ["completion", "tools"] if self.srv.chat_tools else ["completion"]
            caps = known.get(str(body.get("model")), chat_caps)
            self._json(200, {"capabilities": caps})
            return
        if self.path == "/api/embed":
            self.srv.embed_requests += 1
            if self.srv.embed_status != 200:
                self._json(self.srv.embed_status, {"error": "simulated embed failure"})
                return
            if body.get("model") not in (EMBED_MODEL, "fake-embed"):
                self._json(404, {"error": f"model '{body.get('model')}' not found"})
                return
            inputs = body.get("input")
            texts = [inputs] if isinstance(inputs, str) else list(inputs or [])
            self._json(200, {"model": body["model"], "embeddings": [fake_embedding(t) for t in texts]})
            return
        if self.path == "/api/chat":
            self.srv.caption_requests += 1
            if body.get("model") != VISION_MODEL or not self.srv.with_vision:
                self._json(404, {"error": f"model '{body.get('model')}' not found"})
                return
            self._json(
                200, {"model": body["model"], "message": {"role": "assistant", "content": CAPTION}, "done": True}
            )
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
        system = str(body["messages"][0].get("content", "")) if body["messages"] else ""
        if body.get("tools") or system.startswith("You are Critic"):
            self._stream_turn(body["model"], *scripted_turn(body))
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

    def _stream_turn(self, model: str, text: str, calls: list[tuple[str, dict]]) -> None:
        """Stream a turn the way Ollama's OpenAI endpoint does: text deltas, tool-call fragments, usage."""
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.end_headers()

        def send(delta: dict, finish: str | None = None) -> None:
            chunk = {
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [{"index": 0, "delta": delta, "finish_reason": finish}],
            }
            self.wfile.write(f"data: {json.dumps(chunk)}\n\n".encode())
            self.wfile.flush()
            time.sleep(self.srv.delay_s)

        try:
            for word in text.split(" ") if text else []:
                send({"content": word + " "})
            for index, (name, arguments) in enumerate(calls):
                raw = arguments["__raw__"] if "__raw__" in arguments else json.dumps(arguments)
                head = {
                    "index": index,
                    "id": f"call_{uuid.uuid4().hex[:12]}",
                    "type": "function",
                    "function": {"name": name, "arguments": raw[: len(raw) // 2]},
                }
                send({"tool_calls": [head]})
                send({"tool_calls": [{"index": index, "function": {"arguments": raw[len(raw) // 2 :]}}]})
            send({}, "tool_calls" if calls else "stop")
            usage = {
                "object": "chat.completion.chunk",
                "model": model,
                "choices": [],
                "usage": {"prompt_tokens": 50, "completion_tokens": 10 + len(text) // 4},
            }
            self.wfile.write(f"data: {json.dumps(usage)}\n\ndata: [DONE]\n\n".encode())
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError):
            pass


# ---------- a scripted stand-in for a tool-calling model ----------
# It follows the agents' prompts the way a capable model would, deterministically, so the engine can be
# tested end to end: Core delegates to the librarian, the librarian searches and reads, Core links the items.

_UNTRUSTED = re.compile(r"<untrusted[^>]*>\n(.*?)\n</untrusted>", re.S)
_IDS = re.compile(r"id: ([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})")
_LINK = re.compile(
    r"notes? about (.+?),? summari[sz]e them,? and link them to (?:the )?(?:project|galaxy) (.+?)[.!?]*$", re.I
)
_FIND = re.compile(r"notes? about (.+?)(?:,? and summari[sz]e them)?[.!?]*$", re.I)


def _payload(text: str) -> str:
    found = _UNTRUSTED.search(text)
    return found.group(1) if found else text


def _history(messages: list[dict]) -> list[tuple[str, dict, str]]:
    """(tool name, arguments, result) for every tool call so far in this task."""
    results = {m.get("tool_call_id"): str(m.get("content", "")) for m in messages if m.get("role") == "tool"}
    calls = []
    for m in messages:
        for call in m.get("tool_calls") or []:
            fn = call.get("function", {})
            try:
                args = json.loads(fn.get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {}
            calls.append((fn.get("name", ""), args, results.get(call.get("id"), "")))
    return calls


def scripted_turn(body: dict) -> tuple[str, list[tuple[str, dict]]]:
    messages = body["messages"]
    tools = {t["function"]["name"] for t in body.get("tools") or []}
    system = str(messages[0].get("content", ""))
    user = next((str(m["content"]) for m in reversed(messages) if m["role"] == "user"), "")
    done = _history(messages)
    names = [name for name, _a, _r in done]
    if system.startswith("You are Critic"):
        return "OK", []
    if "[[loop]]" in user:
        return "", [("vault__search", {"query": "same thing"})]
    if "[[unknown-tool]]" in user and not done:
        return "", [("files__delete_everything", {})]
    if "[[bad-args]]" in user and not done:
        return "", [("vault__search", {"__raw__": "{not json"})]
    if "[[remember]]" in user and "memory__save" in tools and "memory__save" not in names:
        return "", [("memory__save", {"content": user.replace("[[remember]]", "").strip(), "about": "user"})]
    if (m := _LINK.search(user)) and "agent__delegate" in tools:
        topic, project = m.group(1).strip(), m.group(2).strip()
        delegated = next((r for n, _a, r in done if n == "agent__delegate"), None)
        if delegated is None:
            return "I'll have the librarian find and summarize them.", [
                (
                    "agent__delegate",
                    {"agent": "librarian", "instruction": f"Find my notes about {topic} and summarize them."},
                )
            ]
        linked = next((r for n, _a, r in done if n == "project__add_items"), None)
        if linked is None:
            ids = list(dict.fromkeys(_IDS.findall(_payload(delegated))))
            if ids:
                return "", [("project__add_items", {"project": project, "item_ids": ids})]
        summary = _payload(delegated).split("\n\nItems used:")[0].strip()
        return f"{summary}\n\n{linked or 'Nothing was linked.'}", []
    if "vault__read" in tools and (m := _FIND.search(user)):
        topic = m.group(1).strip()
        search = next((r for n, _a, r in done if n == "vault__search"), None)
        if search is None:
            return "", [("vault__search", {"query": topic, "types": ["note"]})]
        try:
            hits = json.loads(_payload(search))
        except json.JSONDecodeError:
            hits = []
        read = {a.get("item_id") for n, a, _r in done if n == "vault__read"}
        pending = [h for h in hits if h["id"] not in read]
        if pending:
            return "", [("vault__read", {"item_id": pending[0]["id"]})]
        if not hits:
            return f"I found no notes about {topic}.", []
        texts = [_payload(r) for n, _a, r in done if n == "vault__read"]
        firsts = []
        for text in texts:
            body_text = text.split("\n\n", 1)[-1].strip()
            firsts.append(body_text.split(". ")[0].rstrip(".") + ".")
        used = "\n".join(f"- {h['title']} (id: {h['id']})" for h in hits)
        return f"Summary: {' '.join(firsts)}\n\nItems used:\n{used}", []
    return f"Echo from the fake model: {user}", []


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
