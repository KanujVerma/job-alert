# Phase 2 executable contract — broaden job discovery without losing original cohort

STATUS PLANNED. Prerequisite: P1-E CI/review merged (done) plus a documented post-merge live check (verify STATUS). Three PRs P2-A/B/C. No mandatory AI. Original 13 network flags persist; no new company inherits them.

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
## P2-A executable start packet (for the next coding agent)
1. Verify current `main`, CI, post-P1E scheduled scan and [Phase 1 tracker #6](https://github.com/KanujVerma/jobbie/issues/6). If missing live verification, record BLOCKED_LIVE rather than pretending it occurred.
2. Inspect `src/adapters/base.py`, `src/adapters/__init__.py`, `src/models.py`, `src/config.py`, `src/http.py`, `src/notifier.py`, `main.py` and adapter fixture idioms. Preserve the frozen `Job` constructor and current CLI.
3. Confirm official Greenhouse/Ashby public job posting API formats, pagination, response limits, allowed fetch frequency and exact direct apply URLs using official documentation at execution time. Do not invent board IDs or use unauthorized authenticated endpoints.
4. Implement reusable Greenhouse and Ashby adapters using `HTTPClient` and current adapter registry, plus timeout/429/error handling and explicit source attribution. Emit only source-backed fields; do not mark jobs employer-verified from mock fixtures. Keep missing salary, date, role type as unknown rather than making up data.
5. Add fixtures covering empty board, multi-page/multi-location results, 429/403/404, malformed JSON, missing descriptions, requirement split and compensation with correct base units; ensure supplier-specific URLs cannot expose tokens in logs.
6. Initially configure ZERO additional active companies without a documented verified board token, employer source and permission. Add a small explicit approved sample after real read-only smoke. Never give discovered companies network priority.
7. Run all existing tests plus adapter tests; compare before/after original 13 source throughput; keep state unchanged in dry run, avoid flooding Discord. Prove one *permitted* live read-only fetch.
8. Update `docs/STATUS.md`, `docs/HANDOFF.md`, `docs/RELEASE_LOG.md` and adapter contract docs, then PR review. P2-B is blocked until P2-A merged and tested. P2-C requires source rights, canonical state dual-write and 72-hour shadow evidence.

This scope is about **adding read-only discovery adapters**, not a Cloudflare migration, LLM matching, automated application submission, or resume processing.
