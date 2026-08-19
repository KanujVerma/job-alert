# job-alert

## 1. What it does

Monitors 14 configured company career sites (12 currently enabled — see section 12) every 15 minutes for U.S.-based internships, new-grad, and entry-level tech roles. Sends Discord webhook alerts when new postings are detected. Runs free on GitHub Actions with state committed back to the repo to avoid duplicates.

---

## 2. Quick start (local)

```bash
git clone <your-repo-url>
cd job-alert
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt          # runtime only
# pip install -r requirements-dev.txt    # + pytest, for running the test suite
cp .env.example .env
# Edit .env: set DISCORD_WEBHOOK_URL to your webhook
python main.py validate-config
python main.py test-discord
python main.py run --dry-run --verbose
python main.py run
```

Run the tests with `pip install -r requirements-dev.txt && pytest`. CI installs
`requirements.txt` only, since the workflow runs the bot rather than the suite.

---

## 3. GitHub Actions setup

1. Push this repo to GitHub. **Use a public repo:** Actions minutes are unlimited and free on public repos, while a private repo bills every run against a 2,000 min/month allowance — at a 15-minute cron (~96 runs/day, ~6 min each) that allowance is gone in about three days.
2. Go to repo **Settings → Secrets and variables → Actions → New repository secret**
3. Name: `DISCORD_WEBHOOK_URL`, Value: your Discord webhook URL
4. Go to **Actions** tab → enable workflows if prompted
5. Click **"Job Alerts" → "Run workflow"** (first manual run — this will silent-backfill)
6. After first run, state is committed. Cron runs every ~15 minutes automatically.

> **Note:** GitHub free-tier cron can drift 5–15 minutes during peak hours. Alerts are **near real-time**, not instant.

---

## 4. CLI reference

```
python main.py run                          # one cycle, exits
python main.py run --dry-run                # no Discord, no state writes
python main.py run --dry-run --verbose      # + detailed per-company output
python main.py run --company Micron         # debug one adapter only
python main.py run --firehose-first-run     # send all current matches (first run)
python main.py run --summary-first-run      # send one summary embed (first run)
python main.py daemon                       # local long-running loop
python main.py validate-config             # check config + env vars
python main.py test-discord                # send test embed to verify webhook
```

---

## 5. How adapters work

Each company uses one adapter class in `src/adapters/`. The adapter's `fetch()` yields normalized `Job` objects. The filtering pipeline then decides which jobs match and which to alert on. To swap out a company's adapter, change the `adapter:` field in `companies.yaml` — no Python code changes needed.

**Current adapters:** workday (5 companies), smartrecruiters (2), lever (1), oracle_careers (1), amazon_jobs (1), apple_jobs (1), microsoft_research (1) — all enabled; plus phenom_people (1) and generic_html (1), both currently disabled (section 12).

`eightfold` and `eightfold_playwright` adapters are implemented, registered and tested, but no company currently uses them.

> **Note:** Snowflake, Microsoft Research, and Applied Digital use SPA-based sites that are difficult to scrape without a browser. These adapters return empty results until the sites expose a stable public API. The bot will not error out for these — it logs a warning and continues.

---

## 6. Adding / editing companies

To add a new company:

1. Find which career platform they use (Workday, Lever, Greenhouse, etc.)
2. Add an entry to `companies.yaml`:
   ```yaml
   - name: NewCompany
     adapter: workday   # or lever, smartrecruiters, etc.
     enabled: true
     config:
       base_url: https://newcompany.wd1.myworkdayjobs.com
       tenant: newcompany
       site: External
   ```
3. Run `python main.py validate-config` to check
4. Run `python main.py run --company NewCompany --dry-run --verbose` to test
5. Push to GitHub

To disable a company without removing it:
```yaml
- name: Micron
  enabled: false   # temporarily disabled
  ...
```

To add a platform not yet supported: create a new adapter in `src/adapters/yournew.py` extending `BaseAdapter`, register it in `src/adapters/__init__.py`, and reference it in `companies.yaml`.

---

## 7. Per-company keyword overrides

Each company supports optional overrides that merge with global filters:

```yaml
- name: Amazon
  adapter: amazon_jobs
  enabled: true
  extra_include_keywords:
    - "apprentice"
    - "rotational"
  extra_exclude_keywords:
    - "senior"
    - "principal"
  extra_preferred_locations:
    - "Nashville"
  config:
    ...
```

---

## 8. Resetting state

**Locally:**
```bash
rm state/seen_jobs.json
python main.py run   # silent backfill again
```

Or use `--firehose-first-run` to get all current matches sent to Discord.

