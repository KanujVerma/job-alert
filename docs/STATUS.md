# Jobbie canonical project status

**Audited:** 2026-11-06 America/Chicago (evidence timestamps extend into 2026-11-07 UTC). This is a snapshot, not continuous telemetry. Verify GitHub HEAD, PRs and Actions before acting.

Canonical repository: **KanujVerma/jobbie**, ID 1339847701. Repository rename is complete. Current inspected main is `d98afe73674925f8aaeb9d6fe21df0b077375689`; later state-only commits may advance main.

## Active delivery: Phase 2A, PR #23
- **PR:** https://github.com/KanujVerma/jobbie/pull/23
- **Branch:** `feat/p2-a-public-job-boards`
- **Status:** IMPLEMENTED, CI-TESTED, PUBLIC-API-READ-VERIFIED, INDEPENDENTLY REVIEWED. **Not merged or production-enabled at this checkpoint.**
- **Reviewed runtime source:** `5e56bc668a6615002b5ac0fbe8592b2a84987162`. Subsequent documentation-only commits do not change those source blobs; verify this with Git before reusing evidence.
- **Full CI:** https://github.com/KanujVerma/jobbie/actions/runs/42342377756 — **812 passed in 32.95s**, Python 3.12.16, config validation and documentation gate passed. Baseline was 727 tests; P2-A adds 85 parametrized regression cases.
- **Live public reads:** https://github.com/KanujVerma/jobbie/actions/runs/42342377775 — 19 Greenhouse postings and 73 Ashby postings. All 92 were classified excluded on these provider-owned smoke boards. These counts are source connectivity/normalization proof, NOT new-grad matches.
- **Side effects:** receipt verifies identical `companies.yaml` and `state/seen_jobs.json` hashes before/after; no Discord sender was constructed or called; examples remain disabled.
- **Independent review:** Codex completed review of `5e56bc6` with `has_any_findings=false`, `has_unresolved_findings=false`. Receipt: https://github.com/KanujVerma/jobbie/pull/23#issuecomment-6702690334 . The initial inline-HTML tenure bug was fixed and seven regressions added before this review.
- **Durable evidence:** [P2-A verification record](evidence/P2-A-VERIFICATION.md) and [unaltered live JSON](evidence/P2-A-live-2026-11-07.json). The JSON source SHA is GitHub's synthetic PR merge checkout, not a deployed production commit.

## Implemented P2-A functionality
`GreenhouseAdapter` and `AshbyAdapter` use official public GET endpoints and the existing HTTPClient/registry. Shared validation bounds response size/job count/detail requests, prevents arbitrary endpoints/redirects and preserves unknown fields. Prospect/unlisted jobs are excluded. Posting IDs, descriptions, location options, explicit employment, published-versus-updated dates and salary units retain their source meaning. HTML inline formatting cannot disconnect years from an experience requirement. Structured non-full-time types and incomplete descriptions cannot become verified new-grad alerts just because of a title.

The normal filter, immutable Job model, notification-payload builder, review queue, config validator and dry-run pipeline are integrated. `scripts/verify_public_boards.py` produces metadata-only read receipts without calling the notification loop. No database, LLM, private documents, feed scraping or application submission was added.

## Existing production system and constraints
- The original Python GitHub Actions monitor remains unchanged in production configuration: 15 configured sources, original 13 enabled, 2 disabled.
- Original network priority: Micron, Salesforce, CrowdStrike, Intel, Applied Materials, Western Digital, SanDisk, Plaid, Oracle, Microsoft Research, Microsoft, Amazon, Apple. Network priority does not mean a referral has been submitted.
- Phase 1 A/B/C (#12–14), D1/D2/D3 (#15–17), E (#18) code is merged. P1-E source commit is `9c9365ae5f3d936b20fc8a90c7ac22a5e0c6ff42`.
- **Issue #6 still needs post-P1-E production verification.** The latest scheduled Job Alerts run observed in this audit is #42319860893 at `473ad343...`, before the P1-E merge. Do not use that run as post-P1-E evidence.
- GitHub's nominal 15-minute cron has observed multi-hour gaps. Source health logging does not fix the scheduler. Plaid's known Lever 404 is a failure, not evidence of no employer openings.
- Phases 2B/2C and 3–6 remain PLANNED. The two P2-A example boards are outside production config and disabled; no new ongoing job alerts are active.

## Exact remaining work for Gemini / next agent
Follow [PHASE-2A-VERIFY.md](agent-prompts/PHASE-2A-VERIFY.md), using **PR #23**, not a new implementation branch. Inspect exact latest HEAD and review/check results; resolve any genuine new defect with tests, without rewriting already working code. Verify the upstream Phase 1 operational gate, then merge only if all gates allow. Keep new production employers disabled until separately source-verified and activation is authorized. Record actual merge and post-merge CI, or leave PR open with precise blockers. Do not start Phase 2B.

Every functional PR updates STATUS, HANDOFF and RELEASE_LOG together. CI enforces their presence; a reviewer must still verify statements against actual code, logs and source evidence.
