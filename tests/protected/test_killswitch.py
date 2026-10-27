"""The kill switch works even when Core is hung (ARCHITECTURE.md §1.4). PROTECTED: Forge may not change these."""

import json
import time
from pathlib import Path

from tests.integration.test_supervisor import CONTROL_TOKEN, Harness, _call, core, harness  # noqa: F401
from universe_core.protected.killswitch import KillSwitch, KillSwitchState, read_state, write_state
from universe_supervisor.control import ControlServer


def test_state_file_is_fail_safe(tmp_path: Path) -> None:
    path = tmp_path / "killswitch.json"
    assert not read_state(path).engaged  # no file: off
    path.write_text("{garbage")
    assert read_state(path).engaged  # unreadable: engaged
    write_state(path, KillSwitchState(engaged=False))
    assert not read_state(path).engaged


def test_core_comes_back_engaged_after_a_restart(tmp_path: Path) -> None:
    write_state(tmp_path / "killswitch.json", KillSwitchState(engaged=True, via="supervisor"))
    changes: list[bool] = []
    switch = KillSwitch(tmp_path, audit=lambda **_e: None, publish=lambda *_a: None, on_change=changes.append)
    assert switch.engaged and changes == [True]  # applied at startup: tasks stop, the egress gate closes


def _post(port: int, path: str, body: dict) -> tuple[int, dict]:
    import urllib.request

    request = urllib.request.Request(
        f"http://127.0.0.1:{port}{path}",
        data=json.dumps(body).encode(),
        method="POST",
        headers={"Authorization": f"Bearer {CONTROL_TOKEN}", "Content-Type": "application/json"},
    )
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(request, timeout=10) as response:
        return response.status, json.loads(response.read())


def test_supervisor_engages_and_core_acknowledges(harness: Harness) -> None:  # noqa: F811
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    server = ControlServer(harness.sup, CONTROL_TOKEN, on_shutdown=lambda: None)
    server.start()
    try:
        assert _call(server.port, "POST", "/killswitch")[0] == 400  # needs {"engaged": bool}
        status, result = _post(server.port, "/killswitch", {"engaged": True})
        assert status == 200 and result == {"ok": True, "engaged": True, "core_acked": True, "core_restarted": False}
        state = json.loads((harness.config.data_dir / "killswitch.json").read_text())
        assert state["engaged"] and state["via"] == "supervisor"
        syncs = [s for s in harness.starts() if "killswitch_sync" in s]
        assert syncs == [{"killswitch_sync": True, "state": state}]  # with the session token
        _status, released = _post(server.port, "/killswitch", {"engaged": False})
        assert released["engaged"] is False and released["core_acked"]
    finally:
        server.shutdown()


def test_a_hung_core_is_restarted_with_the_switch_engaged(harness: Harness) -> None:  # noqa: F811
    harness.set_mode("hung")
    harness.run_until(lambda s: core(s)["state"] == "healthy")
    first = [s for s in harness.starts() if "mode" in s]
    started = time.monotonic()
    result = harness.sup.killswitch(True)
    assert time.monotonic() - started < 3  # gave Core one second, not forever
    assert result["core_acked"] is False and result["core_restarted"] is True
    harness.set_mode("ok")
    harness.run_until(
        lambda s: core(s)["state"] == "healthy" and len([x for x in harness.starts() if "mode" in x]) > len(first)
    )
    assert json.loads((harness.config.data_dir / "killswitch.json").read_text())["engaged"]
