# Jobbie canonical project status

**Last human/tool audit:** 2026-11-06 (America/Chicago; GitHub commits use UTC). **This is a snapshot, not live telemetry.** Confirm `main`, open PRs, current Actions runs and current state before execution; `state/seen_jobs.json` receives automatic commits after each scheduled scan.

**Repository:** `KanujVerma/jobbie` (GitHub rename verified; repository ID `1339847701`). **Main source release inspected:** `9c9365ae5f3d936b20fc8a90c7ac22a5e0c6ff42` (P1-E PR #18 squash). Any subsequent main head may be a state-only commit rather than a code release. Identity is no longer blocked on rename.

## Phase and confidence ledger

| Milestone | Code | CI / review | Actual operation | Next gate |
|---|---|---|---|---|
| P1-A/B/C (#12–14) | Merged | Historical synthetic fixtures, first review failure; see logs | Live manual Actions run #41915003368, 0 eligible at that time | Superseded by P1D/E |
| P1-D1/D2/D3 (#15–17) | Merged | 654 tests in CI; final Codex review of #17 completed | Scheduled jobs subsequently delivered recorded alerts; see state heartbeats | Avoid treating those first Intel matches as verified suitable |
| **P1-E (#18)** | **Merged** to `main` at `9c9365ae` | **716 passing tests**, [Actions #42329594922](https://github.com/KanujVerma/jobbie/actions/runs/42329594922) on state-reconciled branch; Codex completed review of same code at `69acbe23` with no major findings | **No post-merge eligible job alert proof recorded in this audit.** Source changes merged; wait for a scheduled run/authorized live check | Verify production scanner with new code and review actual new-grad relevance |
| **Phase 2A** | Implemented on `feat/p2-a-public-job-boards`; not yet merged/enabled | Local full suite: **803 passed**; remote CI/review pending | Read-only smoke pending; no new active employers | Latest source CI, code review and read-only receipt; Phase 1 live gate remains |
| Phase 2B/C | PLANNED | Not applicable | Not deployed | Separate reviewed phases; no feeds/database in P2-A |
| Phases 3–6 | PLANNED | Not applicable | Not deployed | Sequential dependencies in `docs/PHASES.md` |

## What actually works today
- Python `main.py` CLI and GitHub Actions monitor, 13 enabled original sources + 2 disabled.
- `src/adapters/`: Workday, Eightfold PCSX, Amazon, Apple, Microsoft Research, Lever, SmartRecruiters, Oracle and disabled experimental adapters.
- `src/eligibility.py`, `src/experience.py`: deterministic tri-state new-grad eligibility and guarded bachelor-appropriate experience rules. `src/filtering.py` composes freshness/location/classification.
- `src/notifier.py`: Discord outbound webhook, star for `network_priority`, no assumed referral.
- `src/storage.py` and `src/backfill.py`: v2 historical state, URL dedup, pending/alerted, bounded batches of at most 10 visible backfill links acknowledged only after confirmed delivery.
- `src/health.py`: adapter health, actual run heartbeat/gap detection.
- `tests/` + `.github/workflows/test.yml`: automated regression tests.

## Operational risks and known unknowns
1. **Scheduling:** GitHub Actions nominal `*/15` cron has shown gaps of roughly 4–8 hours, including on November 6. Diagnostics detect but DO NOT fix drift. No guarantee of real-time alerts.
2. **Plaid:** Lever source has returned HTTP 404. The adapter now records failure rather than healthy zero; find an authorized new endpoint in a narrowly scoped later PR, not an authenticated bypass.
3. **Some enabled sources have zero results** and may legitimately have no listings or need source investigation. Do not fabricate job counts or hiring-frozen conclusions.
4. **Evidence of user eligibility:** Earlier Intel alerts were recorded as successfully sent, but qualified bachelor-path requirements were questioned; P1-E addresses parser risk. It has not established that those old jobs were actually new-grad eligible.
5. **No actual referral contact records**: all original 13 are priority network entries with referral status unconfirmed.
6. **Private features unavailable:** Discord slash commands, private resume indexing, approved private GitHub repos, tailored resumes, startup outreach, Gmail sending and application tracker belong to future phases.
7. **No $0 hosting additions approved/deployed** beyond the current public Actions bot; provider plans in docs are hypotheses pending quota/security/terms verification.

## Immediate next execution
1. Check [PR #18](https://github.com/KanujVerma/jobbie/pull/18) merged, CI, and latest post-merge `Job Alerts` scheduled run. Record actual runtime evidence with its SHA/timestamp; distinguish 0 qualifying openings from broken alerts.
2. Check and reconcile [Phase 1 tracker #6](https://github.com/KanujVerma/jobbie/issues/6) and historical open tickets #2–5, without misrepresenting review-only gates as complete.
3. Then begin **Phase 2, P2-A** under `docs/phases/PHASE-2.md`: official read-only Greenhouse/Ashby adapters, source verification, fixture tests; preserve original 13, state and webhook. Phase 2B and 2C follow as separate reviewed PRs; no large rewrite or preemptive Cloudflare service.
4. Update this file, `docs/HANDOFF.md`, and `docs/RELEASE_LOG.md` in EACH functional PR. CI enforces doc freshness; source-data state commits are exempt.

No new agent needs past ChatGPT conversation, locally stored resumes, or private credentials merely to continue the current phase.

## Documentation continuity follow-up (2026-11-06)
[PR #19](https://github.com/KanujVerma/jobbie/pull/19) merged at `7458d18299b1ab36b25a221990ef2fd6d265252c` (725 tests), publishing current status, architecture and agent handoff. Codex subsequently found HTML-fixture and rename-path bypasses, fixed by [PR #21](https://github.com/KanujVerma/jobbie/pull/21), merged at `dbb309a6b30bbf90cf4fa2d887052467d8760720` with [727 passing CI tests](https://github.com/KanujVerma/jobbie/actions/runs/42331100940) and a completed Codex review **with no findings**. This changes documentation/CI only; P1-E's post-merge Job Alerts scan remains a separate live-verification gate. **Next code issue: [P2-A #20](https://github.com/KanujVerma/jobbie/issues/20)** after [Phase 1 #6](https://github.com/KanujVerma/jobbie/issues/6) is satisfied.

## P2-A implementation checkpoint
Owner explicitly requested implementation now. Greenhouse/Ashby adapters, typed
source facts, config validators and regression tests are implemented in the
P2-A branch. No existing employer config or production state has changed.
The earlier Phase 1 live gate stays open; adapter staging does not claim it
satisfied. Full local regression: 803 passed (727 existing + 76 new), 32.68s.
See [P2-A implementation](implementation/P2-A.md),
[source contracts](sources/P2-A_PUBLIC_APIS.md), and
[Gemini verifier runbook](agent-prompts/PHASE-2A-VERIFY.md).
