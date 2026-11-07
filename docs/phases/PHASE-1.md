# Phase 1 executable contract — new-grad-only + network-priority alerts

**User-facing release:** Jobbie 2.1. **At foundation creation: NOT IMPLEMENTED.**
**Scope:** existing 13 enabled monitored career-site entries only, no new providers, no AI, no candidate PDFs, no Discord slash commands, no Cloudflare, no external email, no private storage. Keep legacy Python webhook + state/CLI available. Three ordered PRs P1-A/P1-B/P1-C. Do not skip live evidence.

## Exact before-state (RECONFIRM on HEAD)
- `companies.yaml` has 15 configured, 13 enabled, 2 disabled. `internship_only: false` but early-career keywords still include internship/co-op/student. Apple and Amazon still query internship sources. ``src/filtering.py` has raw-text rules with possible false positive/negative classification.
- Existing functions: `apply_filter_pipeline` and `label_job`; `Job.role_type` frozen enum; `src/notifier.py` publishes embeds; `src/storage.py` v2 first-seen/alerted state; workflow scheduled 15m but observed many hours between runs. Refactor safely.
- Network original list EXACT names in `docs/PRODUCT.md`. Do not include inactive Snowflake/Applied Digital as network-priority by default. `Microsoft Research` and `Microsoft` are two monitored entries, one wider company family, dedup apply URLs.

## Explicit policy / sample role matrix
Eligible to individual-alert if there is positive evidence of TECH role and full-time/early career with no disqualifier:
- "Software Engineer, New Grad" full-time US / no conflicting dates -> eligible.
- "Software Engineer I" with 0-2 yrs and full-time US -> eligible.
- "University Graduate 2027" with explicit eligible Dec 2026 graduating range -> eligible.
- "Junior Backend Engineer" 0-2 yrs full-time US -> eligible.
- Applied AI, SWE, full-stack, FDE 0-2 yrs (real early-career) -> eligible.
Needs review (not confidently eligible):
- General "Software Engineer" with no level or required experience, even if the description mentions interns in a different sentence.
- 2027 cohort with NO actual graduation eligibility window.
- "Engineer II" with unspecified years, 3 years required, or 0-2 years but contradictory levels.
- Unknown work authorization, role type or location; salary missing does NOT itself trigger review.
Excluded from job alerts:
- Explicit "Summer 2027 Software Engineer Intern", "Co-op", student placement.
- Senior/Staff/Principal/Lead/Director/Manager engineering roles when titles indicate seniority, or >=4 required years with no clear junior alternative.
- Non-US ONLY positions, required US citizenship/active clearance, or explicit degree/graduation requirement the owner doesn't meet.
- Explicit contract/part-time-only when permanent full-time required.
- Nontechnical sales/HR/operations role even if description mentions Python. Exclude based on TITLE/structured department/duties, not incidental words in a technical job description.
Need review tier must appear in a *bounded, labeled summary* or review log, never disappear silently or be announced as a confirmed fit. Do not suppress legitimate US option because same posting also lists Canada.

## Ordered implementation work

### P1-A: eligibility engine and fixture corpus
1. Capture base branch SHA, tests, config/workflow and small representative dry-run diagnostic. Never send test webhook unless explicitly permitted/verified safe.
2. Introduce `src/eligibility.py` pure deterministic classifier: `employment_type`, `career_level`, `eligibility`, stable reasons + evidence extraction from explicit title, structured fields and relevant requirement sentences. Do not use a word found anywhere in raw_text to classify role; distinguish "internship preferred" in job history vs internship job. Preserve existing Job constructor/adapter return types and CLI, add an adapter-normalization helper only as needed.
3. Update `src/filtering.py` to invoke eligibility and location logic, preserving legacy compatibility and reason logs. Prevent inappropriate "sales" / "masters" / "PhD" mention excludes and generic technology mentions in nontech postings. Parse multiple locations individually; distinguish US remote vs unspecified remote. Unknown posted date is not automatically "posted today".
4. Restrict Phase 1 TECH roles to SWE, backend, full-stack, product engineering, AI/FDE, justified junior data/ML; generic product/program manager is not a default engineering alert.
5. Change `companies.yaml` `filters` to explicitly select `new_grad_full_time` while preserving ability to dry-run legacy mode for rollback; mark old `internship_only` deprecated or translate it with warnings, never silently allow interns.
6. Disable APPLE internship source and AMAZON internship-only query in config without removing adapters or tests. Do not modify disabled companies or bypass employer authentication.
7. Add table-driven synthetic fixtures under `tests/fixtures` and `tests/test_eligibility.py`: at least 25 adversarial cases spanning the matrix, semantically ambiguous wording, grad dates, US citizenship vs green card, 2027 class, PhD preferred vs required, salary unknown, foreign-city names, identical title distinct reqs. Preserve all existing tests.
8. Output include/exclude/review summary counts by company in `--dry-run --verbose`; run tests and compare baseline.

**P1-A gate:** 100% exclusion of explicit internship/senior/citizenship-only fixture roles; all clearly eligible examples included; uncertain cases `needs_review` with reason; no regression in existing unit suite; no public state mutation on `--dry-run`. Do not claim real adapter coverage yet.

### P1-B: immutable original cohort + webhook formatting
1. Add `network_priority: true` and `cohort: original_2026_11_04` to exactly 13 enabled source entries in `companies.yaml`. Add `referral_status: unconfirmed` for each. Disabled entries remain false/not flagged. Validate a new discovered source defaults to no marker.
2. Keep location priority (`Job.priority`) separate from network/referral metadata. If duplicates across Microsoft and Microsoft Research, preserve source records but display one normalized employer with a network badge.
3. Add precise notifier contract: prefix `⭐ NETWORK PRIORITY` for original 13, `DISCOVERED` for future; show role/full-time verification category, company, city/location, direct URL, posted_at when source-known OR detected_at labeled as such; source attribution, confidence/review label; salary only when verified. Do not invent a salary, exact job-age, referral contact or referral status.
4. Guard against Discord embed limits, rate limits, disallowed @mentions, untrusted Markdown/control chars, bad/empty URL, and sanitization of public text.
5. Create `tests/test_network.py` and notifier snapshot/regression tests for 13 flagged + 2 unflagged, duplicate source, unconfirmed referral, unknown dates and long titles. Keep existing webhook transport and max-alert cap.

**P1-B gate:** explicit 13/2 flag assertions, zero assertion of actual referral, readable embeds and no duplicate sends in fixtures. Network badges do not appear on disabled/added companies.

### P1-C: state migration, schedule observability, cutover
1. Existing v2 `state/seen_jobs.json` MUST be retained and backed up before any migration. Use additive versioned state fields; do not reset all seen jobs.
2. Implement ``policy_version=2026-11-newgrad-v1` migration marker and a safe reclassification/backfill preview. Re-examine *currently available, source-verified* postings to find eligible opportunities from the last 7 days (when posted_at is credible; if unknown, use observed_at accurately). Cap summary at 10 items/first run with total count and direct links where possible. Do not firehose every old item. Track migration completed exactly once, and no summary from failed fetch.
3. Default subsequent runs notify only newly discovered/reopened verified eligible jobs, once per canonical URL/requisition across sources/runs where possible. Need-review positions should be recorded and summarized no more than daily, capped; never silently erased. Preserve old state and detect missing/corrupt state instead of treating total loss as a legitimate fresh run.
4. Add run heartbeat/diagnostics: configured cron, actual start/finish, adapter count, accepted/review/excluded, actual alert success/failure, per-source zero/failed distinction, last-success age, scheduler gaps. Structured logs no secrets. If Actions is late, report elapsed age without promising exact 15m latency.
5. Check GitHub Actions resource and time limits; keep existing concurrency and serial state commit behavior. Fix identified scheduler/config problems without requiring a new external runtime. Provide manual `workflow_dispatch` and dry-run playbook.
6. Add `docs/OPERATIONS.md` Phase 1 release addendum and update root `README.md` 15/13 reality and new commands; no false live claims.
7. Verify full `pytest`, `validate-config`, targeted live adapter read-only dry-run, no side effects. Run an approved live webhook smoke and an actual workflow run if secrets are configured; record run URL and timestamp. Recheck GitHub Actions schedule after deployment; if scheduled gap remains, state accurately and give fallback.
8. Rollback: feature flag returns to previous stable notifier/filter while preserving state; migration marker remains auditable; no deleting state or mass re-alerting.

