# Visa Availability Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the hourly Playwright/Gmail checker with a `requests`-based scraper that runs every 10 minutes in GitHub Actions and publishes `status.json` plus a static filter UI to GitHub Pages.

**Architecture:** `checker/portal.py` (HTTP + HTML parsing) → `checker/__main__.py` (scrape all embassies, 4 workers) → `checker/state.py` (pure merge with previous state) → `status.json`. A single Actions workflow keeps state on a `data` branch (committed only on material change) and deploys `site/` + fresh `status.json` to Pages. The site is vanilla ES modules; filtering and staleness logic live in `site/logic.js` and are unit-tested with `node --test`.

**Tech Stack:** Python 3.12 (CI; 3.10 locally), `requests`, `beautifulsoup4` (stdlib `html.parser`), `pytest`; vanilla JS ES modules; GitHub Actions (`actions/checkout@v4`, `actions/setup-python@v5`, `actions/upload-pages-artifact@v3`, `actions/deploy-pages@v4`).

**Spec:** `docs/superpowers/specs/2026-10-17-visa-availability-dashboard-design.md` (approved 2026-10-17, with two amendments already applied: `available_since` naming, and commit-on-change ignoring timestamps).

## Global Constraints

- Portal base URL `https://broneering.mfa.ee/en/`; form fields `broneering[esindus]`, `broneering[isikuteArv]` (always `"1"`), `broneering[_token]`, services select `broneering[toiming]`. A POST response of HTTP **422 is normal**.
- Fresh `requests.Session` + fresh CSRF token for every embassy call.
- Polite load: ≤ 4 concurrent requests; 3 attempts with exponential backoff; 15 s timeout; descriptive User-Agent `visa-availability-dashboard (+https://github.com/josephjoel3099/visa-appointment-checker)`.
- No email or any notification sender; no Playwright/Chromium; no `GMAIL_*` references anywhere.
- The workflow file MUST be `.github/workflows/check.yml`, keep `workflow_dispatch`, plus `schedule` cron every 15 min as fallback; `concurrency: group: check, cancel-in-progress: false`.
- `status.json` shape and `service_catalog` seed `Long-stay visa (D-visa) application` exactly as in the spec; catalog never shrinks.
- Samples of raw HTML go to `data/samples/` on the `data` branch.
- Site: no build step, choices in `localStorage` (default New Delhi `"40"` + D-visa), stale warning at > 30 min, re-poll `status.json` every 60 s.
- **Do not `git commit` or `git push`** at any point; the user has not authorized it. Each task ends with a checkpoint (tests green), not a commit. Do not touch `docs/` files other than this plan and the spec.
- Never ask the user for the GitHub token; it lives only in cron-job.org.

## Review Focus

Input classes the spec implies but does not spell out; each has a test in the owning task.

1. Portal answers 200/422 but the services `<select>` is gone (markup changed) → must be an embassy failure (`ok: false`, previous data kept), never "no appointments". (Task 1, Task 4)
2. Blank placeholder option, padded whitespace, or duplicate option text in the services select → ignored/stripped/deduped, never a phantom "available" service. (Task 1)
3. Corrupt, empty, or missing previous `data/status.json` (first run, bad branch contents) → treated as no previous state, run still succeeds. (Task 4)
4. Selection saved in `localStorage` references embassies/services no longer in `status.json`, or is empty → no crash; stale ids are skipped and an empty selection yields a hint. (Task 5)
5. More than half the embassies fail, or `list_embassies` itself fails (portal down) → exit 1, published data keeps old availability, only `last_checked` moves. `last_success` is `null` before the first success and the site must cope. (Task 3, Task 4, Task 5)

Known limitation (accepted): because timestamps are not committed, after a failed run `last_success` shown is the one from the last *committed* state, which may be older than the true last success, so the stale banner can appear slightly early.

---

## File Structure

