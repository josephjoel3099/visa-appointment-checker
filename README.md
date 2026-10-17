# Estonia Visa Appointment Dashboard

Watches the [Estonia MFA booking portal](https://broneering.mfa.ee/en/) and
publishes a small static website showing which services each embassy currently
lists. You choose the embassies and services you care about, the choice is
saved in your browser, and the page highlights when one of them appears.

## What "available" means

A service counts as **available** when it is **listed on the portal** for that
embassy. Appointment **dates are not shown**: the portal's calendar page sits
behind a reCAPTCHA, and this project does not try to bypass it. Open the portal
yourself to pick a date once a service shows up.

## How it works

1. A GitHub Actions workflow (`check.yml`) runs every ~10 minutes. It is
   triggered by a [cron-job.org](https://cron-job.org) job calling the GitHub
   API, with GitHub's own `*/15` cron as a fallback. Only one run at a time
   (`concurrency: check`).
2. `python -m checker` reads the public portal (embassies, then the services
   listed for each one), merges the result with the previous state and writes
   `public/status.json`.
3. The previous state lives on a separate `data` branch (created automatically
   on the first run). It is committed to only when something materially
   changed, ignoring timestamps, so the branch history is a clean change log.
4. The four files in `site/` plus the fresh `status.json` are deployed to
   GitHub Pages on every run. The page reads `status.json`, filters it using
   your saved choices (`localStorage`), and can show a browser notification
   and title marker when a selected service becomes available (only while the
   page is open).
5. If more than half of the embassies fail to load, the run still deploys the
   last known data and logs a workflow warning. The run stays **green** during
   a short or transient outage and only finishes **red** on a *sustained*
   outage, meaning the last successful check (`last_success` in
   `status.json`) is more than 60 minutes old, or there is none at all. The
   dashboard itself also shows a stale/failing banner whenever data is old.

All data comes from the portal's public pages; no account or credentials are
involved.

## Layout

| Path | Purpose |
| --- | --- |
| `checker/portal.py` | HTTP client and HTML parsing for the portal |
| `checker/state.py` | Pure merge of a fresh scrape with the previous state |
| `checker/__main__.py` | CLI: scrape, merge, write `status.json` |
| `site/` | Static dashboard (`index.html`, `app.js`, `logic.js`, `style.css`) and its JS tests |
| `tests/` | Python tests (`test_live.py` hits the real portal and is opt-in) |
| `.github/workflows/check.yml` | Scheduled check and Pages deploy |
| `.github/workflows/test.yml` | Python and JS tests on push / pull request |
| `docs/` | Design spec and plan |

## Setup

1. **Pages**: in the repo, go to **Settings -> Pages -> Build and deployment ->
   Source** and choose **GitHub Actions**.
2. **First run**: open **Actions -> Check availability -> Run workflow**. This
   creates the `data` branch and publishes the site.
3. **Reliable scheduling (recommended)**: GitHub's cron is often delayed, so
   add a job on [cron-job.org](https://cron-job.org):
   - URL: `https://api.github.com/repos/josephjoel3099/visa-appointment-checker/actions/workflows/check.yml/dispatches`
   - Method: `POST`, every 10 minutes
   - Request body: `{"ref":"main"}`
   - Headers: `Accept: application/vnd.github+json` and
     `Authorization: Bearer <token>`
   - Expected response: **HTTP 204** (that means success)
   - Token: a fine-grained personal access token limited to this repository
     only, with **Actions: Read and write**. Store it only in cron-job.org.
     Never put it in this repository, a workflow file or a secret here.

## Notifications, hosting and inactivity

- GitHub emails the owner about failed workflow runs by default. Even with the
  sustained-outage rule above you may want to turn this off: open **GitHub
  Settings -> Notifications -> Actions** and untick the email option for failed
  workflows (or choose "Don't notify").
- The setup assumes a **public repository**: free-plan GitHub Pages requires
  one, and about 6 runs per hour would burn the Actions minutes of a private
  repository.
- GitHub disables scheduled workflows after 60 days without repository
  activity. The cron-job.org dispatch is unaffected, since it calls the API
  directly rather than relying on GitHub's `schedule` trigger.

## Local development

```bash
pip install -r requirements-dev.txt
pytest                      # unit tests (live tests are deselected)
pytest -m live              # also hit the real portal
python -m checker           # writes public/status.json and data/status.json
cd site && node --test      # JS tests
```

`python -m checker` creates `data/` and `public/` locally; both are
git-ignored, so state is never committed to `main`.

Open `site/index.html` through a local web server with a `status.json` next to
it (for example copy `public/status.json` to `site/status.json`, which is
git-ignored) to preview the dashboard.

## Limitations

- Dates are not collected because of the reCAPTCHA (see above). The checker has
  an optional `--with-dates` flag that stays off; since dates are never
  scraped, no samples are written and `data/samples/` stays empty.
- The portal's HTML may change; if parsing breaks, the data goes stale and,
  once the outage is sustained (over 60 minutes), runs show red.
