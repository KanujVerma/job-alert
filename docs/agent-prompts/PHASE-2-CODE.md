# Single-phase /code objective: Phase 2

/goal

Repository: KanujVerma/jobbie if the GitHub rename is verified; else KanujVerma/job-alert. Read AGENTS.md, docs/README.md, PRODUCT.md, DECISIONS.md, CURRENT_STATE.md, PHASES.md, CONTRACTS.md, ARCHITECTURE.md, SECURITY.md, EVALS.md, OPERATIONS.md, OPEN_SOURCE.md, and docs/phases/PHASE-2.md. Inspect current main, actual Phase 1 release evidence, old adapters/tests/state and Actions. If Phase 1 is not RELEASED, stop with an explicit blocker; do not skip it.

Execute ONLY Phase 2, in ordered reviewable PRs P2-A (Greenhouse/Ashby official read-only adapters), P2-B (licensed/public feed discovery with explicit source-rights review), P2-C (canonical job catalogue, cross-source dedup, shadow dual-write and rollout). Preserve 13 original NETWORK PRIORITY flags; all new companies default discovered/no referral. Do not implement AI, interactive Discord, resume upload, automatic applications or outbound sends. Do not scrape authenticated/protected Jobright/LinkedIn data.

Test all existing behavior; 30+ dedup/adversarial fixtures, source failures, first-seen vs posted dates, source links, 72h shadow comparison if actually observable. Reconcile canonical IDs against old v2 state; no re-alert storm. Source rights unknown -> source remains disabled. Record source URLs, run IDs, test results, regressions, privacy checks, rollback. Review and merge PRs only when gates pass; otherwise report BLOCKED. Do not call mock data "live" or start Phase 3.
