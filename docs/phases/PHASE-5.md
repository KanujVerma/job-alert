# Phase 5 executable contract — startup opportunities + approved outreach

STATUS PLANNED. Requires Phase 4 released. PRs P5-A/B/C, no mass outreach, no LinkedIn auto-DM.

## P5-A: research startups and hiring signals
- Target SF Bay Area primarily, also NYC, Miami/other FL, Texas, Chicago, rest CA. YC company/public jobs, allowed ATS listings, verified company sites, licensed data only. Comply with terms, rate limits, robots; no authenticated scraping/Jobright internal reverse engineering.
- Two results: `confirmed_open_role` with verified employer job URL and freshness; `company_outreach_target` without confirmed role. Never claim the latter is actively hiring.
- Company record: canonical domain, verified product, stage/size ONLY where sourced, geography, role signals, last checked, source refs, why specific public/approved projects relate.
- Fail-safe missing company facts as unknown; verify 20 company samples manually.

## P5-B: contact verification and grounded drafting
- Contact only from permitted publicly listed BUSINESS information or manually provided contact; each email/source recorded with retrieval timestamp. Do not guess addresses from name patterns, scrape LinkedIn profiles, buy/leak personal lists, or claim recruiter status from an outdated page.
- Outreach draft cites 1–2 relevant approved PUBLIC projects and company-specific grounded observations. Tone concise, non-template-y; not falsely claim production metrics or customer experience.
- Trial project proposal only if owner approves and company engages; scoped PAID trial, no unconditional free labor offer. Distinct outreach path if no vacancy.
- Store versioned draft and recipient, no automatic send merely from preview.

## P5-C: outbound approval/send integration
- Use authorized Gmail sending OAuth or another expressly approved provider, least privilege. Require owner action approving exact recipient/subject/body; server stores SHA256 digest and one-time nonce bound to owner ID and expiry.
- Sender service performs idempotent send, records provider message ID/time. Timeout -> `indeterminate`, reconcile; do not retry blindly.
- Bounce/opt-out handling, rate limit, stop/unsubscribe where relevant; no high-volume automation. LinkedIn generates copy-ready drafts, user sends manually.
- Test deliberate mismatch after approval, duplicate click, network timeout, unauthorized click, revoked approval. No email live test without direct recipient/owner approval.
- Phase 1/2 alerts still work if contact research or mail unavailable.

**Release:** one approved permitted test email with verified provider receipt, at least five accurately distinguished startup company targets, no unapproved external send.
