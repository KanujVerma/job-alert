# Documentation continuity, freshness, and agent handoffs

The repository, NOT a ChatGPT conversation or a private agent memory, is the durable source of product and engineering context. **Every functional PR must update these three files at the same time:**
1. `docs/STATUS.md` — current audited phase and evidence, outstanding blockers and next PR (replace snapshot).
2. `docs/HANDOFF.md` — next agent's first actions, code map/assumptions if changed, exact next task, how to verify.
3. `docs/RELEASE_LOG.md` — append PR-scoped engineering evidence, test links and risk. PR number can be pending until actual creation/merge; update afterward. Do not invent commit IDs.

Other doc contracts to update if affected:
- `docs/PRODUCT.md` for user-visible behavior.
- `docs/ARCHITECTURE.md` and `docs/IMPLEMENTED_ARCHITECTURE.md` for interfaces, module dependencies or real topology.
- `docs/CONTRACTS.md` for new status/fields/schema, migrations and dedup.
- `docs/DECISIONS.md` for a decision with identifier, timestamp, rationale and approval.
- `docs/PHASES.md` and the exact `docs/phases/PHASE-N.md` for PR slots and release gate changes.
- `docs/EVALS.md` for acceptance thresholds, metrics and evidence.
- `docs/SECURITY.md` and `docs/OPEN_SOURCE.md` whenever access/PII/dependencies/data rights change.
- `docs/OPERATIONS.md` for provider secrets, flags, rollback, runtime workflows and runbooks.
- `README.md` when command examples, configured companies or deployed features change.

## Automated gate
`scripts/check_handoff_docs.py` runs for ALL GitHub pull requests against `main` via `.github/workflows/test.yml`. It examines changed files. When any functional Python/config/workflow/dependency source changes, the PR must also modify `STATUS.md`, `HANDOFF.md`, and `RELEASE_LOG.md`. It rejects PRs that omit any of the three. Synthetic tests check the detector.

The gate intentionally excludes state-only `state/seen_jobs.json` commits (the live bot generates them automatically), and does not pretend to verify whether documentation statements are truthful. **Human or independent reviewer still checks claims and links**. A docs-only PR may update these records without changing runtime.

## Source and conflict resolution
- Verify GitHub `main` and exact PR diff/CI. A README or planning doc is never proof of deployed behavior.
- Frozen product constraints and security rules in `DECISIONS.md`, `PRODUCT.md`, `SECURITY.md` have priority unless the owner authorizes a recorded ADR.
- `STATUS.md` is the latest audited snapshot, not a continuously live data feed; scheduled scans update `state/seen_jobs.json` independently. Source release commits, CI evidence, live delivery and human approval remain distinct.
- When stale/contradictory documentation is discovered, correct it immediately in the next PR, or open a blocking docs issue before implementing dependent features. Avoid hallucinating a reconciliation.
- Keep historical context in `RELEASE_LOG.md`; do not rewrite history to conceal failed reviews/tests.

## Release process
1. Build tests and code on a branch.
2. Update handoff/status/release log, plus affected phase/architecture/security documents.
3. CI checks docs presence, then tests. Independent code review and source-rights checks follow.
4. Merge only green code with resolved major findings; record source merge SHA and operational gate separately.
5. When actual production proof arrives, update `STATUS.md` and issue tracker with source URL, timestamp and observed result, without mixing synthetic fixtures into live evidence.

## Future-phase rule
Plan each next PR inside the repository before coding; do not rely on an unshared Gemini/Codex transcript. Capture decisions as versioned docs and prioritize explicit API schemas, fixture definitions, acceptance conditions, cost/privacy limits, and rollback.
