"""Supervisor entry point. Prints JSON lines on stdout: {"event":"ready",...} then {"event":"status",...}."""

import json
import signal
import sys
import threading
from typing import Any

from universe_supervisor.config import ConfigError, SupervisorConfig
from universe_supervisor.control import ControlServer
from universe_supervisor.jsonlog import JsonLog
from universe_supervisor.supervisor import Supervisor

_stdout_lock = threading.Lock()


def _print(event: str, **fields: Any) -> None:
    with _stdout_lock:
        sys.stdout.write(json.dumps({"event": event, **fields}, default=str) + "\n")
        sys.stdout.flush()


def main() -> int:
    try:
        config = SupervisorConfig.from_env()
    except ConfigError as exc:
        print(f"universe-supervisor: {exc}", file=sys.stderr)
        return 2
    log = JsonLog(config.log_dir / "supervisor.jsonl", echo=False)
    supervisor = Supervisor(config, log=log, emit=lambda status: _print("status", status=status))
    done = threading.Event()

    def shutdown(*_args: object) -> None:
        if not done.is_set():
            done.set()
            supervisor.shutdown()

    for sig in (signal.SIGINT, signal.SIGTERM, getattr(signal, "SIGBREAK", None)):
        if sig is not None:
            signal.signal(sig, shutdown)

    if config.watch_stdin:
        # Electron holds our stdin open; EOF means the parent is gone, so take the services down with us.
        def watch() -> None:
            while sys.stdin.buffer.read(4096):
                pass
            shutdown()

        threading.Thread(target=watch, name="stdin-watch", daemon=True).start()

    control = ControlServer(supervisor, config.control_token, shutdown)
    control.start()
    supervisor.prepare_initial()
    _print("ready", control_port=control.port, core_url=f"http://127.0.0.1:{config.core_port}")
    try:
        supervisor.run()
    finally:
        shutdown()
        control.shutdown()
    return 0


if __name__ == "__main__":
    sys.exit(main())