```
checker/__init__.py          package marker
checker/portal.py            HTTP client + HTML parsers (depends on requests, bs4)
checker/state.py             pure merge / equality / run-health functions
checker/__main__.py          orchestration + CLI
tests/fixtures/*.html        saved portal pages
tests/test_portal_parse.py   parser tests
tests/test_portal_client.py  client tests with a fake session
tests/test_live.py           opt-in live test (-m live)
tests/test_state.py
tests/test_main.py
site/index.html app.js logic.js style.css package.json logic.test.js
.github/workflows/check.yml  runner + deploy
.github/workflows/test.yml   pytest + node --test on push/PR
requirements.txt requirements-dev.txt pytest.ini .gitignore README.md
```

---

### Task 1: Portal HTML parsers and fixtures

**Files:**
- Create: `checker/__init__.py` (empty), `checker/portal.py`, `requirements.txt` (`requests`, `beautifulsoup4`), `requirements-dev.txt` (`-r requirements.txt`, `pytest`), `pytest.ini` (registers marker `live`; `addopts = -m "not live"`), `tests/fixtures/home.html`, `tests/fixtures/services_none.html`, `tests/fixtures/services_several.html`, `tests/fixtures/after_service_synthetic.html`
- Modify: `.gitignore` (create if absent; add `cookies.txt`, `site/status.json`, `__pycache__/`, `.pytest_cache/`)
- Test: `tests/test_portal_parse.py`

**Interfaces:**
- Produces (in `checker/portal.py`):
  - `BASE_URL: str`, `USER_AGENT: str` (values from Global Constraints)
  - `class PortalError(Exception)`
  - `@dataclass(frozen=True) class Service: id: str; name: str`
  - `parse_embassies(html: str) -> dict[str, str]` — option value → name, from `select[name="broneering[esindus]"]`, skipping the empty-value option; raises `PortalError` if the select is missing
  - `parse_token(html: str) -> str` — value of `input[name="broneering[_token]"]`; raises `PortalError` if absent
  - `parse_services(html: str) -> list[Service]` — options of `select[name="broneering[toiming]"]`; skips empty-value options, strips whitespace from names, dedupes by name (first wins); raises `PortalError` if the select is missing
  - `parse_dates(html: str) -> list[str] | None` — best-effort: scan visible text (script/style removed) and `data-date`/`data-day`/`value` attributes for `YYYY-MM-DD` and `DD.MM.YYYY` dates; return sorted unique ISO strings, or `None` when none found

- [ ] **Step 1: Capture fixtures** with a one-off script run from the scratchpad (not committed): GET `BASE_URL` → `home.html`; POST New Delhi (`esindus=40`, `isikuteArv=1`, token from the GET, same session) → `services_none.html`. In both, replace the token value with `TESTTOKEN`. Derive `services_several.html` from `services_none.html` by inserting into the `broneering[toiming]` select, after its blank option, `<option value="501">Long-stay visa (D-visa) application</option>`, `<option value="502">Short-stay visa (C-visa) application</option>`, and a third option `<option value="503">  Residence permit application </option>`. Write `after_service_synthetic.html` by hand: a plain page with the header comment `<!-- SYNTHETIC: replace with a real captured sample once a service is bookable -->` and a list containing `2026-11-03`, `04.11.2026`, `2026-11-03` (duplicate).
- [ ] **Step 2: Write failing tests** in `tests/test_portal_parse.py`:
  - `test_parse_embassies_home`: result has 40 entries, `result["40"] == "Embassy of the Republic of Estonia in New Delhi"`, `result["4"].endswith("London")`, `"" not in result`
  - `test_parse_token`: `parse_token(home) == "TESTTOKEN"`; `parse_token("<html></html>")` raises `PortalError`
  - `test_parse_services_none`: `parse_services(services_none) == []`
  - `test_parse_services_several`: `[s.name for s in ...] == ["Long-stay visa (D-visa) application", "Short-stay visa (C-visa) application", "Residence permit application"]` and ids `["501","502","503"]` (whitespace stripped)
  - `test_parse_services_dedupes_names`: HTML with the D-visa option twice yields one `Service`
  - `test_parse_services_missing_select_raises`: `parse_services("<html><body>Maintenance</body></html>")` raises `PortalError` (Review Focus 1)
  - `test_parse_dates_synthetic`: `== ["2026-11-03", "2026-11-04"]`
  - `test_parse_dates_none_found`: `parse_dates(services_none) is None`
