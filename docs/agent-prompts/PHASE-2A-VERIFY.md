# Gemini: verify and finish existing Phase 2A PR #23

**This is a completion runbook, NOT a request to reimplement Phase 2A.**

Repository: `KanujVerma/jobbie`.
PR: https://github.com/KanujVerma/jobbie/pull/23
Branch: `feat/p2-a-public-job-boards`.
Read AGENTS.md; docs/STATUS.md, HANDOFF.md, implementation/P2-A.md,
phases/PHASE-2.md, sources/P2-A_PUBLIC_APIS.md, evidence/P2-A-VERIFICATION.md,
CONTRACTS.md, SECURITY.md, OPERATIONS.md and issues #20/#6.

## Completed work and precise evidence
Public Greenhouse/Ashby adapters, shared safe normalization, registry/config,
optional immutable Job fields, employment/description guardrails, accurate
published-date labels, review-queue source fields, 85 new regression tests,
disabled sample boards, metadata-only smoke CLI and read-only Actions workflow
are implemented. Original 727 tests remain: **812 pass**.

Reviewed source: `5e56bc668a6615002b5ac0fbe8592b2a84987162`.
- Unit/integration CI: https://github.com/KanujVerma/jobbie/actions/runs/42342377756
  (812 passed in 32.95s, Python 3.12.16).
- Live public read: https://github.com/KanujVerma/jobbie/actions/runs/42342377775
  (19 Greenhouse + 73 Ashby, all excluded by candidate classification,
  config/state hashes unchanged, no Discord sends).
- Codex summary: https://github.com/KanujVerma/jobbie/pull/23#issuecomment-6702690334
  completed with no findings at that source SHA.
- Durable receipt: docs/evidence/P2-A-live-2026-11-07.json. Its source_sha
  `00111df2b1a09be5b487723be8a0df1c5e79bffe` is GitHub's PR merge checkout
  (5e56bc6 into d98afe7), NOT a production merge/release commit.

Later documentation-only commits can change the PR HEAD. Compare source blobs
before deciding whether evidence still covers the code. If ANY functional code,
fixture or workflow changed after the reviewed source, rerun tests/live reads as
applicable and obtain an independent review of that new source. Never label an
old SHA's green checks as the latest SHA passing.

## 1. Exact checkout and safety audit
1. Read actual PR state/head/base/checks/reviews first. If merged already, skip
   duplicate implementation/merge and perform only post-merge verification.
2. `git fetch origin`; check `git status --short`. Do not discard local work.
3. If open: `git checkout feat/p2-a-public-job-boards`; `git pull --ff-only`.
4. Record `git rev-parse HEAD` and `git rev-parse origin/main`.
5. Inspect `git diff origin/main...HEAD -- companies.yaml state/seen_jobs.json .github/workflows/job-alerts.yml`.
   Expected: no implementation changes. If main has newer state-only commits,
   merge/rebase carefully, retain newest state and never force-push main.
6. Confirm no `.p2a-transport/`, temporary p2a-source-snapshot.yml or
   p2a-apply-implementation.yml remains in the final PR diff. They were temporary
   test-environment setup, not deployed runtime components.

## 2. Deterministic validation (actual current head)
Use Python 3.12 and `pip install -r requirements-dev.txt`.
Run and preserve exact outputs:
```
python main.py validate-config
python -m compileall -q src scripts
pytest -q
python scripts/check_handoff_docs.py --base origin/main --head HEAD
```
Expected unchanged source count: 812 tests. If you fix a reproduced defect,
add regression tests and report the new count; never weaken/delete tests to pass.
CI must also pass on the final exact PR head.

Explicitly confirm inline HTML cannot split a 5-year mandatory experience
requirement; structured Intern/PartTime/Contract/Temporary cannot become full-time
new-grad; Greenhouse prospect posts and Ashby isListed=false are excluded;
updated_at is not posted_at; bonus/equity never added into annual cash salary;
unsafe links and failed APIs cannot masquerade as valid empty boards; dry run
leaves saved state byte-identical and sends no webhooks.

## 3. Read-only live smoke (NO Discord or production state mutation)
Use a fresh path outside the repository:
```
SHA=$(git rev-parse HEAD)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
python scripts/verify_public_boards.py --allow-network \
  --manifest examples/p2a-public-boards.yaml \
  --output "/tmp/jobbie-p2a-${SHA}-${STAMP}.json"
```
Inspect the JSON, not only exit code. Both boards must be observed_nonempty or
observed_empty, with no source error hidden as zero. Require
state_and_config_unchanged=true, discord_sent=false, production_enabled=false.
Current counts can change: 19 and 73 were observations, not fixed assertions.
The source SHA must match the tested checkout (or documented PR merge ref).
No eligible opening is required to prove a read-only adapter works. Empty/error
results must be accurately reported. Do not expose raw job descriptions as a
public dataset. On 403/429/blocked network, stop with the exact blocker and no
proxy/login/CAPTCHA evasion or invented fixture-based live proof.

## 4. Resolve inherited Phase 1 gate before production rollout
Issue #6 requires a genuine Job Alerts run whose source includes P1-E commit
`9c9365ae5f3d936b20fc8a90c7ac22a5e0c6ff42`. Inspect actual scheduled-run source
and logs, job/source counters and successful/failed delivery semantics. Latest
run observed during this implementation, #42319860893 at 473ad343, PRECEDES
P1-E and cannot satisfy this gate. A unit CI or P2-A read-only workflow does not
replace the production scan.

If a later scheduled run exists, verify it and document the evidence. If none
exists, record BLOCKED_LIVE and leave PR open, or perform only an owner-authorized
manual production scan with existing configuration. Never run --rerun-backfill,
reset seen_jobs.json, create a fake job, or send a synthetic "eligible" alert to
manufacture success. A successful fetch is not proof every job is suitable.
Scheduler delays remain a separately documented limitation, not silently fixed.

## 5. Review, merge, post-merge verification
- Inspect the independent review's exact SHA and resolve all actionable findings.
  The no-findings review of 5e56bc6 covers unchanged source; any later functional
  change requires fresh review. A quota failure is NOT approval.
- If final-head CI, code review, live-read proof and prerequisite gate pass,
  merge PR #23 normally with expected head protection. Never force merge stale
  or failing checks. Verify actual merge SHA and main CI afterward.
- Do NOT add or activate production companies as part of this verification.
  Preserve 15 configured / original 13 enabled and unconfirmed referral states.
  Enabling specific employers is a separate, source-verified config change with
  controlled dry-run and owner authorization.
- Update STATUS.md, HANDOFF.md, RELEASE_LOG.md in any follow-up PR, plus issue
  #20 and PR #23 comments. Separate IMPLEMENTED, TESTED, LIVE_READ_VERIFIED,
  MERGED and PRODUCTION_ENABLED. Do not start P2-B or P2-C.

## Required final report
PR URL; exact source/head/merge SHA; full test count and command output; current
CI/review URLs; per-board counts and receipt; state/config invariance; Phase 1
run evidence or precise BLOCKED_LIVE reason; whether merged; whether employers
were enabled (expected no); next specific authorized step. Do not tell the owner
this is running additional job alerts when only the adapter code was staged.
