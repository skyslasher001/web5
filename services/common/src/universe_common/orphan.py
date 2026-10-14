"""Exit when our parent process is gone, so Core never outlives its supervisor (and workers never outlive Core).

Two real cases: on POSIX the supervisor can be SIGKILLed (children in their own session survive), and on
Windows the venv's python.exe is a launcher that runs the real interpreter as a *child*, so killing the
launcher would leave Core running and holding its port. Either way the next Core could not bind.
"""

import os
import threading
from collections.abc import Callable

import psutil

from universe_common.log import get_logger

log = get_logger(__name__)


def watch_parent(on_orphaned: Callable[[], None], *, interval_s: float = 0.25) -> threading.Thread | None:
    """Poll the parent (pid + create time, so PID reuse can't fool it) and call `on_orphaned` once."""
    try:
        parent = psutil.Process(os.getppid())
        parent.create_time()
    except psutil.Error:
        return None

    def run() -> None:
        stop = threading.Event()
        while not stop.wait(interval_s):
            if not parent.is_running():
                log.warning("parent_process_gone", parent_pid=parent.pid)
                on_orphaned()
                return

    thread = threading.Thread(target=run, name="orphan-watch", daemon=True)
    thread.start()
    return thread
