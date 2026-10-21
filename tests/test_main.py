import json
import logging

import pytest

from checker.__main__ import MAX_WORKERS, main, run, scrape_all
from checker.portal import DatesResult, MaintenanceError, PortalError, Service

SERVICE = "Long-stay visa (D-visa) application"
T1 = "2026-10-17T10:00:00Z"
T2 = "2026-10-17T11:00:00Z"


class FakePortal:
    def __init__(self, embassies, services, dates=None, page_text="x"):
        self.embassies = embassies  # id -> name, or an Exception
        self.services = services  # id -> list[Service] | Exception
        self.dates = dates or {}  # (eid, sid) -> list | None | Exception
        self.page_text = page_text

    def list_embassies(self):
        if isinstance(self.embassies, Exception):
            raise self.embassies
        return dict(self.embassies)

    def list_services(self, embassy_id):
        result = self.services[embassy_id]
        if isinstance(result, Exception):
            raise result
        return result

    def list_dates(self, embassy_id, service_id):
        result = self.dates.get((embassy_id, service_id), ["2026-11-02"])
        if isinstance(result, Exception):
            raise result
        return DatesResult(
            dates=result,
            pages={
                "home": f"home {self.page_text}",
                "services": f"services {self.page_text}",
                "after_service": f"after {self.page_text}",
            },
        )


class _Records(logging.Handler):
    def __init__(self):
        super().__init__(logging.DEBUG)
        self.lines = []

    def emit(self, record):
        self.lines.append(record.getMessage())

    @property
    def text(self):
        return "\n".join(self.lines)


@pytest.fixture
def caplog():
    """Attach straight to the checker logger so this works regardless of any
    pytest plugin (e.g. ROS ones) that reconfigures the root logger."""
    logger = logging.getLogger("checker")
    handler = _Records()
    old_level = logger.level
    logger.addHandler(handler)
    logger.setLevel(logging.DEBUG)
    logger.propagate = False  # keep test output pristine
    try:
        yield handler
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old_level)
        logger.propagate = True


def svc():
    return [Service(id="9", name=SERVICE)]


def two_embassy_portal(**kw):
    return FakePortal(
        {"40": "New Delhi", "41": "Berlin"},
        {"40": svc(), "41": []},
        **kw,
    )


def paths(tmp_path):
    return tmp_path / "data", tmp_path / "public" / "status.json"


def load(p):
    return json.loads(p.read_text())


def test_max_workers_is_four():
    assert MAX_WORKERS == 4


def test_first_run_writes_out_and_data(tmp_path):
    data_dir, out = paths(tmp_path)
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    assert out.exists()
    assert (data_dir / "status.json").exists()
    status = load(out)
    assert status["embassies"]["40"]["services"][SERVICE]["available"] is True
    assert status["embassies"]["41"]["services"] == {}


def test_unchanged_run_does_not_touch_data_file(tmp_path):
    data_dir, out = paths(tmp_path)
    # embassy 40 has an AVAILABLE service: last_seen_available moves each run
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    data_file = data_dir / "status.json"
    before = data_file.read_bytes()
    assert run(two_embassy_portal(), data_dir, out, T2) == 0
    assert data_file.read_bytes() == before
    status = load(out)
    assert status["last_checked"] == T2
    assert status["embassies"]["40"]["services"][SERVICE]["last_seen_available"] == T2


def test_embassy_failure_is_isolated(tmp_path):
    data_dir, out = paths(tmp_path)
    portal = FakePortal(
        {"40": "New Delhi", "41": "Berlin", "42": "Paris"},
        {"40": svc(), "41": PortalError("boom"), "42": svc()},
    )
    assert run(portal, data_dir, out, T1) == 0
    status = load(out)
    assert status["embassies"]["41"]["ok"] is False
    assert status["embassies"]["40"]["ok"] is True
    assert status["embassies"]["42"]["services"][SERVICE]["available"] is True


def test_missing_services_select_is_embassy_failure(tmp_path):
    data_dir, out = paths(tmp_path)
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    portal = FakePortal(
        {"40": "New Delhi", "41": "Berlin", "42": "Paris"},
        {
            "40": PortalError("services select not found"),
            "41": [],
            "42": [],
        },
    )
    assert run(portal, data_dir, out, T2) == 0
    emb = load(out)["embassies"]["40"]
    assert emb["ok"] is False
    assert emb["services"][SERVICE]["available"] is True


