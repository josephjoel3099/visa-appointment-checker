"""Pure merge logic that folds a fresh scrape into the persisted status.json."""

from __future__ import annotations

import copy

SEED_CATALOG: list[str] = ["Long-stay visa (D-visa) application"]


def is_run_ok(scrape: dict) -> bool:
    """False when there are no embassies or more than half failed."""
    embassies = scrape.get("embassies") or {}
    if not embassies:
        return False
    failed = sum(1 for e in embassies.values() if not e.get("ok"))
    return failed * 2 <= len(embassies)


def _merge_ok_embassy(prev_emb: dict | None, scraped: dict, now: str) -> dict:
    prev_services = (prev_emb or {}).get("services", {})
    services: dict = {}
    for name, info in scraped.get("services", {}).items():
        prev = prev_services.get(name)
        was_available = bool(prev and prev.get("available"))
        services[name] = {
            "available": True,
            "available_since": prev.get("available_since") if was_available else now,
            "last_seen_available": now,
            "dates": info.get("dates"),
        }
    for name, prev in prev_services.items():
        if name in services:
            continue
        # materially_equal ignores last_seen_available while a service is
        # available, so the stored value lags. On the available -> unavailable
        # flip (which is committed) stamp "now", accurate to one check
        # interval. Already-unavailable services keep their frozen value.
        was_available = bool(prev.get("available"))
        last_seen = now if was_available else prev.get("last_seen_available")
        # The finished window runs from last_available_from to last_seen_available.
        window_start = (
            prev.get("available_since") if was_available else prev.get("last_available_from")
        )
        services[name] = {
            "available": False,
            "available_since": None,
            "last_seen_available": last_seen,
            "last_available_from": window_start,
            "dates": None,
        }
    return {
        "name": scraped.get("name"),
        "ok": True,
        "checked_at": now,
        "services": services,
    }


def merge(previous: dict | None, scrape: dict, now: str) -> dict:
    prev = copy.deepcopy(previous) if previous else {}
    prev_embassies: dict = prev.get("embassies", {})
    catalog = set(SEED_CATALOG) | set(prev.get("service_catalog", []))
    run_ok = is_run_ok(scrape)

    if not run_ok:
        failed = {
            "last_checked": now,
            "last_success": prev.get("last_success"),
            "embassies": prev_embassies,
            "service_catalog": sorted(catalog),
        }
        if scrape.get("maintenance_until"):
            failed["maintenance_until"] = scrape["maintenance_until"]
        return failed

    embassies = prev_embassies  # absent embassies stay untouched
    for eid, scraped in scrape["embassies"].items():
        prev_emb = prev_embassies.get(eid)
        if scraped.get("ok"):
            embassies[eid] = _merge_ok_embassy(prev_emb, scraped, now)
            catalog.update(scraped.get("services", {}))
        elif prev_emb is not None:
            prev_emb["ok"] = False
        else:
            embassies[eid] = {
                "name": scraped.get("name"),
                "ok": False,
                "checked_at": None,
                "services": {},
            }

    return {
        "last_checked": now,
        "last_success": now,
        "embassies": embassies,
        "service_catalog": sorted(catalog),
    }


def _strip(status: dict) -> dict:
    out = copy.deepcopy(status)
    out.pop("last_checked", None)
    out.pop("last_success", None)
    for emb in out.get("embassies", {}).values():
        emb.pop("checked_at", None)
        for svc in emb.get("services", {}).values():
            # For a currently-available service last_seen_available is just
            # "now" and moves every run; once unavailable it is frozen and
            # meaningful, so it stays part of the comparison.
            if svc.get("available"):
                svc.pop("last_seen_available", None)
    return out


def materially_equal(a: dict | None, b: dict | None) -> bool:
    if a is None or b is None:
        return a is None and b is None
    return _strip(a) == _strip(b)
