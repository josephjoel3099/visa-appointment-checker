from pathlib import Path

import pytest
import requests

from checker.portal import USER_AGENT, MaintenanceError, Portal, PortalError, Service

FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


class FakeResponse:
    def __init__(self, status_code, text="", headers=None):
        self.status_code = status_code
        self.text = text
        self.headers = headers or {}


class FakeSession:
    """Scripted session: each get/post pops the next scripted item."""

    def __init__(self, script):
        self.script = script
        self.headers = {}
        self.calls = []

    def _next(self, method, url, **kwargs):
        self.calls.append((method, url, kwargs))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def get(self, url, **kwargs):
        return self._next("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self._next("POST", url, **kwargs)


def make_portal(*scripted):
    """Return (portal, sessions, sleeps). One shared script across sessions."""
    script = list(scripted)
    sessions = []

    def factory():
        s = FakeSession(script)
        sessions.append(s)
        return s

    sleeps = []
    return Portal(session_factory=factory, sleep=sleeps.append), sessions, sleeps


def ok(name):
    return FakeResponse(200, load(name))


def test_list_services_posts_form_fields():
    portal, sessions, _ = make_portal(ok("home.html"), ok("services_several.html"))
    services = portal.list_services("40")
    assert all(isinstance(s, Service) for s in services) and services
    session = sessions[0]
    assert session.headers["User-Agent"] == USER_AGENT
    method, _, kwargs = session.calls[1]
    assert method == "POST"
    assert kwargs["data"] == {
        "broneering[esindus]": "40",
        "broneering[isikuteArv]": "1",
        "broneering[_token]": "TESTTOKEN",
    }
    assert kwargs["timeout"] == 15


def test_422_is_not_an_error():
    portal, _, _ = make_portal(
        ok("home.html"), FakeResponse(422, load("services_none.html"))
    )
    assert portal.list_services("40") == []


def test_each_call_uses_fresh_session():
    portal, sessions, _ = make_portal(
        ok("home.html"),
        ok("services_several.html"),
        ok("home.html"),
        ok("services_several.html"),
    )
    portal.list_services("40")
    portal.list_services("40")
    assert len(sessions) == 2


def test_list_embassies():
    portal, _, _ = make_portal(ok("home.html"))
    assert portal.list_embassies()["40"].endswith("New Delhi")


def test_retries_connection_error_then_succeeds():
    portal, _, sleeps = make_portal(
        requests.ConnectionError("boom"),
        ok("home.html"),
        ok("services_several.html"),
    )
    assert portal.list_services("40")
    assert sleeps == [1.0]


def test_gives_up_after_three_attempts():
    portal, sessions, sleeps = make_portal(
        FakeResponse(503), FakeResponse(503), FakeResponse(503)
    )
    with pytest.raises(PortalError):
        portal.list_embassies()
    assert sleeps == [1.0, 2.0]


def test_maintenance_503_fails_fast_with_end_time():
    portal, sessions, sleeps = make_portal(
        FakeResponse(503, headers={"X-Maintenance-End": "2026-10-21 15:00 UTC"})
    )
    with pytest.raises(MaintenanceError) as excinfo:
        portal.list_embassies()
    assert excinfo.value.until == "2026-10-21T15:00:00Z"
    assert sleeps == []
    assert len(sessions[0].calls) == 1


def test_503_with_unparseable_maintenance_header_is_retried():
    bad = {"X-Maintenance-End": "soon"}
    portal, _, sleeps = make_portal(
        FakeResponse(503, headers=bad),
        FakeResponse(503, headers=bad),
        FakeResponse(503, headers=bad),
    )
    with pytest.raises(PortalError) as excinfo:
        portal.list_embassies()
    assert not isinstance(excinfo.value, MaintenanceError)
    assert sleeps == [1.0, 2.0]


def test_429_is_retried():
    portal, _, sleeps = make_portal(FakeResponse(429), ok("home.html"))
    assert portal.list_embassies()
    assert sleeps == [1.0]


def test_403_not_retried():
    portal, sessions, sleeps = make_portal(FakeResponse(403))
    with pytest.raises(PortalError):
        portal.list_embassies()
    assert sleeps == []
    assert len(sessions[0].calls) == 1


def test_get_422_is_an_error():
    portal, _, sleeps = make_portal(FakeResponse(422))
    with pytest.raises(PortalError):
        portal.list_embassies()
    assert sleeps == []


def test_list_dates_returns_pages_and_dates():
    portal, sessions, _ = make_portal(
        ok("home.html"), ok("services_several.html"), ok("after_service_synthetic.html")
    )
    result = portal.list_dates("40", "501")
    assert result.dates == ["2026-11-03", "2026-11-04"]
    assert set(result.pages) == {"home", "services", "after_service"}
    last_method, _, kwargs = sessions[0].calls[-1]
    assert last_method == "POST"
    assert kwargs["data"]["broneering[toiming]"] == "501"
    assert kwargs["data"]["broneering[esindus]"] == "40"
    assert kwargs["data"]["broneering[_token]"] == "TESTTOKEN"
    assert len(sessions) == 1


def test_list_dates_unparseable_gives_none():
    portal, _, _ = make_portal(
        ok("home.html"), ok("services_several.html"), ok("services_none.html")
    )
    result = portal.list_dates("40", "501")
    assert result.dates is None