**P1-C gate:** dry-run has no state/webhook mutation; controlled first-run backfill not spam; duplicate suppression across runs; no loss of existing alert state; real verified job alert to Discord when credentials permitted; live Actions run success (and observed schedule latency caveat).

## Tests / evidence artifacts required
- Regression table: 25+ eligibility fixtures, observed expected/result with reason codes.
- 13 original/2 disabled config snapshot with flags.
- Before-and-after job counts by enabled adapter using same source sample; do NOT call "missing postings" healthy without source verification.
- Discord payload snapshot showing NETWORK PRIORITY / referral UNCONFIRMED and no fabricated salary/date.
- State-migration fixture using copy of redacted prior v2 state, repeat-run idempotency, cap behavior, reset/corruption handling, revert test.
- Exact test commands/output and GitHub Actions run link; failures/blocked reasons.
- No screenshots of private webhooks, personal resumes, token-bearing URLs.

## Phase 1 release decision / stop rules
Release only when P1-A/B/C merged AND phase smoke verified. If provider blocks an adapter, mark degraded, keep other sources, never bypass auth. If webhook secret or workflow permissions absent, stop at `BLOCKED_LIVE` with exact manual setup, not a fictional success. If scheduled runs remain sparse, transparently call service best-effort, not real-time. Do NOT commence Phase 2 before Phase 1 is demonstrably usable.