- [ ] **Step 3: Run** `pytest tests/test_portal_parse.py -v` → FAIL (`ModuleNotFoundError`/`ImportError`).
- [ ] **Step 4: Implement** the interfaces above in `checker/portal.py` using `BeautifulSoup(html, "html.parser")`; one regex pair for dates, converting `DD.MM.YYYY` to ISO.
- [ ] **Step 5: Run** `pytest tests/test_portal_parse.py -v` → all PASS.
- [ ] **Step 6: Checkpoint** (no commit): `pytest -q` green.

---

### Task 2: Portal HTTP client

**Files:**
- Modify: `checker/portal.py`
- Create: `tests/test_portal_client.py`, `tests/test_live.py`

**Interfaces:**
- Consumes: Task 1 parsers, `Service`, `PortalError`, `BASE_URL`, `USER_AGENT`
- Produces:
  - `@dataclass class DatesResult: dates: list[str] | None; pages: dict[str, str]` (`pages` keys: `"home"`, `"services"`, `"after_service"`)
  - `class Portal` with `__init__(self, session_factory=requests.Session, sleep=time.sleep, base_url=BASE_URL, timeout=15, attempts=3)` and:
    - `list_embassies(self) -> dict[str, str]`
    - `list_services(self, embassy_id: str) -> list[Service]`
    - `list_dates(self, embassy_id: str, service_id: str) -> DatesResult` — GET home, POST embassy (`isikuteArv="1"`), then POST the same form plus `broneering[toiming]=service_id` using the token from the services response; `dates = parse_dates(last page)`. Raises `PortalError` on HTTP failure; a parse miss is `dates=None`, not an error.
  - Retry rule (private `_request`): retry on `requests.RequestException`, HTTP 429 and ≥ 500; sleep `1.0 * 2**n` between attempts (so `[1.0, 2.0]` for 3 attempts); GET accepts 200, POST accepts 200 and 422; any other status raises `PortalError` immediately without retry. Every call creates a new session via `session_factory()`, sets `headers["User-Agent"] = USER_AGENT`, passes `timeout`.

- [ ] **Step 1: Write failing tests** using a `FakeSession` (records `get`/`post` calls, returns scripted `FakeResponse(status_code, text)` or raises a scripted exception) injected via `session_factory`, and a `sleeps` list passed as `sleep=sleeps.append`:
  - `test_list_services_posts_form_fields`: after `list_services("40")` with scripted home + `services_several`, the POST `data` equals `{"broneering[esindus]": "40", "broneering[isikuteArv]": "1", "broneering[_token]": "TESTTOKEN"}` and the session header `User-Agent == USER_AGENT`
  - `test_422_is_not_an_error`: POST scripted 422 with `services_none` → `[]`
  - `test_each_call_uses_fresh_session`: two `list_services` calls → `session_factory` invoked twice
  - `test_retries_connection_error_then_succeeds`: first GET raises `requests.ConnectionError`, second succeeds; `sleeps == [1.0]`
  - `test_gives_up_after_three_attempts`: three 503s → `PortalError`; `sleeps == [1.0, 2.0]`
  - `test_403_not_retried`: one 403 → `PortalError`, `sleeps == []`, one call made
  - `test_list_dates_returns_pages_and_dates`: scripted home, `services_several`, `after_service_synthetic` → `dates == ["2026-11-03","2026-11-04"]`, `set(pages) == {"home","services","after_service"}`, final POST has `broneering[toiming] == "501"`
  - `test_list_dates_unparseable_gives_none`: last page = `services_none` → `dates is None`
- [ ] **Step 2: Write `tests/test_live.py`** with `@pytest.mark.live`: `Portal().list_embassies()` has ≥ 30 entries including `"40"`; `Portal().list_services("40")` returns a `list` (no assertion on contents).
- [ ] **Step 3: Run** `pytest tests/test_portal_client.py -v` → FAIL (`Portal` undefined).
- [ ] **Step 4: Implement** `Portal` and `DatesResult` in `checker/portal.py` per the interface block.
- [ ] **Step 5: Run** `pytest -q` → PASS; then `pytest -m live -v` → PASS (needs network; one real call per test).
- [ ] **Step 6: Checkpoint** (no commit).

