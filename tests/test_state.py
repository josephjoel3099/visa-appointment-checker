import copy

from checker.state import SEED_CATALOG, is_run_ok, materially_equal, merge

NOW1 = "2026-10-17T10:00:00Z"
NOW2 = "2026-10-17T10:10:00Z"

SVC = "Long-stay visa (D-visa) application"


def scrape(**embassies):
    """scrape(id=(ok, {service: dates}), ...)"""
    return {
        "embassies": {
            eid: {
                "name": f"Embassy {eid}",
                "ok": ok,
                "services": {s: {"dates": d} for s, d in services.items()},
            }
            for eid, (ok, services) in embassies.items()
        }
    }


def test_first_run_service_appears():
    s = scrape(a=(True, {SVC: ["2026-11-01"]}))
    out = merge(None, s, NOW1)
    svc = out["embassies"]["a"]["services"][SVC]
    assert svc["available"] is True
    assert svc["available_since"] == NOW1
    assert svc["last_seen_available"] == NOW1
    assert svc["dates"] == ["2026-11-01"]
    assert out["embassies"]["a"]["name"] == "Embassy a"
    assert out["embassies"]["a"]["ok"] is True
    assert out["embassies"]["a"]["checked_at"] == NOW1
    assert SEED_CATALOG[0] in out["service_catalog"]
    assert SVC in out["service_catalog"]
    assert out["last_success"] == NOW1
    assert out["last_checked"] == NOW1


def test_seed_catalog_value():
    assert SEED_CATALOG == ["Long-stay visa (D-visa) application"]


def test_stays_available_keeps_since():
    s = scrape(a=(True, {SVC: ["2026-11-01"]}))
    first = merge(None, s, NOW1)
    second = merge(first, s, NOW2)
    svc = second["embassies"]["a"]["services"][SVC]
    assert svc["available_since"] == NOW1
    assert svc["last_seen_available"] == NOW2
    assert second["embassies"]["a"]["checked_at"] == NOW2


def test_disappears():
    first = merge(None, scrape(a=(True, {SVC: ["2026-11-01"]})), NOW1)
    second = merge(first, scrape(a=(True, {})), NOW2)
    svc = second["embassies"]["a"]["services"][SVC]
    assert svc["available"] is False
    assert svc["available_since"] is None
    assert svc["last_seen_available"] == NOW2
    assert svc["dates"] is None


def test_reappears_gets_new_since():
    first = merge(None, scrape(a=(True, {SVC: None})), NOW1)
    gone = merge(first, scrape(a=(True, {})), NOW2)
    back = merge(gone, scrape(a=(True, {SVC: None})), "2026-10-17T10:20:00Z")
    svc = back["embassies"]["a"]["services"][SVC]
    assert svc["available_since"] == "2026-10-17T10:20:00Z"


def test_embassy_failure_keeps_previous_services():
    first = merge(
        None,
        scrape(a=(True, {SVC: ["d"]}), b=(True, {}), c=(True, {})),
        NOW1,
    )
    second = merge(
        first,
        scrape(a=(False, {}), b=(True, {}), c=(True, {})),
        NOW2,
    )
    assert second["embassies"]["a"]["ok"] is False
    assert second["embassies"]["a"]["services"] == first["embassies"]["a"]["services"]
    assert second["embassies"]["a"]["checked_at"] == first["embassies"]["a"]["checked_at"]


def test_new_embassy_failure():
    first = merge(None, scrape(a=(True, {}), b=(True, {})), NOW1)
    second = merge(first, scrape(a=(True, {}), b=(True, {}), c=(False, {})), NOW2)
    c = second["embassies"]["c"]
    assert c["ok"] is False
    assert c["services"] == {}
    assert c["checked_at"] is None


def test_majority_failure_only_moves_last_checked():
    first = merge(
        None,
        scrape(a=(True, {SVC: ["d"]}), b=(True, {}), c=(True, {}), d=(True, {})),
        NOW1,
    )
    bad = scrape(
        a=(True, {}), b=(False, {}), c=(False, {}), d=(False, {"Other": None})
    )
    second = merge(first, bad, NOW2)
    assert second["embassies"] == first["embassies"]
    assert second["service_catalog"] == first["service_catalog"]
    assert second["last_checked"] == NOW2
    assert second["last_success"] == NOW1


