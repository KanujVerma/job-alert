# Jobbie technical and product documentation

**Start here if joining cold:** [Agent handoff](HANDOFF.md) -> [Current audited status](STATUS.md) -> [Agent rules](../AGENTS.md) -> [Roadmap](PHASES.md) -> active [Phase 2 contract](phases/PHASE-2.md), once the Phase 1E post-merge live gate is verified. GitHub source HEAD and Actions evidence override old snapshots.

## Sources of truth
- [STATUS.md](STATUS.md): CURRENT code release, CI evidence, live operation confidence, blockers and next implementation.
- [HANDOFF.md](HANDOFF.md): exact fresh-agent onboarding, reading order, commands, code map, next PR and completion packet.
- [RELEASE_LOG.md](RELEASE_LOG.md): chronological PR/commit/CI/review record and remaining live checks.
- [MAINTENANCE.md](MAINTENANCE.md): documentation update requirements, CI checks and conflict resolution.
- [IMPLEMENTED_ARCHITECTURE.md](IMPLEMENTED_ARCHITECTURE.md): running implementation and module map.
- [ARCHITECTURE.md](ARCHITECTURE.md): FUTURE evolutionary architecture and provider boundaries; not already deployed.
- [PRODUCT.md](PRODUCT.md): audience, three recruiting paths, 13 original priority sources, UX requirements.
- [DECISIONS.md](DECISIONS.md): locked policy, architecture choices and defaults.
- [CONTRACTS.md](CONTRACTS.md): eligibility, canonical IDs, candidate evidence, document/outreach models.
- [SECURITY.md](SECURITY.md): privacy and outbound authorization.
- [EVALS.md](EVALS.md): test matrices and release gates.
- [OPERATIONS.md](OPERATIONS.md): dry run, Actions, state safety, monitoring and rollback.
- [OPEN_SOURCE.md](OPEN_SOURCE.md): permitted reusable code, candidate feeds and license checks.
- [RESUME_TAILORING.md](RESUME_TAILORING.md): planned natural, evidence-locked tailored resume quality pipeline.
- [RENAME.md](RENAME.md): verified repository rename and local-remote migration checklist.
- [CURRENT_STATE.md](CURRENT_STATE.md): **historical 2026-11-04 baseline only**; do not treat as current implementation.

## The six release contracts and bounded prompts
| Phase | User value / current state | Detailed contract | Agent objective |
|---|---|---|---|
| 1 | Initial new-grad bot + P1D/P1E correctness fixes merged; post-P1E production check pending | [P1](phases/PHASE-1.md) | [P1 prompt](agent-prompts/PHASE-1-CODE.md) is historical |
| 2 | Wider verified job discovery; **next, planned** | [P2](phases/PHASE-2.md) | [P2 prompt](agent-prompts/PHASE-2-CODE.md) |
| 3 | Private profile and search; planned | [P3](phases/PHASE-3.md) | [P3 prompt](agent-prompts/PHASE-3-CODE.md) |
| 4 | Natural fact-preserving tailoring; planned | [P4](phases/PHASE-4.md) | [P4 prompt](agent-prompts/PHASE-4-CODE.md) |
| 5 | Startup scouting and explicitly approved outbound; planned | [P5](phases/PHASE-5.md) | [P5 prompt](agent-prompts/PHASE-5-CODE.md) |
| 6 | Applications, reminders, feedback; planned | [P6](phases/PHASE-6.md) | [P6 prompt](agent-prompts/PHASE-6-CODE.md) |

**Archive:** older `docs/superpowers/` development plans are historical, not the release contract. For requests to implement a phase, read active phase docs and live GitHub first. Never start a later phase because an old conversation said it is ready.

## Exact update cadence
Every functional PR changes [STATUS](STATUS.md), [HANDOFF](HANDOFF.md) and [RELEASE_LOG](RELEASE_LOG.md); a pull-request CI check enforces that these files were touched. Scheduled production state-only commits are exempt. The guard does NOT prove truth: reviewer must still compare documentation to code, CI and live logs.
