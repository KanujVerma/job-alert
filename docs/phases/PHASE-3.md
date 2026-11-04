# Phase 3 executable contract — candidate profile, approved GitHub and interactive Discord

STATUS PLANNED. Requires Phase 2 released and $0 free-tier/permission feasibility confirmed. Four ordered PRs P3-A/B/C/D.

## P3-A: Discord command endpoint / identity
- Register official Discord HTTP interactions, verify Ed25519 signatures and request timestamp/replay window BEFORE parsing/acting, allowlist one owner Discord user ID. Only commands and explicitly clicked context menu interactions; never read entire channel history.
- `/jobs find`, `/jobs top`, `/profile show`, `/github repos`, `/settings`, `/health`; unauthorized requests return no private data.
- Ack/defer per Discord API deadline, enqueue heavy work; correlation and idempotency on interaction ID. No new message reading permission.
- Deploy Cloudflare Worker free-tier only after limits and required secrets verified; fallback CLI command interface until configured. Security negative tests mandatory.

## P3-B: durable personal storage + uploads
- Private DB for owner profile/settings/jobs/matches; private file storage for PDF/DOCX and optional exports. No private data in publicly committed `state/`, GitHub issues, workflows or logs.
- Signed short-lived downloads, content-type/size validation, parser timeouts, arbitrary PDF safety, upload deletion, encrypted transport, least privilege.
- Resume versions immutable; each upload proposes extracted facts; do not auto-confirm new metrics, company claims, dates or work authorization.
- Job/owner model isolation; migration backup and rollback, quotas and no-paid default.

## P3-C: evidence ledger and repo permissions
- Parse approved Epic/HCL/Tesla résumé versions (owner uploads only; do not package private files in repo).
- Public GitHub project candidates: Clinical Notes NLP Assistant, RegimeRadar, Relay, Drift. Preserve docs' caveats: synthetic clinical demo, real-vs-demo market data, incomplete native app, no live capital. Authorship requires source/PR evidence; README doesn't prove independent validation.
- Private repos: default none. Owner approves exact repo allowlist and visibility scope. Read-only token; index limited necessary evidence with SHA/path/text span; never send private code externally without separately approved disclosure.
- CandidateFact states proposed/confirmed/rejected/revoked; owner correction invalidates dependent draft caches.

## P3-D: deterministic matching + optional AI explanation
- Eligibility tri-state remains authoritative. Ranking with initial weight rubric (role 30, skill 25, geography 15, salary 10, freshness 10, company/startup preference 10); unknown dimensions are missing, not false zero.
- Source-grounded why/why-not explanations cite job text and confirmed candidate fact IDs; "match score" NOT a hiring probability.
- AI optional for complex cases, initial candidate Groq GPT-OSS120B subject to privacy, quota and quality benchmarks; provider adapter model-agnostic. If no LLM, basic matching works.
- Discord private interactive search, save/feedback and guarded commands work end-to-end. No auto-submit or outbound send.

### Release proof
- Authorized user command + unauthorized user rejection + replay attack; actual Discord interaction if credentials provided.
- Private upload and deletion, redaction scan; candidate fact confirmation and revocation propagation.
- 40 labeled opportunity fixtures with confusion matrix, unknowns/eligibility reasons, score reproducibility. Preserve Phase 1/2 independent scrape under model outage.
- $0 quota cap and failure behavior validated. If secrets missing -> `BLOCKED_LIVE`, do not manufacture demonstration.
