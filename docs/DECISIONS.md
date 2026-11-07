# Decision register — locked product/architecture choices

Dated 2026-11-04. "Locked" means an agent cannot change it without explicit owner authorization documented by a new ADR entry. "Implementation choice" may be optimized within constraints with tests; explain tradeoffs in PR.

| ID | Status | Decision / implication |
|---|---|---|
| J-001 | LOCKED | Canonical product/repository slug `jobbie` lowercase. GitHub repository rename verified (same ID 1339847701); historical `job-alert` links/remotes require migration. |
| J-002 | LOCKED | Personal single-user Discord-first product; only owner's authenticated Discord ID may change private state. |
| J-003 | LOCKED | Six independent, sequential phases. Phase 1 is deployable WITHOUT AI, Cloudflare, private storage, a new UI or additional job sources. |
| J-004 | LOCKED | December 2026 graduate; January 2027 preferred start; full-time new-grad/entry-level/appropriate 0–2-year roles; selected explicit stretch roles; internships excluded from alerts. |
| J-005 | LOCKED | US employment authorization without sponsorship; green-card permanent residency is NOT citizenship. Citizenship-only / clearance requirements need exact evidence and a real eligibility check. Never assume a planned future naturalization is complete. |
| J-006 | LOCKED | $100k BASE target is a ranking preference. Unknown compensation remains unknown; no false salary estimates. |
| J-007 | LOCKED | SF Bay Area top priority; other CA, NYC, Chicago, TX, FL next; other US openings not automatically excluded. |
| J-008 | LOCKED | The 13 enabled original career-site entries in PRODUCT.md carry `network_priority` forever unless owner changes it. `referral_status` separate and default unconfirmed. Disabled Snowflake and Applied Digital not in original flagged 13 by default. |
| J-009 | LOCKED | Three recruiting tracks: traditional new grad, open startup roles, proactive startup outreach without confirmed opening. |
| J-010 | LOCKED | Only explicitly approved PRIVATE GitHub repositories may be indexed, read-only. Approval to read is not approval to disclose externally or transmit full code to an LLM. |
| J-011 | LOCKED | Outbound email may be sent only after exact recipient/subject/body/version approval by owner, via supported authorized integration; LinkedIn messaging remains manual. No auto-apply. |
| J-012 | LOCKED | Free recurring budget; paid services disabled by default, hard limits, usage observation, no claims of unlimited free service. |
| J-013 | LOCKED | Jobright functionality may be studied via public docs and authorized manual tests; proprietary implementation, authenticated scraping, REA reverse-engineering without authorization excluded. |
| J-014 | LOCKED | Resume tailoring may reorder/rewriter evidence but must preserve employer/title/dates/metrics/ownership and distinguish synthetic/prototype/validated/live status. Every added fact needs an approved source. |
| J-015 | LOCKED | No model output alone can satisfy eligibility, change confirmed candidate facts, publish a resume, send an email, or mark an application as submitted. |
| J-016 | LOCKED | Legacy webhook alerts and state survive each migration until a measured cutover with rollback. Existing GitHub Actions trigger is best-effort, not guaranteed every 15 minutes. |
| J-017 | IMPLEMENTATION CHOICE | Start with Python job ingestion, later Cloudflare Worker/D1/private R2; treat provider/architecture as replaceable interfaces if free-tier limits dictate. |
| J-018 | IMPLEMENTATION CHOICE | Groq GPT-OSS 120B is initial **candidate** for free AI inference, not an asserted winner. Benchmark naturalness + grounded accuracy with privacy policies and rate limits. No paid OpenAI usage unless credits/billing verified and separately approved. |
| J-019 | IMPLEMENTATION CHOICE | Reuse MIT/Apache-licensed open-source components only with NOTICE/LICENSE obligations; evaluate permitted data-feed terms independently. |
| J-020 | LOCKED | Existing README and historical plans are legacy references, not authoritative proof of 2.0 implementation. Published "live" status requires actual operator evidence. |
| J-021 | LOCKED | Phase 1D Quality and Release Hardening: Enforce strict new-grad eligibility (levels, locations, 0-2 yrs), confirmed alert delivery invariant, 7-day backfill freshness decoupling, review queue ranking/retention, and CI test automation. |

| J-022 | LOCKED | Owner-selected implementation flow (2026-11-05): Primary assistant writes code, tests, reviewable PRs and operational checks directly when tools permit. Gemini is for independent review or genuinely blocked implementation, not the default proxy for work that can be done here. Continue one phase at a time with working releases. |

| J-023 | LOCKED | Documentation continuity: every functional source/config/test/workflow PR updates `docs/STATUS.md`, `docs/HANDOFF.md` and `docs/RELEASE_LOG.md` in the same PR; automated CI presence gate plus independent truth review. Historical state-only runtime commits are exempt. |
| J-024 | LOCKED | No manual reset/delete/forced push of production `state/seen_jobs.json` to force notifications. Keep existing 13-source priority cohort; migrations/backfills idempotent and scoped. Repo historical notes about `rm state/seen_jobs.json` are superseded by `docs/OPERATIONS.md`. |

## Open decisions: default actions
 (not questions to invent answers for)
1. Referral people/contact details: UNKNOWN. Maintain `unconfirmed` for all 13 until owner supplies and confirms. Do not request names as prerequisite to Phase 1.
2. Exact local 2027 cohort cutoff: PER-JOB. Quote original requirements and mark review when ambiguous.
3. Explicit owner Discord ID, webhook, Cloudflare credentials, email OAuth: SECRET/NOT PROVIDED IN REPO. Phase 1 reuses existing webhook; later phases must stop at credential-dependent live validation and give exact setup instructions, not forge success.
4. Private repo allowlist: NONE until owner explicitly approves each repository; public repo evidence is still filtered for verified authorship and readiness.
5. Salary of any particular listing: UNKNOWN without source-backed posted compensation.
6. Whether owner can claim included API credits: UNKNOWN until verified; default no paid billing.
7. GitHub repository rename COMPLETED and verified. Individual computers' local git remotes still need operator verification; do not claim they were updated.

## Change process
New entries: `J-025` onward, date, request/justification, contracts affected, PR, migration, test delta, rollback. Never silently "resolve" two conflicting instructions. A lower-priority implementation detail may be selected with explicit rationale and tests; a LOCKED policy conflict requires owner decision.
