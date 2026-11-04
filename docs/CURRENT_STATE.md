# Verified baseline: legacy bot (inspection 2026-11-04)

This is a CODE INSPECTION snapshot, not a complete live test of every adapter. All features outside the observed inventory are PLANNED, not deployed.

## Repository and runtime
- Inspected repository: `KanujVerma/job-alert`, public, default branch `main`, at source snapshot `7b666e2557d923035a6edd64c8fa9a0012e95af1` (state-only commit). Repo rename to `jobbie` still unverified.
- Runtime: Python 3.12 via `.github/workflows/job-alerts.yml`; scheduled `*/15 * * * *` and manual `workflow_dispatch`; `concurrency: group: job-alerts`; 20 min top-level timeout and 14 min run-step timeout. Action commits `state/seen_jobs.json` back to main. Old cron observed to run HOURS apart despite configured cadence; investigate rather than claim real-time.
- User CLI in `main.py`: `validate-config`, `needs-browser`, `test-discord`, `run` (`--dry-run`, `--company`, `--verbose`, initial summary/firehose), `daemon`. Keep compatibility through phase 1.
- Dependencies: `requests`, `beautifulsoup4`, `PyYAML`, `python-dotenv`, `dateutil`, `playwright`; test suite under `tests/`. Use installed `requirements-dev.txt` for tests.
- Current notifications: outbound ONLY via Discord webhook, `src/notifier.py`. Cannot receive messages, slash commands, or resume attachments.
- Current state: `src/storage.py` v2, company-scoped seen-job IDs with first/last seen, alerted flag, prune TTL; public `state/seen_jobs.json` tracked in Git. No candidate or application database.
- `src/models.py` defines frozen Job with id, company, title, location, department, category, URL, source platform, posted/detected times, raw_text, role_type (internship, new-grad, entry-level, unknown), priority (preferred, normal), matched_keywords.
- `src/adapters/__init__.py` registers Workday, Lever, SmartRecruiters, Oracle Careers, Amazon, Apple, Microsoft Research, Eightfold variants, Phenom, generic HTML.

## Config reality
`companies.yaml` contains FIFTEEN entries: THIRTEEN enabled (Micron, Salesforce, CrowdStrike, Intel, Applied Materials, Western Digital, SanDisk, Plaid, Oracle, Microsoft Research, Microsoft, Amazon, Apple), TWO disabled (Snowflake, Applied Digital). Older `README.md` says 14 configured / 12 enabled and is stale.

`filters.internship_only` is already `false`. That does NOT implement a reliable new-grad mode: `early_career_keywords` still includes intern/internship/co-op/student, and `src/filtering.py` uses broad raw-text keyword checks. `label_job` can classify based on internship mention anywhere in description; title-only vs requirement-context parsing is missing. Some title filters are overly broad (e.g., "sales" anywhere in a SWE posting). Unknown locations pass through and some country checks use all raw text; mixed multi-location jobs need care.

## Known observed / documented gaps
- README per-company `extra_include_keywords` / `extra_exclude_keywords` example has no proven equivalent implementation in current search, so do not rely on it without code audit.
- Amazon `include_internship_search: true` and Apple `sources: internships` remain enabled. Phase 1 must stop internship-only fetches where safe; retain code and nonintern search.
- Microsoft and Microsoft Research overlap. Main.py dedupes by apply URL only WITHIN a single run; duplicate across runs/sources remains possible.
- Oracle, Plaid, SanDisk have documented empty/quiet cases; distinguish "zero jobs" from failed fetch. Snowflake and Applied Digital disabled for JavaScript/auth barriers. No unsupported bypass.
- Existing priority `preferred` means a preferred LOCATION, not a network/referral priority. Do not overload it.
- First-run silent backfill state exists; old seen state does not support a new-grad migration announcement. Need controlled, bounded backfill without reset.
- Missing posted date may pass freshness filter; unknown post date is not automatically a new posting.
- Current docs and workflow claim ~15 minute checks but actual recent schedule run timestamps are widely spaced. GitHub schedule cannot be assumed exact.
- Phase 1 must not weaken existing error handling, token-bucket Discord notification throttling, or adapter tests.

## What has NOT been verified by this documentation commit
- No actual fixture suite or live end-to-end Discord send was run as part of this documentation write.
- No new-grad filter implementation, extra sources, private storage, interactive Discord bot, GitHub evidence sync, resume tailoring, startup outreach, Gmail sending, or application tracker has been released.
- Exact latest posted jobs and referral availability are not known.
- Repository name has not been renamed here.

## Before next coding phase
Read `src/filtering.py`, `src/models.py`, `src/config.py`, `src/storage.py`, `src/notifier.py`, `main.py`, `companies.yaml`, the relevant adapter files, current tests, and latest Actions runs. Revalidate baseline HEAD, which will change because state auto-commits continue.