## Verification and Sign-Off Evidence (Jobbie 2.1 Release)
- **Release Status:** Complete & Verified
- **Sequential PRs Merged to `main`:**
  1. **P1-A (Eligibility Engine & Fixtures):**
     - PR: [#12](https://github.com/KanujVerma/jobbie/pull/12)
     - Squash commit: `476975d043600e9d467c4c7e46f4d4c2e1a60a65`
     - Added pure deterministic classifier in `src/eligibility.py`, 30-case adversarial matrix `tests/fixtures/eligibility_matrix.json`, updated `src/filtering.py` with multi-location parsing and `mode: new_grad_full_time` filter.
  2. **P1-B (Immutable Cohort & Webhook Formatting):**
     - PR: [#13](https://github.com/KanujVerma/jobbie/pull/13)
     - Squash commit: `ebca5eadc1cdff463564e972bd7ea0c648f45e63`
     - Configured 13 enabled employers with `network_priority: true`, `cohort: original_2026_11_04`, and `referral_status: unconfirmed`. Preserved 2 disabled companies unflagged. Formatted gold `⭐ NETWORK PRIORITY` embeds with markdown/mention sanitization and verified salary conditioning.
  3. **P1-C (State Migration, URL Deduplication, Scheduler Observability):**
     - PR: [#14](https://github.com/KanujVerma/jobbie/pull/14)
     - Squash commit: `9f94b568bf422509121775a6c1a84f3c9597792e`
     - Upgraded state schema with `policy_version: 2026-11-newgrad-v1`, `StateCorruptionError`, cross-run URL deduplication, 7-day bounded backfill summary, daily review digest throttling, run diagnostics, and scheduler gap logging (>45m).
- **Test Evidence:**
  - 592 tests passing cleanly (`pytest`) across all unit and integration test suites.
  - `python main.py validate-config` verified valid.
  - Live adapter dry-run read verified with zero mutations to `state/seen_jobs.json`.
- **Live Workflow Run Evidence:**
  - Triggered via `workflow_dispatch` on `main`: [Actions Run 41915003368](https://github.com/KanujVerma/jobbie/actions/runs/41915003368).
  - Schedule reality caveat: Actions schedule drift can exceed nominal 15m intervals; gap detection flags runs exceeding 45m without promising sub-15m real-time polling.
- **Rollback Protocol:**
  - Switch `filters.mode: legacy` in `companies.yaml`. State retains backward compatibility without wiping seen jobs or causing alert storms.

## Phase 1D: Quality and Release Hardening (Jobbie 2.1 Final Release)
- **Release Status:** Complete & Verified
- **Sequential PRs Merged to `main`:**
  1. **P1-D1 (Classification and Coverage):**
     - PR: [#15](https://github.com/KanujVerma/jobbie/pull/15)
     - Squash commit: `e1608cf6223d21ef7ebaf2ce565c0e96f0159970`
     - Corrected level code classifications (E3/IC1/L1/P1 -> new_grad; E4+/L4+/IC3+ -> senior/excluded; E3/L3 with ambiguous exp -> needs_review).
     - Disambiguated Workday multi-locations with composite `location` and `additionalLocations` parsing.
     - Resolved geographic disambiguation (Georgia state vs Georgia country, London OH vs London UK, Paris TX vs Paris France).
  2. **P1-D2 (State and Delivery Correctness):**
     - PR: [#16](https://github.com/KanujVerma/jobbie/pull/16)
     - Squash commit: `c9acd1ce69a6866ec88fecab76f7f022718797f1`
     - Decoupled 7-day backfill freshness from standard 48-hour individual alert threshold, isolating historical postings from consuming the alert cap.
     - Enforced confirmed delivery invariant (`alerted=True` only when Discord webhook succeeds).
     - Added `--rerun-backfill` CLI flag for safe reruns without resetting state.
     - Re-raised Lever adapter HTTP errors (404 classified as failed rather than healthy zero).
     - Review queue cleanup and prioritization (scoring canonical 13 network priority, early career keywords, tech hubs, and preserving classification evidence).
  3. **P1-D3 (Automated Verification and Release):**
     - PR: [#17](https://github.com/KanujVerma/jobbie/pull/17)
     - Squash commit: `b920f706d20b94a45d02261ed97ec911d0d85094`
     - Added GitHub Actions CI workflow in `.github/workflows/test.yml` running pytest and config validation on PRs and pushes to main.
     - CI Run Evidence: [Actions Run 41953363672](https://github.com/KanujVerma/jobbie/actions/runs/41953363672) passing on commit `b920f70` on `main`.
     - Measured actual GitHub Actions cron delivery gaps on production runs:
       - Run 41881777832 (`2026-11-04T17:55:22Z`) to Run 41933684385 (`2026-11-04T23:26:08Z`): 5h 30m gap.
       - Run 41810957728 (`2026-11-04T09:57:20Z`) to Run 41881777832 (`2026-11-04T17:55:22Z`): 7h 58m gap.
       - Run 41762686190 (`2026-11-04T02:44:24Z`) to Run 41810957728 (`2026-11-04T09:57:20Z`): 7h 13m gap.
       - Verification: Confirms public Actions runner scheduling drift can delay nominal 15m intervals up to ~8 hours during low priority scheduling. Confirms `compute_run_diagnostics()` in `src/health.py` accurately identifies `scheduler_gap_detected=True` when elapsed interval exceeds 45m (3x cadence), preventing false-positive operational alerts while transparently recording scheduler health.
     - Post-merge operational live dry-run on `main` verified with zero state or alert mutation across all 13 canonical adapters (`Run heartbeat: duration=486.08s, gap=9383.33s, scheduler_gap=True, adapters=12/13 (zero=2), matched=2, review=264, excluded=9052, alerted=0`).
- **Test Suite Evidence:** 654 tests passing cleanly synchronously (`pytest` in 32.48s).
- **Configuration Validation:** `python main.py validate-config` verified clean on `main`.
- **Release Sign-Off:** Phase 1D is fully verified, operational, and all three sequential PRs are merged to `main`.




## P1-E targeted correctness patch (2026-11-05)
Issue discovered after P1D: experience extraction chose the lowest unrelated tenure number, which can treat a master's/PhD or specific-tool pathway as satisfying a bachelor's minimum. A seven-day backfill summary could acknowledge more jobs than it displayed. The owner requested primary-assistant code delivery, with Gemini used for checking only when necessary.

- Implementation PR: [#18](https://github.com/KanujVerma/jobbie/pull/18) (status must be read from GitHub; do not infer merged from this text).
- Source: `src/experience.py` (conservative bachelor's-path requirements), `src/backfill.py` (bounded, resumable, delivered-link-only ACK), plus integration and adversarial tests.
- Required gates: passing automated tests on exact head, independent review, proof no unseen backfill candidate is marked alerted, and real employer JD spot-check for the three historical Intel alerts. Do not change public production state or trigger `--rerun-backfill` without safe preview/approval.
- Previous "Complete & Verified" claims describe P1D at its earlier SHA, not automatic approval of this corrective PR. Phase 2 is blocked until P1E passes.
