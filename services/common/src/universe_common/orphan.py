"""Exit when our parent process is gone, so Core never outlives its supervisor (and workers never outlive Core).

Two real cases: on POSIX the supervisor can be SIGKILLed (children in their own session survive), and on
Windows the venv's python.exe is a launcher that runs the real interpreter as a *child*, so killing the
launcher would leave Core running and holding its port. Either way the next Core could not bind.

On Windows the launcher also sits *between* us and the process that started us (supervisor → launcher → Core).
When the supervisor dies the launcher lives on, waiting for us, so watching only our direct parent would miss it:
when the parent is our own launcher, its parent is watched too (CI's first Windows run, 2026-10-27).
"""

import os
import sys
import threading
from collections.abc import Callable
from typing import Any

import psutil

from universe_common.log import get_logger

log = get_logger(__name__)


def _is_our_launcher(parent: Any, me: Any) -> bool:
    """The venv launcher runs the real interpreter with its own arguments: same name, same arguments after argv[0]."""
    try:
        return parent.name().lower() == me.name().lower() and parent.cmdline()[1:] == me.cmdline()[1:]
    except psutil.Error:
        return False


def watched_processes(parent: Any, me: Any, *, windows: bool = sys.platform == "win32") -> list[Any]:
    """The processes whose exit means we're orphaned: our parent, plus the launcher's parent on Windows."""
    watched = [parent]
    if windows and _is_our_launcher(parent, me):
        try:
            grandparent = parent.parent()
        except psutil.Error:
            grandparent = None
        if grandparent is not None:
            watched.append(grandparent)
    return watched


def watch_parent(on_orphaned: Callable[[], None], *, interval_s: float = 0.25) -> threading.Thread | None:
    """Poll the parent (pid + create time, so PID reuse can't fool it) and call `on_orphaned` once."""
    try:
        parent = psutil.Process(os.getppid())
        parent.create_time()
        watched = watched_processes(parent, psutil.Process())
    except psutil.Error:
        return None

    def run() -> None:
        stop = threading.Event()
        while not stop.wait(interval_s):
            gone = next((p for p in watched if not p.is_running()), None)
            if gone is not None:
                log.warning("parent_process_gone", parent_pid=gone.pid)
                on_orphaned()
                return

    thread = threading.Thread(target=run, name="orphan-watch", daemon=True)
    thread.start()
    return thread