---

### Task 3: State merge logic

**Files:**
- Create: `checker/state.py`
- Test: `tests/test_state.py`

**Interfaces:**
- Produces:
  - `SEED_CATALOG: list[str] = ["Long-stay visa (D-visa) application"]`
  - Scrape shape (input): `{"embassies": {"<id>": {"name": str, "ok": bool, "services": {"<service name>": {"dates": list[str] | None}}}}}`
  - `is_run_ok(scrape: dict) -> bool` — `False` when there are no embassies or **more than half** have `ok: False` (exactly half is still OK)
  - `merge(previous: dict | None, scrape: dict, now: str) -> dict` — returns the full `status.json` dict from the spec:
    - always sets `last_checked = now`; `last_success = now` only if `is_run_ok(scrape)`, else previous value (`None` if no previous)
    - if not `is_run_ok`: embassies and catalog are returned unchanged from `previous` (empty if none)
    - per embassy with `ok: True`: set `name`, `ok=True`, `checked_at=now`; each scraped service → `available=True`, `available_since` = previous value if previously available else `now`, `last_seen_available=now`, `dates` as scraped; each previously-known service not scraped → `available=False`, `available_since=None`, `dates=None`, `last_seen_available` kept
    - per embassy with `ok: False`: keep previous services and `checked_at`, set `ok=False` (new embassy that failed: `services={}`, `checked_at=None`)
    - embassies in `previous` but absent from `scrape` are kept untouched
    - `service_catalog` = sorted union of `SEED_CATALOG`, previous catalog, and every scraped service name
  - `materially_equal(a: dict | None, b: dict | None) -> bool` — deep equality after dropping `last_checked`, `last_success` (top level) and `checked_at` (per embassy); `None` equals only `None`

- [ ] **Step 1: Write failing tests** (`NOW1="2026-10-17T10:00:00Z"`, `NOW2="2026-10-17T10:10:00Z"`, helper `scrape(**{id: (ok, {name: dates})})`):
  - `test_first_run_service_appears`: `merge(None, ...)` → service `available is True`, `available_since == NOW1`, `last_seen_available == NOW1`, catalog contains seed and the service, `last_success == NOW1`
  - `test_stays_available_keeps_since`: second merge at `NOW2` → `available_since == NOW1`, `last_seen_available == NOW2`
  - `test_disappears`: merge with empty services → `available is False`, `available_since is None`, `last_seen_available == NOW1`, `dates is None`
  - `test_embassy_failure_keeps_previous_services`: `ok: False` → `ok is False`, services and `checked_at` equal previous
  - `test_majority_failure_only_moves_last_checked`: 3 of 4 embassies fail → embassies and catalog equal previous, `last_checked == NOW2`, `last_success == NOW1`
  - `test_majority_failure_first_run`: `merge(None, all-failed, NOW1)` → `embassies == {}`, `last_success is None`, `last_checked == NOW1`
  - `test_exactly_half_failing_is_ok`: 2 of 4 failing → `is_run_ok` True
  - `test_no_embassies_not_ok`: `is_run_ok({"embassies": {}})` False
  - `test_catalog_never_shrinks_and_sorted`
  - `test_absent_embassy_is_kept`
  - `test_materially_equal_ignores_timestamps`: same data merged at `NOW1` and `NOW2` → True; flipping one service's availability → False; `materially_equal(None, None)` True, `materially_equal(None, merged)` False
- [ ] **Step 2: Run** `pytest tests/test_state.py -v` → FAIL.
- [ ] **Step 3: Implement** `checker/state.py`; pure functions, no I/O, never mutate arguments (deep-copy `previous`).
- [ ] **Step 4: Run** `pytest tests/test_state.py -v` → PASS.
- [ ] **Step 5: Checkpoint** (no commit): `pytest -q` green.

---

### Task 4: Orchestrator and CLI

**Files:**
- Create: `checker/__main__.py`
- Test: `tests/test_main.py`

