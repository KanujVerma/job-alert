# Canonical contracts: classification, identity, evidence, states

These contracts define REQUIRED SEMANTICS for implementation. Current `Job` and state format differ; use phased migrations, retain compatibility, and add tests. Planned fields are NOT current implementation.

## Phase 1 role classification
Separate three dimensions:
- `employment_type`: `full_time`, `internship`, `co_op`, `contract`, `part_time`, `unknown`.
- `career_level`: `new_grad`, `entry_level`, `junior`, `mid`, `senior`, `unknown`.
- `eligibility`: `eligible`, `needs_review`, `excluded`.
No class may be inferred solely from a random word in the full description, such as "interns welcome", "sales team", or "PhD preferred".

Suggested result shape (names adjustable only with same semantics and tests):
`EligibilityVerdict(job_id, policy_version, status, employment_type, career_level, reasons[], evidence_spans[], unknowns[])`.
Reasons are stable machine-readable codes, e.g. `INTERNSHIP_ROLE`, `SENIOR_LEVEL`, `GRADUATION_OUTSIDE_WINDOW`, `US_CITIZEN_REQUIRED`, `NON_US_ONLY`, `CONFIRMED_NEW_GRAD`, `ENTRY_LEVEL_TITLE`, `ZERO_TO_TWO_YEARS`, `WORK_AUTH_UNKNOWN`, `LOCATION_UNKNOWN`, `FULL_TIME_UNSPECIFIED`.
A reason requires raw job field/source evidence and must not contain confidential candidate identity.

Rules of priority: explicit internship/co-op in job TITLE or structured employment field beats incidental full-time mention; explicit senior title or minimum >=4 years excludes; specified 0–2 years counts early-career; 3 years => `needs_review` stretch; unknown years/title => `needs_review`, never silently "eligible"; explicit graduation date mismatch excludes; 2027 cohort without clear dates remains review; citizenship/active clearance requirement excludes if clearly mandatory; vague "security experience" does not mean US citizenship required. Mixed US+non-US location qualifies US if a selectable US location exists; otherwise unknown. Preserve `role_type` legacy enum as presentation when needed, do not equate that with `eligibility`.

Phase 1 alert policy: `eligible` -> individual webhook alert; `needs_review` -> bounded digest/report or separate clearly labeled review channel if already configured, never confidently eligible; `excluded` -> no user job alert. Existing notifier transport remains; summary cannot claim employer posting time when only first-seen time known.

## Network/referral fields
Stable source key per configured adapter entry. Metadata `network_priority: bool`, `cohort: original_2026_11_04 | discovered`, `referral_status: unconfirmed | contact_possible | referral_requested | referral_submitted | referral_confirmed | unavailable`. Do not replace current location-based Job.priority with network status. Original 13 per PRODUCT.md; per-source flags persist. Actual referral contact names or details must never be committed to public `companies.yaml` or public state. Phase 1 records only non-sensitive status `unconfirmed`; later private database can store owner-confirmed statuses.

## Job identity and provenance (Phase 2)
`job_id` canonical immutable ID. `job_source_id` each observed external source; `canonical_employer_domain`, `official_req_id` optional, `original_url`, `canonical_url`, `source_platform`, `first_seen_at`, `last_seen_at`, `posted_at` nullable, `status` (open/closed/unknown), `status_evidence`, `location_set`, `annual_base_min/max` optional + currency + period + source.
No inferred posting date, salary, active opening, or company office city. Metadata missing -> null/unknown. Dedup official req ID when trustworthy; fallback URL normalization with tracking parameter stripping; do NOT merge two distinct req IDs because titles/locations happen to match.

## Candidate fact/evidence (Phase 3)
`CandidateFact`: fact_id, content, category, source_kind, source_ref, exact evidence span/commit_sha, privacy_scope, attribution_owner, validation_status (proposed/confirmed/rejected/revoked), verified_at, supersedes.
Private repo read permission is NOT publication permission. Distinguish authored implementation from collaborators' work; distinguish synthetic/prototype from production. Unknown metrics stay unknown, not zero.

## Resume proposal and artifacts (Phase 4)
`ResumeProposal`: source_resume_version, target_job_snapshot, list of operations (id/path/original/replacement/evidence_fact_ids/rationale), model/version, input_digest. Every operation validated against protected fields and cited evidence; stale original text invalidates the operation.
`ResumeArtifact`: approved_structured_version, PDF and DOCX SHA256s, render version, parser test results, page count, owner_approval_timestamp. Original immutable. Never silently substitute a new version for an already-submitted application.

## Outreach and application states (Phases 5–6)
Outreach: `draft -> reviewed -> approved -> sending -> sent | failed | indeterminate | canceled`. Approval digest binds exact destination/address, subject and body. `indeterminate` requires reconciliation; no blind retry.
Application: `discovered -> saved -> applied -> assessment -> interview -> offer`, with alternative `rejected`, `withdrawn`, `closed` and event timestamps. May skip states with explicit user event; never auto-mark "applied" because a URL was opened, "referral submitted" because a message was drafted, or "interview" because a recruiter viewed a profile.
Commands require authorized user, validation, rate limits and audit; feedback cannot overwrite canonical job/candidate sources.

## Migration rules
Every schema migration needs idempotent upgrader, backup/export, rollback note, dry-run fixtures, and no plaintext secrets. Existing `state/seen_jobs.json` contains historical alerted flags; migration may preserve but not erase it. A bounded `policy_version`-scoped backfill is the only way to surface previously seen newly eligible jobs without a notification storm.

## P2-A optional Job metadata (backward-compatible)
`source_url`, `source_board`, `source_job_id`, `source_internal_job_id`,
`source_updated_at`, `posted_at_kind`, `employment_type`,
`description_complete`, `compensation` have defaults, preserving old constructors.
Known source internship/contract/part-time beats title-based new-grad guesses.
New-source unknown employment without explicit full-time evidence or missing
description requires review. Old adapters default these fields to None and retain
existing behavior. Structured source facts persist in the review queue.
`CompensationRange` stores Decimal salary/pay bounds, explicit currency, nullable
interval and source field/tier label. Never sum equity/bonus or annualize an
unknown interval. Greenhouse post and internal IDs remain distinct.
`updated_at` is not `posted_at`; Ashby `publishedAt` is labeled last published.
