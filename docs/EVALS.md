# Verification matrix and release gates

No fabricated benchmark numbers, simulated "live" claims or implicit passing thresholds. Store exact fixtures, test commands, GitHub run URLs, git SHA, timestamp and evaluation owner in each release PR.

## Evidence levels
- `SPECIFIED`: docs only.
- `IMPLEMENTED`: code exists at exact SHA.
- `UNIT_TESTED`: relevant deterministic tests pass at that SHA.
- `INTEGRATION_TESTED`: local or CI integration behavior verified against representative systems/data.
- `LIVE_VERIFIED`: authorized real Discord/source/provider test observed, with link/log and environment.
- `RELEASED`: all required gates complete and deployed; fallback still viable.
A green synthetic fixture never promotes anything to `LIVE_VERIFIED`.

## Phase 1 critical fixture matrix
At least 25 deterministic table-driven cases with expected status/reason:
(1) explicit full-time New Grad 2026, (2) 2027 cohort allowing December 2026, (3) 2027 cohort unspecified, (4) SWE I 0-2 yrs, (5) Junior Backend 0-2 yrs, (6) general SWE unknown years, (7) SWE II ambiguous, (8) SWE 3 years, (9) senior 5 years, (10) staff, (11) explicit intern title, (12) co-op, (13) internship mention in generic team description but full-time SWE I, (14) "sales analytics" nontech, (15) SWE working on sales features, (16) PhD preferred, (17) PhD required, (18) master's preferred, (19) masters degree required, (20) US citizen REQUIRED, (21) sponsorship unavailable but candidate does not need it, (22) San Jose CA and Toronto mixed, (23) Toronto-only, (24) generic Remote with no US scope, (25) US remote explicitly, (26) missing posted date, (27) SF $100k, (28) undisclosed salary, (29) same MS req via Microsoft Research, (30) identical title with different official req IDs.
Qualify 100% of clear disqualifiers excluded and 100% of clearly eligible fixtures included. All ambiguous statuses `needs_review`. Never infer citizenship.

## Phase 1 acceptance
- All `pytest` green (or exact pre-existing failures explained, not silently ignored); `validate-config` green; dry-run state SHA before/after equal.
- 13 original flags true, 2 disabled not flagged, added test source not flagged, no assertion of actual referral.
- Bounded migration summary, idempotent rerun, no duplicate alert storm, no private data in source/log.
- Real source read-only fetch with correct job URL; a real authorized webhook smoke plus Actions run evidence before LIVE_VERIFIED. Scheduling gaps measured; user told observed latency.
- Shadow compare classified jobs against baseline and sampled manual labels. Record precision/recall; do not invent improvement numbers.

## Phase 2 acceptance
Live source ATS smoke; source rights documented; minimum 30 dedup/closure/adversarial fixtures; 72h shadow count/duplicate comparison; canonical employer and original 13 flags retained.

## Phase 3 acceptance
Valid and invalid signed Discord requests, replay, unauthorized owner access and privacy tests. At least 40 manually labeled job matches with per-class confusion, missing-info handling; confirmed vs proposed candidate facts; private repo read-only and scope enforcement; no public storage leak.

## Phase 4 acceptance
See `RESUME_TAILORING.md`: 24 frozen jobs, zero accepted invented numbers/ownership/title/dates; 12 owner-reviewed samples with >=10 rated improved and at least as natural; all generated PDF/DOCX pass text, link, page and preserved-field checks. A single severe hallucination fails release.

## Phase 5 acceptance
20 sample company facts with source citations; contact provenance verification; unauthorized send, mismatch, double click and ambiguous timeout tests; at least one OWNER-APPROVED test email with actual provider receipt. No auto LinkedIn sends.

## Phase 6 acceptance
Accurate immutable application state and attached exact resume; duplicate event handling, calendar/reminder idempotence, opt-out, private read, optional Gmail opt-in tests. User-confirmed status changes only.

## Cost/reliability/privacy gates (each phase)
- $0 recurring: explicitly record provider tier/limits, observed usage, API rate/429 handling, disabled paid fallback. Cannot guarantee free if usage charges may be incurred; requires spend cap or not deployed.
- No secrets/private documents/family contact data published to GitHub or Discord public channels.
- Source and recipient provenance, retry/backoff, no duplicate external send and a rollback procedure.
- Regression across previously released phases.
- Do not claim uptime/SLA. Record actual delay distribution, missing checks, source errors and fallback behavior.

## Mandatory PR evidence template
`Base SHA:`, `Head SHA:`, `Files changed:`, `Reproduced behavior:`, `Tests (command / result):`, `Coverage (fixtures / live):`, `External source URLs/time:`, `Privacy review:`, `Known unknowns:`, `Rollout / rollback:`, `Codex review status / resolved findings:`, `Release gate status:`.

No PR merges solely because an LLM or README says tests passed.
