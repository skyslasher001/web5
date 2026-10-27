"""Which processes Core watches to know it's orphaned (CI's first Windows run, 2026-10-27).

On Windows the venv's python.exe is a launcher that runs the real interpreter as a child, so the chain is
supervisor → launcher → Core: when the supervisor dies the launcher lives on, and Core must watch past it.
"""

from dataclasses import dataclass

from universe_common.orphan import watched_processes


@dataclass
class FakeProcess:
    pid: int
    exe_name: str
    args: list[str]
    parent_process: "FakeProcess | None" = None

    def name(self) -> str:
        return self.exe_name

    def cmdline(self) -> list[str]:
        return self.args

    def parent(self) -> "FakeProcess | None":
        return self.parent_process


def test_on_windows_core_also_watches_whoever_started_its_launcher() -> None:
    supervisor = FakeProcess(1, "python.exe", [r"C:\venv\Scripts\python.exe", "-I", "-S", "run_supervisor.py"])
    launcher = FakeProcess(2, "python.exe", [r"C:\venv\Scripts\python.exe", "-m", "universe_core"], supervisor)
    core = FakeProcess(3, "python.exe", [r"C:\Python312\python.exe", "-m", "universe_core"], launcher)
    assert [p.pid for p in watched_processes(launcher, core, windows=True)] == [2, 1]


def test_a_parent_that_isnt_our_launcher_is_the_only_one_watched() -> None:
    supervisor = FakeProcess(1, "python.exe", ["python.exe", "-I", "-S", "run_supervisor.py"])
    core = FakeProcess(3, "python.exe", ["python.exe", "-m", "universe_core"], supervisor)
    assert [p.pid for p in watched_processes(supervisor, core, windows=True)] == [1]
    electron = FakeProcess(4, "UNIVERSE.exe", ["UNIVERSE.exe"])
    assert [p.pid for p in watched_processes(electron, core, windows=True)] == [4]


def test_posix_has_no_launcher_to_look_past() -> None:
    supervisor = FakeProcess(1, "python", ["python", "-m", "universe_core"])
    core = FakeProcess(3, "python", ["python", "-m", "universe_core"], supervisor)
    assert [p.pid for p in watched_processes(supervisor, core, windows=False)] == [1]
