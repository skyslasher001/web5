"""Control API on its own loopback port, token held only by Electron main (ADR-0006)."""

import hmac
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any, cast
from urllib.parse import parse_qs, urlparse

from universe_supervisor.supervisor import Supervisor


class ControlServer(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self, supervisor: Supervisor, token: str, on_shutdown: Any) -> None:
        super().__init__(("127.0.0.1", 0), _Handler)
        self.supervisor = supervisor
        self.expected = f"Bearer {token}".encode()
        self.on_shutdown = on_shutdown

    @property
    def port(self) -> int:
        return int(self.server_address[1])

    def start(self) -> None:
        threading.Thread(target=self.serve_forever, name="control-api", daemon=True).start()


class _Handler(BaseHTTPRequestHandler):
    @property
    def srv(self) -> ControlServer:
        return cast(ControlServer, self.server)

    def log_message(self, format: str, *args: object) -> None:
        return

    def _send(self, status: int, body: Any) -> None:
        data = json.dumps(body, default=str).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        host = self.headers.get("Host", "")
        if host != f"127.0.0.1:{self.srv.port}":
            self._send(403, {"error": "bad host"})
            return False
        supplied = self.headers.get("Authorization", "").encode()
        if not hmac.compare_digest(supplied, self.srv.expected):
            self._send(401, {"error": "unauthorized"})
            return False
        return True

    def do_GET(self) -> None:
        if not self._authorized():
            return
        url = urlparse(self.path)
        sup = self.srv.supervisor
        if url.path == "/status":
            self._send(200, sup.status())
        elif url.path.startswith("/logs/"):
            lines = int(parse_qs(url.query).get("tail", ["200"])[0])
            text = sup.logs(url.path.removeprefix("/logs/"), max(1, min(lines, 2000)))
            self._send(404, {"error": "unknown service"}) if text is None else self._send(200, {"text": text})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self) -> None:
        if not self._authorized():
            return
        sup = self.srv.supervisor
        parts = urlparse(self.path).path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "services" and parts[2] in ("restart", "kill"):
            ok = sup.restart(parts[1]) if parts[2] == "restart" else sup.kill(parts[1])
            self._send(200 if ok else 409, {"ok": ok})
        elif parts == ["safe-mode", "exit"]:
            self._send(200, {"ok": sup.exit_safe_mode()})
        elif parts == ["shutdown"]:
            self._send(200, {"ok": True})
            threading.Thread(target=self.srv.on_shutdown, daemon=True).start()
        else:
            self._send(404, {"error": "not found"})