**Interfaces:**
- Consumes: `Portal`, `PortalError`, `Service`, `DatesResult` (Tasks 1–2); `merge`, `is_run_ok`, `materially_equal` (Task 3)
- Produces:
  - `MAX_WORKERS = 4`
  - `scrape_all(portal, now: str) -> tuple[dict, dict]` — returns `(scrape, samples)`; `scrape` in the Task 3 shape; `samples` maps `(embassy_id, service_name)` → `pages` dict. Embassies scraped in a `ThreadPoolExecutor(max_workers=MAX_WORKERS)`. Per embassy: `list_services`; any exception → `ok: False, services: {}`. Per listed service: `portal.list_dates(...)`; any exception → `dates: None` and the service still counts as available. If `portal.list_embassies()` raises → return `({"embassies": {}}, {})`.
  - `run(portal, data_dir: Path, out_path: Path, now: str) -> int` — loads `data_dir/status.json` (missing/unparseable/non-dict → `None`); `scrape_all`; `merge`; **always** writes `out_path` (create parents, JSON indent 2, sorted keys); writes `data_dir/status.json` **only if** `not materially_equal(previous, merged)`; saves each sample page as `data_dir/samples/<embassy_id>__<slugified service name>/<step>.html` only when that directory does not exist yet (written in the main thread after the pool finishes); returns `0` if `is_run_ok(scrape)` else `1`.
  - `main(argv: list[str] | None = None) -> int` — args `--data-dir` (default `data`), `--out` (default `public/status.json`); `now` is current UTC as `%Y-%m-%dT%H:%M:%SZ`; entry via `python -m checker`.

- [ ] **Step 1: Write failing tests** with a `FakePortal` (dict of embassy id → services list or exception; `list_dates` scripted) and `tmp_path`:
  - `test_first_run_writes_out_and_data`: both `out` and `data/status.json` exist, return 0, New Delhi service `available`
  - `test_unchanged_run_does_not_touch_data_file`: pre-seed `data/status.json` from a first run with old timestamps; second run with identical portal state at a later `now` → data file bytes unchanged, `out` has the new `last_checked`
  - `test_embassy_failure_is_isolated`: one embassy raises `PortalError`, others fine → return 0, that embassy `ok is False`, others scraped
  - `test_missing_services_select_is_embassy_failure` (Review Focus 1): `FakePortal` raising `PortalError` from `list_services` for an embassy whose previous state had an available service → previous availability kept, `ok is False`
  - `test_majority_failure_returns_1_and_keeps_data`: 3 of 4 fail → return 1, `data/status.json` bytes unchanged, `out` has old availability and new `last_checked`
  - `test_list_embassies_failure`: `list_embassies` raises → return 1, `out` still written
  - `test_corrupt_previous_treated_as_none` (Review Focus 3): `data/status.json` contains `{not json` (also test empty file and `[]`) → return 0, valid output
  - `test_dates_failure_still_available`: `list_dates` raises → `available is True`, `dates is None`
  - `test_samples_saved_once`: first run creates `data/samples/40__long-stay-visa-d-visa-application/{home,services,after_service}.html`; second run with different page text leaves the originals unchanged
  - `test_max_workers_is_four`: `MAX_WORKERS == 4`
- [ ] **Step 2: Run** `pytest tests/test_main.py -v` → FAIL.
- [ ] **Step 3: Implement** `checker/__main__.py` per the interface block.
- [ ] **Step 4: Run** `pytest -q` → PASS.
- [ ] **Step 5: Smoke against the real portal** (writes only to the scratchpad): `python -m checker --data-dir <scratchpad>/data --out <scratchpad>/public/status.json`; expect exit 0 and ~40 embassies in the output within ~10 s. Copy that output to `site/status.json` (gitignored) for Task 6.
- [ ] **Step 6: Checkpoint** (no commit).

---

### Task 5: Site logic (pure JS) with Node tests

**Files:**
- Create: `site/logic.js` (ES module), `site/package.json` (`{"type": "module"}`), `site/logic.test.js`

