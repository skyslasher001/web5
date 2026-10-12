import httpx
import pytest

from universe_common.egress import EgressDenied, EgressGate, is_loopback


def test_loopback_detection() -> None:
    for host in ("127.0.0.1", "localhost", "::1", "[::1]", "127.0.0.8"):
        assert is_loopback(host)
    for host in ("example.com", "10.0.0.1", "192.168.1.5", "127.0.0.1.nip.io"):
        assert not is_loopback(host)


def test_local_only_clients_refuse_the_internet() -> None:
    gate = EgressGate()
    with pytest.raises(EgressDenied, match="loopback-only"):
        gate.check(httpx.URL("https://example.com/x"), purpose="chat", local_only=True, actor="system")
    gate.check(httpx.URL("http://127.0.0.1:11434/api/tags"), purpose="chat", local_only=True, actor="system")


def test_offline_and_kill_switch_block_and_everything_else_is_audited() -> None:
    audited: list[dict] = []
    gate = EgressGate(offline=True, audit=audited.append)
    with pytest.raises(EgressDenied, match="offline"):
        gate.check(httpx.URL("https://example.com"), purpose="research", local_only=False, actor="agent:researcher")
    gate.offline = False
    gate.killed = True
    with pytest.raises(EgressDenied, match="kill switch"):
        gate.check(httpx.URL("https://example.com"), purpose="research", local_only=False, actor="agent:researcher")
    gate.killed = False
    gate.check(httpx.URL("https://example.com/a?q=1"), purpose="research", local_only=False, actor="agent:researcher")
    assert audited == [
        {
            "action": "net.request",
            "actor": "agent:researcher",
            "target_type": "host",
            "target_id": "example.com",
            "details": {"purpose": "research", "scheme": "https", "path": "/a"},
        }
    ]


async def test_clients_enforce_the_gate_before_sending() -> None:
    gate = EgressGate(offline=True)
    async with gate.async_client(purpose="research") as client:
        with pytest.raises(EgressDenied):
            await client.get("https://example.com/")
