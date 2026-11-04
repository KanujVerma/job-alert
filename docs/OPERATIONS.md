# Operations, baseline, migration and incident runbook

**Current (legacy) app only until Phase 1 is released.** Future/cloud features are not active in this repo merely because they are documented.

## Pre-flight each coding session
1. Confirm repo actual identity with `gh repo view` or GitHub API, default branch and HEAD; rename status at `docs/RENAME.md`.
2. Check open PRs and recent workflow runs; state auto-commits can move main during work.
3. Read `AGENTS.md`, `docs/DECISIONS.md`, current phase, tests, `companies.yaml`, workflow, active adapters.
4. Reproduce relevant issue using dry-run fixture, not live outgoing traffic. Record exactly which tools/credentials are available; never guess.
5. Work on branch, use commit SHA lease or rebase before merge if main advanced.

## Current local commands
`python3 -m venv .venv`
`source .venv/bin/activate`
`pip install -r requirements-dev.txt`
`python main.py validate-config`
`python main.py needs-browser`
`python main.py run --dry-run --verbose`
`python main.py run --company Microsoft --dry-run --verbose`
`pytest -q`

Run `python main.py test-discord` ONLY with owner's configured webhook/approved test destination. It posts an actual Discord message. Use real `python main.py run` only after first-run/backfill behavior and state backup are understood. Never paste webhook URL in terminal logs/issues.

## Existing GitHub Actions
Workflow path `.github/workflows/job-alerts.yml`; configured cron `*/15 * * * *`; workflow_dispatch manual; existing group `job-alerts` serializes runs; logs may contain untrusted web content. Check actual run start/finish gaps. The old bot was observed to run hours apart; do not label 15-minute polling guaranteed. Track last success time, adapter duration, missed runs and notification failures.

## Phase 1 deployment protocol
1. Snapshot latest `main` SHA and copy `state/seen_jobs.json` to a private safe backup (do not create public `.bak` copy in repo).
2. Merge P1-A tests, then P1-B embeds, then P1-C state/health. Keep old modes/feature flag for rollback.
3. Produce `--dry-run` output and verify original `state/seen_jobs.json` hash unchanged. Check 13 flags, reason matrix, controlled backfill preview and accurate posted_at vs first_seen.
4. Verify per-company live adapter reads (allowed/no auth bypass) and a single safe webhook smoke, then manually trigger workflow if secrets are configured. Record run URL, screenshot only if contains no private data/URLs.
5. Observe at least one scheduled run's actual timestamp before labeling LIVE_VERIFIED; note remaining gap/uncertainty. Inspect failed adapter vs genuine zero result.
6. Update `docs/phases/PHASE-1.md` with evidence and phase status. If missing live credentials, mark `BLOCKED_LIVE` with exact setup; do not emit imaginary sent message.
7. Rollback via old classifier/notifier flag and restore last known good code; preserve migrated audit/seen state, no full state deletion.

## State and backfill
- Existing public v2 seen state holds historical IDs and alert status. Never reset it to "force" new-grad alerts; this causes spam.
- New-grad policy migration should be additive, idempotent, bounded (default 7-day verified jobs, up to 10 in one summary) and may record a separate policy marker.
- Unknown posted timestamp must be labeled `first observed`, not `posted`.
- Empty state due to corruption should fail safe with logged diagnostic and request manual remediation, not mass send.

## Failures and response
- Adapter 429/timeouts: bounded exponential backoff, record degraded. Other adapters continue.
- One source empty: health observes silence, not automatically "broken" or "hiring freeze".
- GitHub Actions delayed: report observed gap, provide manual run; preserve job history. Never invent scheduler uptime.
- Discord 429: respect Retry-After, bounded retry, do not mark alerted until success; on ambiguous response log unknown instead of blind duplicate.
- State commit conflict: rebase against latest origin, verify state merged correctly and dedup idempotence; don't force push main or overwrite concurrent run.
- Secrets compromised: stop workflow/sending, rotate at provider, update Actions secret, redact reports.
- Unexpected spend: disable provider, inspect quotas, maintain old no-AI scraper.

## Rename migration
Follow `RENAME.md` after owner performs GitHub Settings rename; do not create replacement repo. Verify actual repo ID and job workflow, update local origin and external references. The planned target name itself is `jobbie`.

## Phase 1 Release Addendum (Jobbie 2.1)
- **Release Status:** Jobbie 2.1 is deployed.
- **Audience & Invariants:**
  - Targeted exclusively at single owner (December 2026 CS graduate seeking full-time US software engineering roles starting January 2027 onward).
  - Internship and co-op postings are 100% excluded.
  - Exactly 13 enabled employer entries in `companies.yaml` carry permanent `network_priority: true`, `cohort: original_2026_11_04`, and `referral_status: unconfirmed`.
  - 2 disabled companies (`Snowflake`, `Applied Digital`) remain unflagged.
  - Zero assumed referrals; unverified salaries remain unmentioned; location priority (`Job.priority`) remains separate from network priority.
- **State Schema & Migration (`2026-11-newgrad-v1`):**
  - Version 2 format is preserved with additive fields: `policy_version`, `migrations`, `alerted_urls`, `review_queue`, and `heartbeat_history`.
  - State corruption detection: `StateCorruptionError` is raised on malformed state files, failing safe to prevent mass re-alert storms.
  - Bounded Backfill: First run under `2026-11-newgrad-v1` identifies source-verified postings from the last 7 days and delivers a single Discord summary embed capped at 10 items instead of firehosing individual alerts.
  - Cross-Run URL Deduplication: Normalized URLs (stripped of tracking tokens and fragments) are tracked in `state["alerted_urls"]` to suppress duplicate alerts across multiple sources (e.g. Microsoft and Microsoft Research) and across subsequent runs.
  - Review Queue & Daily Digest: Ambiguous roles requiring review are stored in `state["review_queue"]` and batched into a daily summary digest (capped at 10) instead of being dropped silently.
- **Scheduler Reality & Cron Drift:**
  - GitHub Actions runs the workflow on `cron: '*/15 * * * *'`.
  - Public repository runners experience significant queue latency; actual intervals between runs regularly stretch from 15 minutes to multiple hours during peak GitHub Actions load.
  - Run heartbeats record start/finish, elapsed duration, and detect scheduler gaps (>45 minutes), logging clear warnings without promising sub-15-minute real-time latency.
  - Manual Trigger: Trigger an immediate scrape pass using GitHub Actions UI or `gh workflow run job-alerts.yml`.
- **Rollback Protocol:**
  - Set `filters: { mode: "legacy" }` in `companies.yaml`.
  - The system will immediately revert to legacy keyword/internship filtering.
  - State remains backward-compatible: seen jobs and migration metadata are preserved without requiring state deletion or re-alerting.

## Subsequent phase releases
Every new provider/feature behind flag and isolated from legacy polling. P2 catalogue dual-write and 72h shadow; P3 command+upload authorized test; P4 owner-approved sample documents; P5 exact approved outbound test; P6 confirmed application/reminder. Before cutover, validate free quota/pricing and rollback. Update docs from actual deployment, not hypothetical diagrams.
