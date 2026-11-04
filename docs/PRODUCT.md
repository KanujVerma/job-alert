# Jobbie 2.0 — Product specification

## Mission and scope
A personal, single-user Discord-first recruiting assistant that progresses through six independently usable releases:
1. reliable FULL-TIME new-grad alerts for existing sources, visibly differentiated network-priority employers;
2. expanded verified job discovery;
3. resume/approved-GitHub-aware matching plus Discord commands;
4. natural, role- and company-specific, fact-preserving resume tailoring;
5. startup discovery and human-approved outbound outreach;
6. application tracking, reminders, outcome-informed ranking.

**Do not bundle later capabilities into Phase 1.** Every release must leave earlier working features intact.

## Candidate policy (owner-confirmed 2026-11-04)
- UW–Madison BS Computer Science; expected graduation December 2026.
- Desired start: January 2027 onward (earlier possible if job clearly permits); do not automatically exclude 2027 cohort postings. A cohort year alone does not prove eligibility.
- US employment authorization and no sponsorship needed; currently a permanent resident, NOT yet a citizen. Security/clearance/citizenship-only jobs are not automatically eligible.
- Roles: software engineer (new grad, SWE I), backend, full-stack, product engineer, applied AI, AI engineer, forward-deployed engineer; startup/founding engineer as an explicitly marked stretch; ML/data/platform adjacent when justified.
- No internship/co-op alerts. Full-time permanent prioritized; contract and fractional work kept separate as opt-in.
- Salary $100,000+ annual BASE preferred, not absolute. Unknown base/bonus/equity distinguishable; do not infer equity as cash salary. Unknown salary should not be hard rejected.
- Geo priority: SF/Bay Area first; other California, NYC, Chicago, TX (Austin/Dallas/Houston and elsewhere), FL (Miami and elsewhere). Other US roles remain searchable; remote must be US-eligible, not merely the word "remote".
- Personal use only. No family/referral names or contact information in the public repo.

## Original employer cohort — exact, locked
13 ENABLED source entries as of 2026-11-04:
`Micron`, `Salesforce`, `CrowdStrike`, `Intel`, `Applied Materials`, `Western Digital`, `SanDisk`, `Plaid`, `Oracle`, `Microsoft Research`, `Microsoft`, `Amazon`, `Apple`.

They each have `network_priority=true`, because the owner/family may have referral paths there. They each have `referral_status=unconfirmed` unless manually changed. The two DISABLED historic entries (`Snowflake`, `Applied Digital`) remain configured but do not automatically receive the network flag. `Microsoft Research` and `Microsoft` are two monitored sources for one broader employer; dedup both without losing source auditability.

Future discovered companies are NOT network priority by default. Referrals require explicit statuses: `unconfirmed`, `contact_possible`, `referral_requested`, `referral_submitted`, `referral_confirmed`, `unavailable`; never label an application referred without evidence.

## Three recruiting paths
### A. Traditional new grad
Verified full-time early career postings at established employers. Employer direct application links. Alerts, salary/status/eligibility evidence, network flags. Formal 2026/2027 cohort eligibility read from posting text, not guessed from its name.

### B. Startup openings
Find SF/NYC/Miami and other preferred-region startups with actual employer postings. Separate "confirmed active opening" from "company to consider". Prioritize evidence from work relevant to the startup's product.

### C. Proactive founder/engineering-team outreach
Discover relevant companies even without an open job. Find verified public business contacts where permitted; otherwise say contact unknown. Draft human-readable, company-specific message using approved public evidence. No outbound email without exact-draft, exact-recipient approval; LinkedIn sending manual. A trial project, if offered, should be scoped and paid, never automatically promised.

## UX by phase
Phase 1: existing channel continues to receive webhook embeds. New alerts show label `NETWORK PRIORITY` vs `DISCOVERED`, posting title, employer, location, role type, source URL, posting date when known, eligibility reason; salary only if provided. Review/ambiguous postings go to bounded digest/log, not incorrectly labeled confirmed.

Phase 2: broader job coverage, direct apply links, dedupe, optional digests, source metadata. Do not assume another company has a referral.

Phase 3: slash commands + private replies (`/jobs find`, `/jobs top`, `/resume upload`, `/profile show`, `/github repos`, `/settings`, `/health`); accept PDF/DOCX; ask owner to approve newly extracted facts; rank using verified job evidence and versioned candidate profile. No entire-message surveillance.

Phase 4: `/resume tailor` against verified posting or pasted JD; one-page default PDF and editable DOCX; inspect diff, edit, accept/reject, download, preserve precise submission version. Quality matters more than high keyword count.

Phase 5: `/startups find`, `/outreach draft`, `/outreach approve`; mark whether there is an active job, source-backed contact, consented public evidence, send record. Messages cannot be sent twice by retries.

Phase 6: `/applications` (saved, applied, assessment, interview, offer, rejected, withdrawn), reminders, follow-ups and optional consented Gmail classification. No auto-apply.

## Success
- Phase 1: user receives useful NEW-GRAD full-time alerts from existing original cohort, with visible priority flag, no internship spam and measured schedule reliability.
- Later: higher verified-job coverage, lower false positives, provenance-backed match explanations, actual user-approved resumes/outreach and persistent application records.
- Always: hard evidence for claims; measurable quality; $0 recurring target; graceful free-tier throttling, no surprises.

## Explicit non-goals
No mass applications; no job-board account scraping/login automation; no reverse-engineering of proprietary Jobright; no unsolicited email or automatic LinkedIn sends; no hidden paid LLM expenditure; no fictitious hiring probability; no publishing private repository details; no "production ready" claim without operational evidence.