def test_majority_failure_returns_1_and_keeps_data(tmp_path):
    data_dir, out = paths(tmp_path)
    ids = {"40": "A", "41": "B", "42": "C", "43": "D"}
    good = FakePortal(ids, {k: svc() for k in ids})
    assert run(good, data_dir, out, T1) == 0
    data_file = data_dir / "status.json"
    before = data_file.read_bytes()

    bad = FakePortal(
        ids,
        {
            "40": svc(),
            "41": PortalError("x"),
            "42": PortalError("x"),
            "43": PortalError("x"),
        },
    )
    assert run(bad, data_dir, out, T2) == 1
    assert data_file.read_bytes() == before
    status = load(out)
    assert status["last_checked"] == T2
    assert status["last_success"] == T1
    for eid in ids:
        assert status["embassies"][eid]["services"][SERVICE]["available"] is True
        assert status["embassies"][eid]["ok"] is True


def test_list_embassies_failure_no_previous(tmp_path):
    data_dir, out = paths(tmp_path)
    portal = FakePortal(PortalError("no select"), {})
    assert run(portal, data_dir, out, T1) == 1
    assert load(out)["last_checked"] == T1
    assert not (data_dir / "status.json").exists()


def test_list_embassies_failure_with_previous(tmp_path):
    data_dir, out = paths(tmp_path)
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    data_file = data_dir / "status.json"
    before = data_file.read_bytes()
    assert run(FakePortal(PortalError("no select"), {}), data_dir, out, T2) == 1
    assert data_file.read_bytes() == before
    status = load(out)
    assert status["last_checked"] == T2
    assert status["embassies"]["40"]["services"][SERVICE]["available"] is True


def test_planned_maintenance_is_not_a_failed_run(tmp_path):
    data_dir, out = paths(tmp_path)
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    data_file = data_dir / "status.json"
    before = data_file.read_bytes()
    down = FakePortal(MaintenanceError("2026-10-17T15:00:00Z"), {})
    assert run(down, data_dir, out, T2) == 0
    assert data_file.read_bytes() == before
    status = load(out)
    assert status["last_checked"] == T2
    assert status["last_success"] == T1
    assert status["maintenance_until"] == "2026-10-17T15:00:00Z"
    assert status["embassies"]["40"]["services"][SERVICE]["available"] is True


def test_overrunning_maintenance_is_still_recorded_but_stays_a_failed_run(tmp_path, caplog):
    data_dir, out = paths(tmp_path)
    down = FakePortal(MaintenanceError("2026-10-17T10:30:00Z"), {})
    assert run(down, data_dir, out, T2) == 1
    assert load(out)["maintenance_until"] == "2026-10-17T10:30:00Z"
    assert "ended" in caplog.text


def test_recovery_clears_maintenance_until(tmp_path):
    data_dir, out = paths(tmp_path)
    down = FakePortal(MaintenanceError("2026-10-17T15:00:00Z"), {})
    assert run(down, data_dir, out, T1) == 0
    assert run(two_embassy_portal(), data_dir, out, T2) == 0
    assert "maintenance_until" not in load(out)


def test_majority_failure_no_previous_creates_no_data_file(tmp_path):
    data_dir, out = paths(tmp_path)
    ids = {"40": "A", "41": "B", "42": "C"}
    portal = FakePortal(
        ids, {"40": svc(), "41": PortalError("x"), "42": PortalError("x")}
    )
    assert run(portal, data_dir, out, T1) == 1
    assert out.exists()
    assert not (data_dir / "status.json").exists()


def test_failures_are_logged_with_context(tmp_path, caplog):
    data_dir, out = paths(tmp_path)
    portal = FakePortal(
        {"40": "A", "41": "B", "42": "C", "43": "D"},
        {
            "40": svc(),
            "41": PortalError("HTTP 503"),
            "42": RuntimeError("kaboom"),
            "43": svc(),
        },
    )
    run(portal, data_dir, out, T1)
    text = caplog.text
    assert "embassy 41" in text and "PortalError: HTTP 503" in text
    assert "embassy 42" in text and "RuntimeError: kaboom" in text
    emb = load(out)["embassies"]
    assert emb["42"]["ok"] is False


def test_list_embassies_failure_is_logged(tmp_path, caplog):
    scrape_all(FakePortal(PortalError("no select"), {}))
    assert "PortalError: no select" in caplog.text