def test_majority_failure_first_run():
    s = scrape(a=(False, {}), b=(False, {}))
    out = merge(None, s, NOW1)
    assert out["embassies"] == {}
    assert out["service_catalog"] == SEED_CATALOG
    assert out["last_success"] is None
    assert out["last_checked"] == NOW1


def test_exactly_half_failing_is_ok():
    s = scrape(a=(False, {}), b=(False, {}), c=(True, {}), d=(True, {}))
    assert is_run_ok(s) is True


def test_more_than_half_failing_not_ok():
    s = scrape(a=(False, {}), b=(False, {}), c=(False, {}), d=(True, {}))
    assert is_run_ok(s) is False


def test_no_embassies_not_ok():
    assert is_run_ok({"embassies": {}}) is False


def test_catalog_never_shrinks_and_sorted():
    first = merge(None, scrape(a=(True, {"Zeta": None, "Alpha": None})), NOW1)
    assert first["service_catalog"] == sorted(set(SEED_CATALOG) | {"Zeta", "Alpha"})
    second = merge(first, scrape(a=(True, {"Mid": None})), NOW2)
    assert second["service_catalog"] == sorted(set(SEED_CATALOG) | {"Zeta", "Alpha", "Mid"})
    third = merge(second, scrape(a=(True, {})), "2026-10-17T10:20:00Z")
    assert third["service_catalog"] == second["service_catalog"]


def test_absent_embassy_is_kept():
    first = merge(None, scrape(a=(True, {SVC: None}), b=(True, {})), NOW1)
    second = merge(first, scrape(b=(True, {})), NOW2)
    assert second["embassies"]["a"] == first["embassies"]["a"]


def test_does_not_mutate_arguments():
    first = merge(None, scrape(a=(True, {SVC: ["d"]})), NOW1)
    s = scrape(a=(True, {}))
    p_copy, s_copy = copy.deepcopy(first), copy.deepcopy(s)
    out = merge(first, s, NOW2)
    assert first == p_copy
    assert s == s_copy
    out["embassies"]["a"]["services"][SVC]["dates"] = ["x"]
    assert first == p_copy


def test_materially_equal_ignores_timestamps():
    s = scrape(a=(True, {SVC: ["d"]}))
    m1 = merge(None, s, NOW1)
    m2 = merge(None, s, NOW2)
    # same data from scratch: available_since differs, so build via previous
    m2 = merge(m1, s, NOW2)
    assert m1 != m2
    assert materially_equal(m1, m2) is True
    m3 = merge(m1, scrape(a=(True, {})), NOW2)
    assert materially_equal(m1, m3) is False
    assert materially_equal(None, None) is True
    assert materially_equal(None, m1) is False
    assert materially_equal(m1, None) is False


def test_disappear_after_unwritten_runs_uses_disappear_time():
    # materially_equal ignores last_seen_available on available services, so
    # data/status.json is not rewritten while a service stays listed: the
    # stored value lags. The flip must stamp the time it was noticed.
    t1, t2, t3 = NOW1, NOW2, "2026-10-17T14:00:00Z"
    stored = merge(None, scrape(a=(True, {SVC: None})), t1)
    merge(stored, scrape(a=(True, {SVC: None})), t2)  # result discarded
    out = merge(stored, scrape(a=(True, {})), t3)
    svc = out["embassies"]["a"]["services"][SVC]
    assert svc["available"] is False
    assert svc["available_since"] is None
    assert svc["last_seen_available"] == t3


def test_already_unavailable_keeps_last_seen_available():
    first = merge(None, scrape(a=(True, {SVC: None})), NOW1)
    gone = merge(first, scrape(a=(True, {})), NOW2)
    later = merge(gone, scrape(a=(True, {})), "2026-10-17T10:20:00Z")
    svc = later["embassies"]["a"]["services"][SVC]
    assert svc["available"] is False
    assert svc["last_seen_available"] == NOW2


def test_disappearance_flip_is_a_material_change():
    first = merge(None, scrape(a=(True, {SVC: None})), NOW1)
    gone = merge(first, scrape(a=(True, {})), NOW2)
    assert not materially_equal(first, gone)