**Interfaces:**
- Produces (named exports of `site/logic.js`):
  - `DEFAULT_SELECTION = { embassies: ["40"], services: ["Long-stay visa (D-visa) application"] }`
  - `STALE_MINUTES = 30`
  - `ageMinutes(iso: string | null, now: Date) -> number` (`Infinity` when `iso` is null/invalid)
  - `staleness(status, now: Date) -> { stale: boolean, reason: "old" | "failing" | null, minutes: number }` — `"failing"` when `last_success !== last_checked` (including `last_success` null); else `"old"` when `ageMinutes(last_checked) > STALE_MINUTES`; else not stale
  - `selectRows(status, selection) -> Row[]` where `Row = { embassyId, embassyName, service, state: "available" | "full" | "error", dates: string[] | null, availableSince: string | null, lastSeenAvailable: string | null }`; one row per selected embassy × selected service, ordered by embassy name then service; embassy ids not in `status.embassies` are skipped; `state "error"` when the embassy has `ok: false`; a service missing from the embassy is `"full"`
  - `newlyAvailable(prevRows: Row[], nextRows: Row[]) -> Row[]` — rows `available` now that were not `available` for the same `embassyId`+`service` before (an unseen row counts as not available)
  - `normalizeSelection(saved: unknown) -> { embassies: string[], services: string[] }` — returns `DEFAULT_SELECTION` copy when `saved` is not an object with string arrays; keeps an explicitly empty array as empty

- [ ] **Step 1: Write failing tests** in `site/logic.test.js` using `node:test` and `node:assert/strict` (fixture status objects built inline):
  - `staleness`: fresh success → `{stale:false, reason:null}`; `last_checked` 31 min old with equal `last_success` → `reason "old"`; `last_success` earlier than `last_checked` → `"failing"`; `last_success: null` → `"failing"`
  - `selectRows`: available/full/error cases; ordering; skips embassy id `"999"` not in status (Review Focus 4); empty selection → `[]`; service name not in catalog → `"full"` rows without throwing
  - `newlyAvailable`: full→available included; available→available excluded; unseen→available included; available→full excluded
  - `normalizeSelection`: `null`, `"x"`, `{embassies: [1]}` → default; `{embassies: [], services: []}` preserved
- [ ] **Step 2: Run** `cd site && node --test` → FAIL (module not found). **If `node` is not installed locally** (it was not on 2026-10-17), stop and tell the user rather than skipping: either they install it (e.g. `sudo apt install nodejs`) or these tests are verified only in CI via Task 7's `test.yml`.
- [ ] **Step 3: Implement** the exports in `site/logic.js`; no DOM, no `localStorage`, no `Date.now()` inside (always pass `now`).
- [ ] **Step 4: Run** `cd site && node --test` → PASS.
- [ ] **Step 5: Checkpoint** (no commit).

---

### Task 6: Site UI

**Files:**
- Create: `site/index.html`, `site/app.js`, `site/style.css`

**Interfaces:**
- Consumes: all exports of `site/logic.js`; `status.json` served next to `index.html`.
- Produces: the page; no exports.