**On GitHub:**
- Delete or edit `state/seen_jobs.json` via the GitHub web UI (or push a reset from local)
- The next cron run will treat it as a first run (silent backfill by default)

---

## 9. Discord webhook hygiene

To regenerate your webhook:

1. Discord → Server Settings → Integrations → Webhooks
2. Click your webhook → Edit → "Regenerate" or delete and create a new one
3. Update your local `.env` file
4. Update the GitHub Actions secret (**Settings → Secrets and variables → Actions → DISCORD_WEBHOOK_URL → Update**)

> **Never commit your real webhook URL** — `.env` is gitignored, `.env.example` has a placeholder only.

---

## 10. Cron drift caveat

GitHub Actions free-tier cron runs are queued at the scheduled time but may start 5–15 minutes late during peak hours. Alerts are **near real-time** (roughly every 15–30 minutes in practice), not instant.

---

## 11. Playwright — JavaScript-Rendered Career Sites

Some career sites are JavaScript-rendered SPAs. The hybrid approach boots the SPA
once with a headless Chromium browser to capture session cookies and/or XHR responses,
then uses the normal HTTP client for pagination.

**Currently enabled:** No browser-enabled adapters are active. Snowflake (`phenom_people`
adapter) is disabled pending a solution for its headless-hostile SPA. See section 13.

### Local setup

```bash
# Step 1: Python package (already in requirements.txt)
pip install -r requirements.txt

# Step 2: Chromium binary (only needed to run browser-enabled adapters)
python -m playwright install chromium
```

The Chromium binary is only needed in environments where a browser-enabled adapter is
active. When all browser adapters are disabled, no browser is ever started.

### Debug artifacts

If the browser bootstrap fails (timeout, anti-bot block, network error),
artifacts are saved to:

```
debug_artifacts/<Company>/<timestamp>/
├── screenshot.png     # page state at failure
├── page.html          # DOM dump (capped at 1 MB)
└── error.txt          # exception type + message
```

The `debug_artifacts/` directory is gitignored and never committed.

### Adding more Playwright adapters (future)

1. Extend `BaseAdapter` and use `BrowserClient` from `src/browser.py` for the
   bootstrap session (`bootstrap_session`) and `evaluate_fetch` for in-page API calls.
2. Register in `src/adapters/__init__.py`.
3. Set `use_playwright: true` in the company's `config` block in `companies.yaml`.

---

## 12. Known disabled / limited companies

| Company | Adapter | Status | Reason |
|---|---|---|---|
| Snowflake | `phenom_people` | Disabled | Phenom People SPA: headless automation can't trigger `searchJobs` API; `evaluate_fetch` is CORS-blocked; direct API calls require session cookies from browser handshake |
| Applied Digital | `generic_html` | Disabled | Careers page embeds an ADP Workforce Now JS-rendered portal (`<recruitment-current-openings>`); no static job cards or public JSON endpoint available; could be re-enabled with a dedicated `adp_workforce_now` Playwright adapter |
| Oracle | `oracle_careers` | Enabled (returns 0) | Oracle HCM API (`recruitingCEJobRequisitions`) is auth-gated; returns empty results for anonymous requests; needs a JS session handshake to return data |
| Microsoft Research | `microsoft_research` | Enabled (returns 0) | Eightfold API returns HTTP 403 for unauthenticated requests; HTML fallback is a fully JS-rendered SPA; both paths blocked |
| Plaid | `lever` | Enabled (returns 0) | Adapter is healthy; Plaid currently has no open roles listed on Lever (hiring freeze or slow period) |

---

## 13. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No Discord messages after setup | Webhook URL not set | Check `.env` / GitHub secret |
| Duplicate alerts | State file deleted or corrupted | Run `--dry-run` first, check `state/seen_jobs.json` |
| Company X never alerts | Adapter hitting auth/SPA wall | Check logs; some sites (Snowflake, MSR) require browser |
| Discord 429 errors | Too many alerts at once | Bot throttles to 4/sec; cap is 25/run |
| GitHub Actions fails with auth error | Missing `permissions: contents: write` | Check `.github/workflows/job-alerts.yml` |
| State file merge conflict on Actions | Two concurrent runs | `concurrency: group: job-alerts` prevents this |
| `validate-config` shows no adapter warnings | Expected when every configured adapter resolves | Check `src/adapters/__init__.py` imports |
| Run killed at 20 minutes | A step hung — usually `playwright install` stalling on an apt mirror | Expected safety behaviour; the job caps at `timeout-minutes: 20` and the install retries 3× before failing |