def test_dates_failure_is_logged(tmp_path, caplog):
    portal = two_embassy_portal(dates={("40", "9"): RuntimeError("cal down")})
    scrape_all(portal, with_dates=True)
    assert "embassy 40" in caplog.text and "RuntimeError: cal down" in caplog.text


@pytest.mark.parametrize("content", ["{not json", "", "[]"])
def test_corrupt_previous_treated_as_none(tmp_path, content):
    data_dir, out = paths(tmp_path)
    data_dir.mkdir()
    (data_dir / "status.json").write_text(content)
    assert run(two_embassy_portal(), data_dir, out, T1) == 0
    assert load(out)["embassies"]["40"]["services"][SERVICE]["available"] is True
    assert isinstance(load(data_dir / "status.json"), dict)


def test_dates_failure_still_available(tmp_path):
    data_dir, out = paths(tmp_path)
    portal = two_embassy_portal(dates={("40", "9"): PortalError("bad")})
    assert run(portal, data_dir, out, T1, with_dates=True) == 0
    entry = load(out)["embassies"]["40"]["services"][SERVICE]
    assert entry["available"] is True
    assert entry["dates"] is None


def test_scrape_all_shape_and_samples():
    scrape, samples = scrape_all(two_embassy_portal(), with_dates=True)
    assert scrape["embassies"]["40"]["name"] == "New Delhi"
    assert scrape["embassies"]["40"]["ok"] is True
    assert scrape["embassies"]["40"]["services"][SERVICE] == {"dates": ["2026-11-02"]}
    assert set(samples[("40", SERVICE)]) == {"home", "services", "after_service"}


def test_scrape_all_list_embassies_failure():
    assert scrape_all(FakePortal(PortalError("x"), {})) == ({"embassies": {}}, {})


def test_scrape_all_maintenance():
    portal = FakePortal(MaintenanceError("2026-10-17T15:00:00Z"), {})
    assert scrape_all(portal) == (
        {"embassies": {}, "maintenance_until": "2026-10-17T15:00:00Z"},
        {},
    )


def test_samples_saved_once(tmp_path):
    data_dir, out = paths(tmp_path)
    sample_dir = data_dir / "samples" / "40__long-stay-visa-d-visa-application"
    assert run(two_embassy_portal(page_text="first"), data_dir, out, T1, with_dates=True) == 0
    for step in ("home", "services", "after_service"):
        assert (sample_dir / f"{step}.html").exists()
    original = (sample_dir / "home.html").read_text()
    assert "first" in original
    assert run(two_embassy_portal(page_text="second"), data_dir, out, T2, with_dates=True) == 0
    assert (sample_dir / "home.html").read_text() == original


def test_dates_step_off_by_default(tmp_path):
    class RecordingPortal(FakePortal):
        def __init__(self, *a, **kw):
            super().__init__(*a, **kw)
            self.date_calls = []

        def list_dates(self, embassy_id, service_id):
            self.date_calls.append((embassy_id, service_id))
            return super().list_dates(embassy_id, service_id)

    data_dir, out = paths(tmp_path)
    portal = RecordingPortal({"40": "New Delhi"}, {"40": svc()})
    assert run(portal, data_dir, out, T1) == 0
    assert portal.date_calls == []
    entry = load(out)["embassies"]["40"]["services"][SERVICE]
    assert entry["available"] is True
    assert entry["dates"] is None
    assert not (data_dir / "samples").exists()


def test_scrape_all_dates_off_by_default():
    scrape, samples = scrape_all(two_embassy_portal())
    assert scrape["embassies"]["40"]["services"][SERVICE] == {"dates": None}
    assert samples == {}


def test_main_with_dates_flag(tmp_path, monkeypatch):
    import checker.__main__ as m

    monkeypatch.setattr(m, "Portal", lambda: two_embassy_portal())
    d = tmp_path / "d"
    assert main(["--data-dir", str(d), "--out", str(tmp_path / "s.json"), "--with-dates"]) == 0
    assert (d / "samples").exists()


def test_main_cli(tmp_path, monkeypatch):
    import checker.__main__ as m

    monkeypatch.setattr(m, "Portal", lambda: two_embassy_portal())
    out = tmp_path / "o" / "s.json"
    code = main(["--data-dir", str(tmp_path / "d"), "--out", str(out)])
    assert code == 0
    assert out.exists()
