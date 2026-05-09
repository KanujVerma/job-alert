# job-alert

## 1. What it does

Monitors 14 company career sites every 15 minutes for U.S.-based internships, new-grad, and entry-level tech roles. Sends Discord webhook alerts when new postings are detected. Runs free on GitHub Actions with state committed back to the repo to avoid duplicates.

---

## 2. Quick start (local)

```bash
git clone <your-repo-url>
cd job-alert
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env
# Edit .env: set DISCORD_WEBHOOK_URL to your webhook
python main.py validate-config
python main.py test-discord
python main.py run --dry-run --verbose
python main.py run
```

---

## 3. GitHub Actions setup

1. Push this repo to GitHub (create a new private repo)
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

**Current adapters:** workday (5 companies), smartrecruiters (2), lever (1), oracle_careers (1), amazon_jobs (1), apple_jobs (1), eightfold (1), microsoft_research (1), generic_html (1).

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

## 11. Playwright — JavaScript-Rendered Career Sites (v2)

Some career sites are JavaScript-rendered SPAs that the plain `requests`-based
pipeline cannot authenticate. The **hybrid approach** boots the SPA once with
a headless Chromium browser to capture session cookies, then uses the normal
HTTP client for all subsequent JSON pagination.

**Currently enabled:** Snowflake only (`adapter: eightfold_playwright`).
Microsoft Research, Applied Digital, and Oracle are disabled pending separate plans.

### Local setup

```bash
# Step 1: Python package (already in requirements.txt)
pip install -r requirements.txt

# Step 2: Chromium binary (only needed to run browser-enabled adapters)
python -m playwright install chromium
```

The Python package is always installed. The Chromium binary is only needed
in environments where a browser-enabled adapter is active. If Snowflake is
disabled (`enabled: false` in `companies.yaml`), no browser is ever started.

### Running Snowflake locally

```bash
# Single-company dry run with verbose output
python main.py run --company Snowflake --dry-run --verbose
```

On success you will see output like:
```
Snowflake: fetched=40 matched=12 new=12 alerted=0
```

### Debug artifacts

If the browser bootstrap fails (timeout, anti-bot block, network error),
artifacts are saved to:

```
debug_artifacts/Snowflake/<timestamp>/
├── screenshot.png     # page state at failure
├── page.html          # DOM dump (capped at 1 MB)
└── error.txt          # exception type + message
```

The `debug_artifacts/` directory is gitignored and never committed.

### Disabling Snowflake

Set `enabled: false` in `companies.yaml`:

```yaml
- name: Snowflake
  adapter: eightfold_playwright
  enabled: false          # ← disable here; Chromium will not start
  config:
    ...
```

### Adding more Playwright adapters (future)

1. Set `use_playwright: true` in the company's `config` block.
2. Create `src/adapters/<name>_playwright.py`, extending `BaseAdapter` with
   `self.browser` for the bootstrap session and `self.http` for API calls.
3. Register in `src/adapters/__init__.py`.
4. See `src/adapters/eightfold_playwright.py` as the reference implementation.

---

## 12. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| No Discord messages after setup | Webhook URL not set | Check `.env` / GitHub secret |
| Duplicate alerts | State file deleted or corrupted | Run `--dry-run` first, check `state/seen_jobs.json` |
| Company X never alerts | Adapter hitting auth/SPA wall | Check logs; some sites (Snowflake, MSR) require browser |
| Discord 429 errors | Too many alerts at once | Bot throttles to 4/sec; cap is 25/run |
| GitHub Actions fails with auth error | Missing `permissions: contents: write` | Check `.github/workflows/job-alerts.yml` |
| State file merge conflict on Actions | Two concurrent runs | `concurrency: group: job-alerts` prevents this |
| `validate-config` shows no adapter warnings | Normal in Phase 1; should resolve after Phase 2+ | Check `src/adapters/__init__.py` imports |
