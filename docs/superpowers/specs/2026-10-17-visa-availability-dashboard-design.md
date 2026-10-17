# Visa Appointment Availability Dashboard — Design

Date: 2026-10-17

## Goal
Replace the hourly, email-sending Playwright checker with a fast, reliable
runner that checks every 10 minutes and publishes results to a GitHub Pages
site. The user picks the embassies and appointment types they care about and
sees whether appointments are available and when. No email or other push
notification service.

## Background (verified 2026-10-17)
- Portal: `https://broneering.mfa.ee/en/` (Estonian MFA booking).
- The form is a plain POST (`broneering[esindus]`, `broneering[isikuteArv]`,
  `broneering[_token]` CSRF token read from the GET). No browser is needed;
  `requests` returns the services `<select name="broneering[toiming]">` in
  ~0.3 s per embassy. Response status is 422 (form re-render) and is normal.
- The portal states that a service missing from the list means no free
  appointments. A listed service therefore means slots exist.
- 40 representations (`broneering[esindus]` option values) exist. At time of
  writing all 40 list zero services.
- The page after choosing a service (the calendar of dates) is behind a
  reCAPTCHA and is not scraped; see "Dates step" below.

## Non-goals
Booking appointments, email/SMS/chat notifications, multi-person (>1) checks,
user accounts or a backend.

## Architecture

```
cron-job.org ──(POST workflow_dispatch every 10 min)──┐
GitHub cron (fallback, every 15 min) ─────────────────┤
                                                      ▼
                         Actions workflow `check.yml` (concurrency: 1 run)
                           1. checkout `main` (code) + `data` branch (state)
                           2. python -m checker  → writes data/status.json
                           3. commit data/ to `data` branch only if changed,
                              ignoring `last_checked`/`checked_at` timestamps
                              (the deployed site always gets fresh timestamps
                              because it is built from the run's output)
                           4. build site = site/ + data/status.json
                           5. deploy to GitHub Pages (actions/deploy-pages)
                                                      ▼
                         Static site: index.html filters status.json
                         client-side using choices saved in localStorage
```

### Units
- `checker/portal.py` — HTTP client for the portal. `list_embassies()`,
  `list_services(embassy_id)`, and `list_dates(embassy_id, service_id)`
  (best-effort, see below). Each call uses a fresh session + CSRF token.
  Depends only on `requests`.
- `checker/state.py` — merges a fresh scrape with the previous
  `status.json` (pure function): updates `available`, `available_since` (set
  when a service flips to available, cleared when it goes away),
  `last_seen_available`, the catalog of service names seen, and `last_checked`.
- `checker/__main__.py` — orchestrates: scrape all embassies (small thread
  pool, max 4 workers, retries with backoff), merge, write JSON.
- `site/index.html` (+ `app.js`, `style.css`) — vanilla JS, no build step.
- `.github/workflows/check.yml` — triggers `workflow_dispatch` and
  `schedule`; `concurrency: group: check, cancel-in-progress: false`.

### Data (`status.json`)
```json
{
  "last_checked": "ISO-8601 UTC",
  "last_success": "ISO-8601 UTC",
  "embassies": {
    "40": {
      "name": "Embassy of the Republic of Estonia in New Delhi",
      "ok": true,
      "checked_at": "...",
      "services": {
        "<service name>": {
          "available": true,
          "available_since": "...",
          "last_seen_available": "...",
          "dates": ["2026-11-03", "..."]
        }
      }
    }
  },
  "service_catalog": ["Long-stay visa (D-visa) application", "..."]
}
```
`service_catalog` grows whenever a new service name is seen and never shrinks,
so the site's appointment-type menu fills in over time. It is seeded with
`Long-stay visa (D-visa) application`. A service absent from a scrape is
marked `available: false` but keeps `last_seen_available`.

### Dates step (amended 2026-10-17 after observing real pages)
Real samples captured once services appeared (216 listed across 36
embassies) showed that every portal page carries a reCAPTCHA and that the
POST selecting a service only re-renders the start form; the calendar sits
behind "To the next page" plus the CAPTCHA. It cannot be reached without
solving the CAPTCHA, which this project will not do. Therefore:
- The dates step is **off by default**: `dates` is always `null` and the
  site shows "Available — open the portal to see dates" with a link.
- `list_dates` and sample capture remain behind an opt-in `--with-dates`
  flag (`python -m checker --with-dates`) for if a CAPTCHA-free source ever
  appears.
- A default run makes ~1 request per embassy (about 40) instead of ~650.
Availability itself never depends on the dates step.

### Site
- Embassy checklist (all 40, from `status.json`) and appointment-type
  checklist (from `service_catalog`). Choices saved in `localStorage`.
  Defaults on first visit: New Delhi + D-visa.
- Shows, for the selection: status per embassy/service (available / full),
  dates if known, last seen available, and a link to the portal.
- Header shows "last checked N min ago"; turns into a warning banner when
  data is older than 30 min or `last_success` lags `last_checked`.
- While the page is open it re-fetches `status.json` every 60 s. When a
  selected service flips to available it changes the tab title and, if the
  user has granted permission, shows a browser notification.

### Error handling
- Per-embassy failures (timeout, non-200/422, form missing) set `ok: false`
  for that embassy and keep its previous availability data; they do not fail
  the whole run. If more than half of embassies fail, the run exits non-zero
  and does not overwrite published data except `last_checked`.
- Retries: 3 attempts, exponential backoff, 15 s timeout.
- Polite load: ≤ 4 concurrent requests, descriptive User-Agent.

### Testing
- `pytest` unit tests for `state.py` (pure merge logic) and for HTML parsing
  in `portal.py` against saved fixtures (home page, services response with
  zero and with several services).
- `portal.py` network calls are covered by one opt-in live test
  (`pytest -m live`) not run in CI.
- Site logic (filtering, staleness) kept in small pure functions in `app.js`,
  tested with Node's built-in test runner if available, otherwise manually.

### Setup requirements (user)
- Repo Settings → Pages → Source: **GitHub Actions**.
- cron-job.org job calling the `workflow_dispatch` endpoint with a
  fine-grained token (Actions: read/write, this repo only).
- Remove obsolete secrets `GMAIL_*`.

### Removed
`send_email_notification`, Playwright dependency and Chromium install,
`cookies.txt` (add to `.gitignore`), Gmail secrets/README sections.
