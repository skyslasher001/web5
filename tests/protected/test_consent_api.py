"""The consent mirror (Phase 7 protected core): off until main reports otherwise, and every change audited."""

from fastapi.testclient import TestClient

from tests.conftest import AUTH


def test_consent_is_off_until_main_reports_it(client: TestClient) -> None:
    response = client.get("/api/v1/consent", headers=AUTH)
    assert response.status_code == 200
    assert response.json() == {"mic": False, "via": None, "changed_at": None}


def test_every_change_is_audited_and_published(client: TestClient) -> None:
    on = client.post("/api/v1/consent", json={"on": True, "via": "hud"}, headers=AUTH)
    assert on.status_code == 200 and on.json()["mic"] is True
    off = client.post("/api/v1/consent", json={"on": False, "via": "killswitch"}, headers=AUTH)
    assert off.json()["mic"] is False
    assert client.get("/api/v1/consent", headers=AUTH).json()["via"] == "killswitch"
    audit = client.get("/api/v1/audit", params={"action": "consent.changed"}, headers=AUTH).json()
    assert [(a["details"]["on"], a["details"]["via"]) for a in audit][:2] == [(False, "killswitch"), (True, "hud")]
    events = client.get("/api/v1/events", params={"type": "consent.changed"}, headers=AUTH).json()["events"]
    assert [e["payload"]["on"] for e in events] == [True, False]


def test_reports_need_the_session_token_and_a_known_source(client: TestClient) -> None:
    assert client.post("/api/v1/consent", json={"on": True, "via": "hud"}).status_code == 401
    bad = client.post("/api/v1/consent", json={"on": True, "via": "a webpage"}, headers=AUTH)
    assert bad.status_code == 422
