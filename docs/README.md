# Jobbie 2.0 documentation map

**Status at foundation creation (2026-11-04):** planning baseline only. Production remains the legacy `job-alert` GitHub Actions + Discord webhook bot. The repo rename to `jobbie` is NOT complete until confirmed in GitHub settings.

## Read first
- [AGENTS.md](../AGENTS.md): mandatory coding-agent contract and stop rules.
- [PRODUCT.md](PRODUCT.md): user-facing workflows, audience, behavior, non-goals.
- [DECISIONS.md](DECISIONS.md): locked decisions, unknowns, change control.
- [CURRENT_STATE.md](CURRENT_STATE.md): verified repo baseline, known weaknesses, no invented capabilities.
- [ARCHITECTURE.md](ARCHITECTURE.md): now and later, service and failure boundaries.
- [CONTRACTS.md](CONTRACTS.md): data types, allowed status transitions, idempotency.
- [SECURITY.md](SECURITY.md): privacy, permission boundaries, external sends.
- [EVALS.md](EVALS.md): objective quality and phase release gates.
- [OPERATIONS.md](OPERATIONS.md): operating/runbook/rollback/monitoring.
- [OPEN_SOURCE.md](OPEN_SOURCE.md): vetted projects, license and reuse checks.
- [RESUME_TAILORING.md](RESUME_TAILORING.md): evidence-locked natural resume production.
- [RENAME.md](RENAME.md): owner-only GitHub rename checklist and verification.
- [PHASES.md](PHASES.md): full PR sequence and dependencies.

## Execute exactly one phase
- [Phase 1: new-grad + original network alerts](phases/PHASE-1.md) -> [short /code prompt](agent-prompts/PHASE-1-CODE.md).
- [Phase 2: more sources and catalogue](phases/PHASE-2.md) -> [prompt](agent-prompts/PHASE-2-CODE.md).
- [Phase 3: identity + matching + Discord commands](phases/PHASE-3.md) -> [prompt](agent-prompts/PHASE-3-CODE.md).
- [Phase 4: resume tailoring](phases/PHASE-4.md) -> [prompt](agent-prompts/PHASE-4-CODE.md).
- [Phase 5: startup sourcing + approved outreach](phases/PHASE-5.md) -> [prompt](agent-prompts/PHASE-5-CODE.md).
- [Phase 6: application lifecycle + optimization](phases/PHASE-6.md) -> [prompt](agent-prompts/PHASE-6-CODE.md).

Older `docs/superpowers/` plans describe historical bot development; they are REFERENCE ONLY if they disagree with these newly approved product/phase contracts. This directory's planning documents do not supersede current code when describing implementation.

## Document change precedence
1. User-authorized changes recorded in `DECISIONS.md` with date and rationale.
2. Current product/security/contracts/phase docs.
3. Executable tests and inspected implementation for observed behavior.
4. Archived design plans and conversation notes.
When two authoritative documents conflict, stop and reconcile via a documentation PR before changing behavior.

## Phase status at authoring
Every phase is `PLANNED`. Do not mark any phase complete until the independently verifiable gates in `EVALS.md` are met and the phase document records evidence.
