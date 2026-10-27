"""A stand-in for Core used by supervisor tests. Behaviour is read from a control file at start:

  ok         serve /api/v1/health, and acknowledge POST /api/v1/killswitch/sync
  crash      exit(3) immediately
  unhealthy  run, but answer health checks with 500
  hung       healthy, but never answer POST requests (a Core stuck in a busy loop)
Each start appends its environment snapshot (selected keys) as a JSON line to FAKE_CORE_ENV_OUT, and each
kill-switch sync appends {"killswitch_sync": <authorized>, "state": <the state file>}.
"""

import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

KEYS = [
    "UNIVERSE_SAFE_MODE",
    "PYTHONPATH",
    "UNIVERSE_AGENTS_DIR",
    "UNIVERSE_START_REASON",
    "UNIVERSE_RESTART_COUNT",
    "UNIVERSE_LAST_EXIT",
    "UNIVERSE_SESSION_TOKEN",
    "UNIVERSE_SUPERVISOR_TOKEN",
]


def main() -> int:
    mode = Path(os.environ["FAKE_CORE_CONTROL"]).read_text().strip()
    with open(os.environ["FAKE_CORE_ENV_OUT"], "a", encoding="utf-8") as fh:
        fh.write(json.dumps({k: os.environ.get(k) for k in KEYS} | {"mode": mode, "pid": os.getpid()}) + "\n")
    if mode == "crash":
        print("fake core: simulated startup crash", flush=True)
        return 3

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, format: str, *args: object) -> None:
            return

        def do_GET(self) -> None:
            status = 500 if mode == "unhealthy" else 200
            body = json.dumps({"status": "ok"}).encode()
            self.send_response(status)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_POST(self) -> None:
            if mode == "hung":
                time.sleep(30)
                return
            authorized = self.headers.get("Authorization") == f"Bearer {os.environ.get('UNIVERSE_SESSION_TOKEN')}"
            state_file = Path(os.environ.get("UNIVERSE_DATA_DIR", ".")) / "killswitch.json"
            state = json.loads(state_file.read_text()) if state_file.exists() else None
            with open(os.environ["FAKE_CORE_ENV_OUT"], "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"killswitch_sync": authorized, "state": state}) + "\n")
            body = json.dumps({"available": True, "engaged": bool(state and state.get("engaged"))}).encode()
            self.send_response(200 if authorized else 401)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

    ThreadingHTTPServer(("127.0.0.1", int(os.environ["UNIVERSE_CORE_PORT"])), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    sys.exit(main())
