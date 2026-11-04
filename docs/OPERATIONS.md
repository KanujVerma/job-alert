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

## Subsequent phase releases
Every new provider/feature behind flag and isolated from legacy polling. P2 catalogue dual-write and 72h shadow; P3 command+upload authorized test; P4 owner-approved sample documents; P5 exact approved outbound test; P6 confirmed application/reminder. Before cutover, validate free quota/pricing and rollback. Update docs from actual deployment, not hypothetical diagrams.
