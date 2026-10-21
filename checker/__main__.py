"""Orchestrator and CLI: scrape the portal, merge with previous state, publish."""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

from checker.portal import MaintenanceError, Portal
from checker.state import is_run_ok, materially_equal, merge

MAX_WORKERS = 4

log = logging.getLogger("checker")


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")


def _scrape_embassy(
    portal, embassy_id: str, name: str, with_dates: bool
) -> tuple[dict, dict]:
    samples: dict = {}
    try:
        listed = portal.list_services(embassy_id)
    except Exception as exc:
        log.warning("embassy %s (%s): %s: %s", embassy_id, name, type(exc).__name__, exc)
        return {"name": name, "ok": False, "services": {}}, samples
    services: dict = {}
    for service in listed:
        dates = None
        if with_dates:
            try:
                result = portal.list_dates(embassy_id, service.id)
                dates = result.dates
                samples[(embassy_id, service.name)] = result.pages
            except Exception as exc:
                log.warning(
                    "embassy %s (%s) service %r dates: %s: %s",
                    embassy_id, name, service.name, type(exc).__name__, exc,
                )
                dates = None
        services[service.name] = {"dates": dates}
    return {"name": name, "ok": True, "services": services}, samples


# NOTE on `with_dates`: the dates calendar sits behind "To the next page" plus a
# reCAPTCHA (confirmed from real saved samples), so it is unreachable without
# solving a CAPTCHA. It is therefore OFF by default; no CAPTCHA circumvention is
# to be attempted. When off, list_dates is never called, every service gets
# dates None and no samples are collected.
def scrape_all(portal, with_dates: bool = False) -> tuple[dict, dict]:
    try:
        embassies = portal.list_embassies()
    except MaintenanceError as exc:
        log.warning("list_embassies: %s", exc)
        return {"embassies": {}, "maintenance_until": exc.until}, {}
    except Exception as exc:
        log.warning("list_embassies: %s: %s", type(exc).__name__, exc)
        return {"embassies": {}}, {}

    scrape: dict = {"embassies": {}}
    samples: dict = {}
    with ThreadPoolExecutor(max_workers=MAX_WORKERS) as pool:
        futures = {
            eid: pool.submit(_scrape_embassy, portal, eid, name, with_dates)
            for eid, name in embassies.items()
        }
        for eid, future in futures.items():
            try:
                emb, emb_samples = future.result()
            except Exception as exc:
                log.warning(
                    "embassy %s (%s): %s: %s", eid, embassies[eid], type(exc).__name__, exc
                )
                emb, emb_samples = {"name": embassies[eid], "ok": False, "services": {}}, {}
            scrape["embassies"][eid] = emb
            samples.update(emb_samples)
    return scrape, samples


def _load_previous(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def _write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _save_samples(data_dir: Path, samples: dict) -> None:
    for (embassy_id, service_name), pages in samples.items():
        target = data_dir / "samples" / f"{embassy_id}__{_slug(service_name)}"
        if target.exists():
            continue
        target.mkdir(parents=True)
        for step, html in pages.items():
            (target / f"{step}.html").write_text(html, encoding="utf-8")


def run(
    portal, data_dir: Path, out_path: Path, now: str, with_dates: bool = False
) -> int:
    data_dir = Path(data_dir)
    out_path = Path(out_path)
    status_file = data_dir / "status.json"

    previous = _load_previous(status_file)
    scrape, samples = scrape_all(portal, with_dates)
    # An announced maintenance window is a planned outage, not a failed run.
    # Once its end has passed the run counts as failed again, but the window
    # stays recorded so the dashboard can say the maintenance is overrunning.
    maintenance_until = scrape.get("maintenance_until")
    if maintenance_until and maintenance_until <= now:
        log.warning("maintenance ended at %s but the portal still answers 503", maintenance_until)
        planned = False
    else:
        planned = bool(maintenance_until)
    merged = merge(previous, scrape, now)

    _write_json(out_path, merged)
    # A failed run must never create or alter the data file.
    run_ok = is_run_ok(scrape)
    if run_ok and not materially_equal(previous, merged):
        _write_json(status_file, merged)
    _save_samples(data_dir, samples)
    return 0 if run_ok or planned else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m checker")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--out", default="public/status.json")
    # Off by default: the calendar is behind a reCAPTCHA (see scrape_all); do not
    # attempt to circumvent it.
    parser.add_argument("--with-dates", action="store_true", default=False)
    args = parser.parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr, level=logging.INFO, format="%(levelname)s %(message)s"
    )
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    return run(Portal(), Path(args.data_dir), Path(args.out), now, args.with_dates)


if __name__ == "__main__":
    sys.exit(main())
