# As-built architecture vs intended future system

**As-built code release: P1-E `9c9365ae`, 2026-11-06 audit.** Changes to `main` after this may be state-only. Future architecture in `docs/ARCHITECTURE.md` describes *targets*, not implemented capabilities.

## As-built synchronous cycle
`GitHub Actions job-alerts.yml` (best-effort cron / manual dispatch)
→ `main.py run`
→ `companies.yaml` 13 enabled monitored source entries
→ `src/adapters/__init__.py` and per-platform `BaseAdapter.fetch`
→ immutable `src.models.Job`
→ `src.filtering.apply_filter_pipeline` (normal 48-hour freshness; special migration 7 days)
→ `src.eligibility.classify_eligibility` + `src.experience.assess_experience_requirements` (tri-state)
→ `src.storage.classify_jobs` (per-source seen IDs and cross-source URL history)
→ `src.notifier.Notifier` (Discord webhook, only confirmed-delivery ACK)
→ bounded versioned `state/seen_jobs.json` commit to `main`.

Ambiguous early-career jobs go into a review queue/daily digest, not an "eligible" alert. `src.backfill.deliver_backfill_batch` sends only up to 10 represented direct links per scan and acknowledges exactly those after confirmed delivery; further unalerted candidates remain pending. `src.health.compute_run_diagnostics` records failed vs empty sources and scheduling gaps.

No long-running server, webhook receiver, Cloudflare database/Worker, AI SDK, private document upload, recruiter mail OAuth or application tracker exists in the running architecture at this audited release.

## Important actual semantics and constraints
- `network_priority` is a config-driven *original source* badge, not a confirmed referral. Original 13 source names are locked in `docs/PRODUCT.md`.
- `Job.priority` means location preference and must not be reused as network importance.
- Workday may retrieve details for promising postings; Microsoft PCSX uses summary fields (full detail can require additional requests). Never treat missing descriptions as confirmed experience requirements.
- Employment/seniority parsing is heuristic and conservative. Even when classifier says eligible, real ATS full requirements and employer cohorts need verification before applications.
- `state/seen_jobs.json` public state must never contain personal resumes, family contacts or private API tokens.
- `.github/workflows/job-alerts.yml` can be 4–8 hours late despite */15 schedule; health logs do not fix the scheduler.

## Target Phase 2 delta (NOT implemented yet)
P2-A: read-only official Greenhouse and Ashby job-board adapters with pagination, description/role/compensation sources and backoff. Existing employers unaffected.
P2-B: vetted and authorized public feeds, permission and original-employer source verification.
P2-C: canonical catalogue storing validated jobs *before* personal filtering, provenance, global dedup and status history, 72-hour shadow migration. Proposed Cloudflare D1 may be replaced with a fully free local/Actions-compatible catalogue; validate actual quota and no paid fallback.

## Target Phases 3–6 (NOT implemented)
3. Discord HTTP interactions, single-user auth, approved public/private repository evidence and resume profiles, deterministic matching with optional budgeted AI.
4. Job-specific natural tailoring from approved CandidateFacts, source validation, editable review and reproducible PDF/DOCX.
5. Verified startup-company and business contact research, explicit recipient/body approval and idempotent email; LinkedIn sending manual.
6. Versioned application stage events, reminders and feedback tuning.

## Failure isolation and rollback
Legacy company polling must remain runnable even if later data feed, AI, private storage or outreach services fail. Feature flags and migrations must preserve original job history. On a state commit conflict, preserve both branches' relevant data and do NOT force push or delete state. Source-rights restrictions apply to all sources and feeds.

## Provider boundary (future only)
Source adapters -> normalized record -> hard eligibility -> ranking -> evidence-backed LLM interpretation -> human approval for documents/outbound actions -> tracking. No single model may declare that an email was sent, job is open, candidate has a credential, or applicant is hired without independently verified evidence.
