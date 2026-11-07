# Gemini completion checklist: P2-A implementation (not a rewrite)

Read AGENTS.md, STATUS.md, HANDOFF.md, this file, implementation/P2-A.md,
phases/PHASE-2.md, sources/P2-A_PUBLIC_APIS.md, CONTRACTS.md and SECURITY.md.
Use the **open P2-A PR** linked from issue #20. The branch is
`feat/p2-a-public-job-boards`. Do NOT start P2-B or P2-C.

## Exact ownership
The adapters, tests, normalization, config/registry integration, smoke CLI and
source docs are already implemented. Your job is to verify the latest exact
head, fix only a reproduced defect, and finish access-dependent/live gates.
Do not redesign the project, disable tests, broaden eligibility, reset state,
change the original 13 employers, enable a speculative board or send emails.

## 1. Establish exact checkout and approvals
1. Read issue #20, Phase 1 issue #6, the P2-A PR body/review threads and actual
   GitHub Actions results. Record the exact current head SHA.
2. `git fetch origin`; `git checkout feat/p2-a-public-job-boards`;
   `git pull --ff-only`; `git status --short`. Do not discard uncommitted work.
3. Verify branch still excludes production `companies.yaml` and
   `state/seen_jobs.json` changes. A subsequent state-only main commit must not
   be overwritten when updating the branch. Use normal merge, never force main.

## 2. Deterministic validation
Use Python 3.12; `pip install -r requirements-dev.txt`.
Run and preserve exact output:
```
python main.py validate-config
python -m compileall -q src scripts
pytest -q
python scripts/check_handoff_docs.py --base origin/main --head HEAD
```
Tests must cover both adapters, structured employment exclusions, missing
fields, prospect/unlisted exclusion, stable IDs, shared 429/timeout handling,
invalid URLs/redirects/truncated lists, salary source units and dry-run state
invariance. Failed tests block merge; do not report a stale head as passing.

## 3. Read-only live adapter proof (NO Discord)
Use a fresh nonexisting output path, never any file under `state/`:
```
python scripts/verify_public_boards.py --allow-network \
  --manifest examples/p2a-public-boards.yaml \
  --output /tmp/jobbie-p2a-<EXACT_HEAD_SHA>-<UNIQUE_SUFFIX>.json
```
Replace `<EXACT_HEAD_SHA>` with `git rev-parse HEAD`; replace `<UNIQUE_SUFFIX>`
with the current UTC timestamp. Check JSON and actual request receipts:
- Both platform results observed_nonempty/observed_empty, not error hidden as 0.
- `state_and_config_unchanged: true`, `discord_sent: false`,
  `production_enabled: false`, correct source SHA.
- Public source URLs match recorded employer boards; no unlisted Ashby job,
  prospect Greenhouse post or guessed salary/date is exposed.
- Empty board is valid fetch evidence, NOT proof of an eligible opening.
- API refusal/403/429/network blockage: record BLOCKED_LIVE and exact error.
  Do not use proxies, login credentials, unofficial endpoints or fake fixtures.
The P2-A read-only Actions workflow produces the same receipt when it can
reach both endpoints. Compare source SHA; do not substitute an old run.

## 4. Phase 1 prerequisite and rollout
Phase 1 issue #6 still requires post-P1-E runtime verification. Inspect a
scheduled `Job Alerts` run whose source includes commit `9c9365ae`; ensure no
runtime regression and source health is accurately reported. The old 15-minute
cron is best effort and can drift hours; do not call it fixed. If none exists,
record that the P2-A code is implemented/tested but production rollout remains
blocked. Do not force a live backfill to generate messages.

Do NOT enable the two example companies merely because they parse. Keep the
15 existing configurations / 13 enabled, all original referral states unchanged.
Enabling any specific employer requires source verification, explicit scope,
controlled dry-run and owner approval. It is a separate config change.

## 5. Review, merge and exact handoff
- Obtain completed independent code review of the latest source (e.g.
  `@codex review`); address findings with tests and rerun CI. Usage limit is a
  blocker, not an approval. Review comments on old hashes do not approve new code.
- If checks/review/allowed live gates pass, merge the P2-A PR normally, verify
  merged SHA and post-merge CI. Otherwise leave PR open with precise blockers.
- Update STATUS/HANDOFF/RELEASE_LOG in the same follow-up PR and issue #20 with
  implemented/tested/live-read/production-enabled as separate statements.
- Final report: PR URL, actual head/merge SHA, test count and command output,
  CI/review URLs, per-board live counts and receipt, unchanged-state evidence,
  exact remaining blockers. Do NOT start another phase.
