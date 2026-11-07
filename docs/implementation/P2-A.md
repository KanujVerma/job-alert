# P2-A implementation and completion record

Base inspected: `d98afe73674925f8aaeb9d6fe21df0b077375689` (727-test baseline).
PR: https://github.com/KanujVerma/jobbie/pull/23 . Branch: `feat/p2-a-public-job-boards`.

## Implemented scope
1. `src/adapters/public_board.py`: fixed public endpoint/config validation, exact hosted-board provenance, safe public URLs, bounded response/job/description/detail counts, HTML/date/compensation normalization. No custom API endpoints, login, redirects or application POSTs.
2. `GreenhouseAdapter` / `AshbyAdapter`: normalized immutable Jobs with stable IDs, source descriptions, location options and explicit employment/compensation. Greenhouse prospect posts and Ashby unlisted posts never surface. Both documented list APIs are single-list; unexpected truncation fails rather than inventing cursor behavior.
3. Optional source metadata on frozen Job preserves old constructors. Explicit source internship/contract/part-time overrides a positive title; incomplete descriptions and unknown employment without body evidence cannot become confidently eligible alerts.
4. Registry/config validation, correct first/last-published notification labels, persisted review-source facts, no new active employers or changes to state/history.
5. Fixture, adversarial HTML and normal `main.do_run` dry-run integration tests, failed-source isolation and side-effect assertions.
6. Standalone read-only verification script/workflow emits metadata-only receipts, checks state/config hashes, and never constructs Notifier. Disabled example boards are outside production config.
7. Durable evidence and exact agent takeover/verification instructions in GitHub.

## Acceptance evidence
- Runtime source `5e56bc668a6615002b5ac0fbe8592b2a84987162`.
- Full CI **812 passed**: [run #42342377756](https://github.com/KanujVerma/jobbie/actions/runs/42342377756).
- Public read **19 Greenhouse + 73 Ashby**, zero eligible on those smoke boards, no sends/writes: [run #42342377775](https://github.com/KanujVerma/jobbie/actions/runs/42342377775).
- Independent review completed with no findings at the runtime source SHA. Initial inline-HTML requirement split was reproduced/fixed with seven additional tests.
- [Evidence and raw receipt](../evidence/P2-A-VERIFICATION.md) distinguish source head, synthetic PR merge checkout, live connectivity and production activation.

## Exact boundary
P2-A is implemented and read-verified on a feature branch. It is NOT yet merged or enabled in production. The prior Phase 1 issue #6 live gate remains unverified and must not be invented. No P2-B feeds, P2-C catalogue, AI, private candidate data, scheduler migration, new production employers or automatic outbound actions. Complete [the verifier runbook](../agent-prompts/PHASE-2A-VERIFY.md) before any release claim.
