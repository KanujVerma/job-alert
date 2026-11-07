# Jobbie delivery roadmap — six stable releases / 20 PR slots

**Current live status must be read from [STATUS.md](STATUS.md)**. Phase 1 A/B/C/D and corrective PR #18 (P1-E) are implemented and merged. P1-E is CI-tested and code-reviewed; post-merge operational check remains separate. Phase 2 is the next planned phase and begins with P2-A only after that check. All other phases remain planned. GitHub issue/PR numbers are not the abstract P1-A slots.

**Original schedule written 2026-11-04.** PR slot labels below are stable design identifiers, NOT GitHub PR numbers. Phase 1 is now implemented; consult STATUS for actual release confidence. Never claim a slot is implemented merely because a spec or issue exists. Finish each phase and its release gate before starting another phase's code. Preserve legacy production alerts until explicitly migrated.

## Required cadence
One primary assistant executes ONE COMPLETE PHASE at a time, directly implementing code/tests/PRs when GitHub tools permit. Gemini is reserved for independent checking or genuinely blocked work. The committed /code prompt is a fallback, not a replacement for implementing available code. Each phase contains bounded sequential PR slots. Do not open 20 PRs at once. PRs within a phase are ordered. Every PR must have passing tests, reviewed diff, and documented integration proof before the next merge (or stop as BLOCKED). A phase counts as shipped only with applicable LIVE evidence; work does not automatically release on PR creation.

| Phase | PR slots | User-facing value immediately after phase | Upstream |
|---|---|---|---|
| 1. New-grad + network alerts | P1-A/B/C implemented (#12–14), D1/D2/D3 hardening (#15–17), E correction (#18) merged | Existing company alerts now appropriate for Dec 2026 new grad; original 13 marked distinctly | Current legacy code |
| 2. More jobs | P2-A Greenhouse/Ashby, P2-B permitted feeds/startups, P2-C canonical catalogue + dedup | Wider verified postings, original 13 retain priority | Phase 1 shipped |
| 3. Personal search | P3-A private Discord API, P3-B private persistence/upload, P3-C candidate + approved GitHub evidence, P3-D ranking/search commands | Search and explanatory matches using private profile; legacy alerts unaffected by AI | Phase 2 shipped |
| 4. Tailored resumes | P4-A fact ledger + model quality harness, P4-B source-preserving tailoring, P4-C PDF/DOCX renderer, P4-D review UI and release | Role-specific, natural, reviewable PDF/DOCX tied to a job, with grounded facts | Phase 3 shipped |
| 5. Startup outreach | P5-A startup intelligence, P5-B verified contacts + drafts, P5-C exact-approval email delivery | Find SF/NY/FL startup leads and send only approved outreach | Phase 4 shipped |
| 6. Tracking | P6-A applications/events, P6-B reminders + digest, P6-C feedback/evaluation/optional consented email classification | Track applications and improve ranking | Phase 5 shipped |

## Definition of PR accepted
- PR is based on latest base HEAD and writes only its scoped files (exceptions documented).
- Tests including new negative/adversarial cases pass; old `pytest` passes or an exact pre-existing failure is explained and resolved before release.
- No private resume, family referral contacts, private GitHub source or tokens in PR diff, fixtures, committed state, logs or generated docs.
- Maintains documented interfaces; migrations are idempotent; no duplicate/unsafe external send due to retry.
- Unit tests alone are not called live verification. Include one direct source/live workflow smoke when applicable.
- Codex review or equivalent reviewer requested after tests; findings resolved or labeled blocked. Do not claim review occurred unless evidence exists.
- Changelog includes observed SHAs/test run IDs, compatibility, security, rollback, residual unknowns.

## Definition of phase released
1. All phase PR slots merged on exact HEAD or documented reason for blocked phase.
2. `docs/phases/PHASE-N.md` acceptance matrix and `docs/EVALS.md` gates satisfied with real evidence.
3. Owner-facing smoke works: P1 actual webhook; P2 real source jobs; P3 authorized Discord command and private resume flow; P4 real sample tailored PDF/DOCX after approval; P5 permitted approved email test; P6 persisted application event and reminder.
4. Rollback verified; previous phase remains available; no secret leaked; provider spend under approved $0 settings.
5. Update phase status and source links in same release PR. If live credentials or user approvals unavailable, use `IMPLEMENTED/TESTED/BLOCKED_LIVE` and give exact setup request. Never invent operational success.

## Approval boundaries
User has authorized planning/foundation and implementation of features, NOT automatic mass applications, outbound email, private-code publication, job-board credentialed scraping or paid API spend. Later phase-specific exact-send approvals are separate requirements. GitHub rename is manual until verified.

## Source of truth for each execution
- [P1](phases/PHASE-1.md) / [prompt](agent-prompts/PHASE-1-CODE.md)
- [P2](phases/PHASE-2.md) / [prompt](agent-prompts/PHASE-2-CODE.md)
- [P3](phases/PHASE-3.md) / [prompt](agent-prompts/PHASE-3-CODE.md)
- [P4](phases/PHASE-4.md) / [prompt](agent-prompts/PHASE-4-CODE.md)
- [P5](phases/PHASE-5.md) / [prompt](agent-prompts/PHASE-5-CODE.md)
- [P6](phases/PHASE-6.md) / [prompt](agent-prompts/PHASE-6-CODE.md)

## Do not create "foundation PR" code for later phases during P1
No artificial DB, long-lived bot, AI SDK, frontend, or scraping source explosion in Phase 1. The working app grows by additive backwards-compatible changes. Every new feature must have a flag/rollback and evidence of prior functionality retained.
