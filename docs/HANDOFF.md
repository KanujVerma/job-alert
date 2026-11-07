# Agent restart / zero-chat-context handoff

**Authoritative fast entrypoint for any coding model or new maintainer.** If this document conflicts with current code, GitHub issues, or latest verified CI, do NOT guess: establish current facts and update this file in a documentation PR. It is NOT a substitute for `AGENTS.md` policies.

## First 10 minutes: reproducible takeover
1. Confirm actual GitHub repository **`KanujVerma/jobbie`** (not `job-alert`), visibility, default branch and commit. Existing legacy GitHub links may redirect; keep new refs canonical.
2. Read `AGENTS.md` then `docs/STATUS.md` for audited phase/evidence; inspect open PRs and [phase tracker #6](https://github.com/KanujVerma/jobbie/issues/6).
3. Read `docs/DECISIONS.md`, `docs/PRODUCT.md`, `docs/PHASES.md` and the CURRENT single-phase file `docs/phases/PHASE-N.md`; do not infer that planned features are implemented.
4. Read `docs/ARCHITECTURE.md` and `docs/IMPLEMENTED_ARCHITECTURE.md` to separate actual runtime from future architecture; `docs/CONTRACTS.md` for data/status invariants.
5. Check `.github/workflows/test.yml` and `job-alerts.yml` last runs; scheduled cron may be hours late. Read `state/seen_jobs.json` metadata only: do not reset/edit/force backfill in public Git state.
6. Read `docs/OPERATIONS.md`, `docs/EVALS.md`, `docs/SECURITY.md` and `docs/OPEN_SOURCE.md` for live checks, data rights, privacy and rollback.
7. Check git status and open PR heads before editing. State-only commits advance `main` regularly; use a branch and bring in latest main without overwriting state.
8. Run `python main.py validate-config` and `pytest -q` (install `requirements-dev.txt`). Use targeted `python main.py run --company NAME --dry-run --verbose` only when allowed; **never use the live webhook just to prove a unit test**.
9. Before writing code, identify one PR slot, acceptance fixture matrix, file interfaces, source permissions and rollback. Implement directly where tools allow; Gemini can independently check or handle genuine tool blockers.
10. Open one reviewed PR with exact tests/results/SHAs and status. **Update `STATUS.md` + `HANDOFF.md` + `RELEASE_LOG.md` in the SAME PR.**

## Right now: exact next job
- **Latest fully merged source work:** P1-E PR #18, source release commit `9c9365ae5f3d936b20fc8a90c7ac22a5e0c6ff42`; 716 tests in CI `42329594922` on a branch reconciled with then-current production state.
- **Remaining verification:** Observe source code on a subsequent scheduled Actions run (post merge), confirm no runtime regression and no candidate alerts falsely labeled verified. Update Phase 1 status with actual run ID. If none exists, keep `BLOCKED_LIVE`, do not fake success.
- **Next IMPLEMENTATION slot after this gate:** `P2-A` Greenhouse/Ashby read-only adapters; no new private datastore, AI, resume tailoring or email.
- **P2-A exact tests:** official/public board token and employer-domain validation; pagination and 429/404/timeout behavior; full description, employment/location and compensation where supplied; direct apply URL; no hallucinated status; keeps original 13 network flag and stops on unpermitted source. See `docs/phases/PHASE-2.md`.
- **Dependency rule:** P2-B after P2-A reviewed/merged; P2-C after P2-B; Phase 3 after Phase 2 released. Stop with a sourced blocker when integration rights or live proof cannot be obtained.

## Code ownership / map
| Area | Actual file | Contract |
|---|---|---|
| Jobs/config/CLI | `main.py`, `companies.yaml`, `src/config.py` | one job scan; 13 enabled original entries; dry-run no network sends/state writes |
| Employer fetch | `src/adapters/*.py` | `BaseAdapter.fetch()` yields normalized immutable `Job` |
| Job model | `src/models.py` | frozen `Job`, no fabricated compensation or citizenship status |
| Eligibility | `src/filtering.py`, `src/eligibility.py`, `src/experience.py` | tri-state; cite evidence; bachelor's-path minimum; unknown -> review |
| Notifications | `src/notifier.py` | webhook success only; star indicates original network, not actual referral |
| Delivery + dedup | `src/storage.py`, `src/backfill.py` | canonical URL dedup; no unshown or failed-sends marked alerted |
| Health | `src/health.py` | failed vs zero, actual scan durations and schedule gaps |
| Tests | `tests/`, `.github/workflows/test.yml` | reproducible tests; CI result is not a live employer verification |
| Future features | `docs/phases/PHASE-3.md` through `PHASE-6.md` | planned, absent until code/release evidence exists |

## Locked constraints
- Personal single user. Dec 2026 UW–Madison BS CS, Jan 2027 target start; full-time US SWE/new-grad/related roles; no internships; $100k+ base is preferred, not hard requirement.
- SF Bay highest geography priority; CA/NYC/Chicago/TX/FL alternatives; other eligible US jobs searchable.
- US lawful permanent resident, no sponsorship needed; not a US citizen. Never infer clearance or naturalization.
- Original 13 network-priority sources are enumerated in `docs/PRODUCT.md` and `companies.yaml`. All original statuses UNCONFIRMED; no fabricated referral availability.
- Never commit secrets, raw resumes or family contacts. Private GitHub repo reading requires per-repo owner consent; reading is distinct from public disclosure.
- No unapproved outbound messages/applications; LinkedIn sending manual; no hidden paid API costs. Jobright proprietary scraping/reverse engineering not authorized.

## Handoff completion packet for every PR
Write exact: phase/PR slot; what changed and why; reviewed SHAs; test command/output; CI URL; observed live run URL (or `BLOCKED_LIVE`); code/data contract deltas; provider/source rights; migration and rollback; remaining risk; next PR owner can start without asking questions. Log immutable history in `docs/RELEASE_LOG.md` and replace `docs/STATUS.md`'s live snapshot.

Do not claim that simply adding documentation updates production behavior. Never schedule or promise background work without an authorized scheduler.
