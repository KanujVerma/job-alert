# Phase 2 executable contract — broaden job discovery without losing original cohort

STATUS PLANNED. Prerequisite: Phase 1 RELEASED, not just merged code. Three PRs P2-A/B/C. No mandatory AI. Original 13 network flags persist; no new company inherits them.

## P2-A: direct company ATS adapters
- Add reusable Greenhouse and Ashby read-only adapters under `src/adapters/` with fixture contracts for pagination/HTTP failures/rate limits/descriptions, salary structured fields and locations. Maintain existing BaseAdapter/Job compatibility or migrate through a tested normalization layer.
- Board discovery: explicit company IDs/board tokens validated against official employer career page. Add candidate startup boards only when public endpoints and terms permit. No job-board user login or bypassing blocks.
- Show direct employer link, source ID and fetch observation time. Synthetic fixture cannot establish a live opening. Tests against fixture and allowed live read-only smoke.
- Merge only if existing 13 continue working; run source-specific health checks.

## P2-B: licensed/allowed curated feeds
- Source candidates: New-Grad-Jobs public output; SimplifyJobs list, Jobright public GitHub list, Freehire API, other aggregators ONLY after per-source license/robots/terms/data rights are documented. Reuse publicly licensed scraper code only where license allows.
- For every feed record retain original source and employer apply URL; mark discovery-only until official employer listing reconfirmed. If data rights unclear, leave feature disabled and mark `blocked_source_rights`, never invent permission.
- Maintain separate feeder provenance and refresh cadence; track closed/stale jobs without claiming hiring intent. Implement backoff, failure isolation, per-source quotas and size caps.
- Count number of unique eligible US roles and percentage of employer-link confirmations using repeatable evaluation samples, not marketing claims.

## P2-C: canonical catalogue / dedup and phase rollout
- Persist ALL validated normalized postings before per-user filtering; preserve originals and source history. Compare stable req-ID and canonical URLs; remove tracking params, do not merge distinct requisitions with identical title/location.
- Use versioned `job_id` mapping and reclassification of older data; old webhook dedupe remains valid during dual-write. A Phase 1 source must not be skipped because new source failed.
- Evaluate Cloudflare D1 or equivalent $0-capability, but do not force paid architecture or embed secrets in public GitHub. If backend not funded/free, retain a bounded SQLite artifact with documented sync and move later.
- Emit source label `network_priority` vs `discovered`, source attribution and employer-verified link confidence. Stage a shadow-run at least 72h with duplicate/coverage counters and rollback before switching canonical source.
- Tests: 30+ cross-source identity cases, source outage/corrupt feed, tracking URLs, reopened role, timezone/freshness, no duplicate/network-flag loss. Live smoke verified with exact links.

**Phase 2 shipping:** broader new-grad feeds/companies generate verified, deduplicated alerts in existing Discord channel; old network source visibility and legacy runs unchanged. Unknown data/rights -> not shipped.
