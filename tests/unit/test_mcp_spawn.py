"""How Core starts an MCP server program: the command lookup and the Windows process flags (review 2026-10-22).

On Windows `npx` is `npx.cmd`, which CreateProcess only finds by its full name, and a console child would flash a
window. These tests check the lookup and flags on any OS; the Windows-only lookup is simulated with `which`.
"""

import os
import stat
import sys
from pathlib import Path

import pytest

from universe_core import mcp_client
from universe_core.mcp_client import resolve_command, spawn_options


def test_a_bare_command_is_found_on_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Windows finds a bare name only through PATHEXT (`my-mcp-server` → `my-mcp-server.cmd`), as with `npx`.
    program = tmp_path / ("my-mcp-server.cmd" if sys.platform == "win32" else "my-mcp-server")
    program.write_text("#!/bin/sh\n", encoding="utf-8")
    program.chmod(program.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", str(tmp_path) + os.pathsep + os.environ.get("PATH", ""))
    assert os.path.normcase(resolve_command("my-mcp-server")) == os.path.normcase(str(program))


def test_windows_finds_npx_cmd(monkeypatch: pytest.MonkeyPatch) -> None:
    found = r"C:\Program Files\nodejs\npx.cmd"
    monkeypatch.setattr(mcp_client.shutil, "which", lambda cmd, path=None: found if cmd == "npx" else None)
    assert resolve_command("npx") == found


def test_paths_and_unknown_commands_are_left_alone(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(mcp_client.shutil, "which", lambda cmd, path=None: None)
    assert resolve_command("no-such-program") == "no-such-program"  # the start fails with a clear error
    assert resolve_command("/opt/tools/server") == "/opt/tools/server"


def test_no_console_window_on_windows() -> None:
    assert spawn_options("win32") == {"creationflags": 0x08000000}  # CREATE_NO_WINDOW
    assert spawn_options("linux") == {}
    assert spawn_options("darwin") == {}