Behavior (from the spec's Site section):
- `index.html` loads `app.js` as `<script type="module">`; mobile-friendly, light/dark via `prefers-color-scheme`.
- Two checklists: embassies (all, from `status.embassies`, sorted by name) and appointment types (`status.service_catalog`). Selection persisted to `localStorage` under one key via `normalizeSelection`; every `localStorage` read/write wrapped in `try/catch` and the page works without it.
- Results list from `selectRows`: per row show embassy, service, state badge (available / full / check failing), `dates` when non-null, else for available rows the text "Available — dates not parsed, open portal"; "last seen available" when set; a link to `https://broneering.mfa.ee/en/`. Empty selection shows a hint to pick an embassy and a type.
- Header: "Last checked N min ago" from `staleness`; warning banner when `stale` (text differs for `"old"` vs `"failing"`).
- Re-fetch `status.json` (`cache: "no-store"`) every 60 s and on tab focus. When `newlyAvailable` is non-empty after a refresh: prefix `document.title` with `(!)` until the tab becomes visible, and show a `Notification` only if permission is already `"granted"`; a small button requests permission.
- Fetch failure keeps the last data and shows the warning banner.

- [ ] **Step 1: Write the three files** per the behavior list above.
- [ ] **Step 2: Manual verification** with `python -m http.server -d site 8000` and the `site/status.json` from Task 4 Step 5: page loads with the New Delhi + D-visa default showing "full"; changing selection survives a reload; a copy of `status.json` edited so New Delhi's D-visa is `available: true` (with `dates: null`) shows the "dates not parsed" text; setting `last_checked` 40 min back shows the stale banner; blocking `status.json` (rename it) keeps the data and shows the warning. Report each of these observations honestly; if no browser is available to the session, say so and give the user this checklist to run.
- [ ] **Step 3: Checkpoint** (no commit): `cd site && node --test` still green (skip if node unavailable, as per Task 5).

---

### Task 7: Workflows, README, and cleanup

**Files:**
- Create: `.github/workflows/check.yml`, `.github/workflows/test.yml`
- Modify: `README.md` (full rewrite)
- Delete: `check_visa.py`, `.github/workflows/check_visa.yml`, `cookies.txt` (untracked; confirm it is only the session cookie before deleting)

**Interfaces:**
- Consumes: `python -m checker --data-dir data --out public/status.json`; site files `index.html app.js logic.js style.css`.

`check.yml` requirements:
- Triggers: `workflow_dispatch`, `schedule` cron `*/15 * * * *`. Top-level `concurrency: { group: check, cancel-in-progress: false }`.
- One job on `ubuntu-latest` with `permissions: { contents: write, pages: write, id-token: write }` and `environment: { name: github-pages, url: ${{ steps.deployment.outputs.page_url }} }`.
- Steps, in order: checkout `main`; ensure the `data` branch exists on `origin` (if `git ls-remote --exit-code --heads origin data` fails, create an orphan branch with one empty commit as `github-actions[bot]` and push it, then return to `main`); checkout `data` into path `data`; setup Python 3.12 with pip cache; `pip install -r requirements.txt`; **run the checker with `id: check` and `continue-on-error: true`**; copy the four site files into `public/`; commit `data/` to the `data` branch only if `git diff --cached --quiet` reports changes (`git add -A` inside `data/`, commit message `Update status`, push `origin data`); `actions/upload-pages-artifact@v3` with `path: public`; `actions/deploy-pages@v4` with `id: deployment`; final step `if: steps.check.outcome == 'failure'` that runs `exit 1` so a failed scrape still deploys but shows red.

`test.yml`: on `push` and `pull_request` to `main`; steps: checkout, Python 3.12, `pip install -r requirements-dev.txt`, `pytest -q`, setup-node 20, `cd site && node --test`. No secrets, no schedule.

README (rewrite): what it does; how the site works; layout table; setup (repo Settings → Pages → Source = GitHub Actions; cron-job.org job POSTing `{"ref":"main"}` to `https://api.github.com/repos/josephjoel3099/visa-appointment-checker/actions/workflows/check.yml/dispatches` every 10 min with a fine-grained token, header `Accept: application/vnd.github+json`, expecting HTTP 204; token never stored in the repo); local dev (`pip install -r requirements-dev.txt`, `pytest`, `pytest -m live`, `python -m checker`, `node --test`); the dates-step limitation and `data/samples/`. No Gmail mentions.

- [ ] **Step 1: Write** `check.yml`, `test.yml`, README.
- [ ] **Step 2: Remove** the old files listed above (`git rm` for tracked ones, `rm cookies.txt`).
- [ ] **Step 3: Validate**: both workflow files parse with `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/*.yml` (install `pyyaml` in the scratchpad venv if missing); `grep -rniE "gmail|playwright|smtp" . --exclude-dir=.git --exclude-dir=docs` returns nothing; `pytest -q` green; `git status --short` shows only the intended adds/removes.
- [ ] **Step 4: Stop and report to the user**; do not commit or push. When the user asks to commit/push, push, then tell them: (a) set **Settings → Pages → Source = "GitHub Actions"**; (b) enable the cron-job.org job (a success returns **HTTP 204**); (c) optionally trigger the first run with `gh workflow run check.yml` and watch `gh run watch`, confirming the `data` branch appears and the Pages URL serves `status.json`.
