# Open-source reuse and external source rights

Verified source-repo license metadata as observed 2026-11-04; re-check exact repo HEAD, LICENSE and NOTICE before vendoring and pin versions. **Code license and job-dataset access are distinct permissions.** Nothing here proves that paid/unofficial APIs or a user's session may be scraped.

| Candidate | Location / relevant files | Observed code license | Intended use | Limits |
|---|---|---|---|---|
| New-Grad-Jobs | https://github.com/ambicuity/New-Grad-Jobs ; `scripts/ngj/filters.py`, `dedup.py`, `compensation.py` | MIT | Adapt 2026/2027 level detection, normalized comp/dedup, test ideas; evaluate feed | Broad curated data contains senior, global, unrelated roles; re-filter strictly. Confirm feed reuse rights. |
| Job Scout | https://github.com/weberwcwei/job-scout ; `src/job_scout/scorer.py`, `db.py`, `notify.py` | MIT | Adapt weight categories, tracking schema | Keyword score does not establish eligibility or hiring probability. |
| Resume Matcher | https://github.com/srbhr/Resume-Matcher ; `apps/backend/app/services/resume_preservation.py`, MCP `tailor_and_verify.py`, writing prompts/tests | Apache-2.0 | Fact-preservation and structured edit ideas; adapt with notices | Its eval tests include opt-in paid evaluation; not independent guarantee of output quality. |
| RenderCV | https://github.com/rendercv/rendercv ; schema, renderer, ATS test scripts | MIT | Dependency for reproducible PDF | Its published parsing study is limited corpus; do local verification. |
| Reactive Resume | https://github.com/reactive-resume/reactive-resume ; proposal/diff/undo UI patterns | MIT | Review UX inspiration/selected modules | Large app and different frontend; not a turnkey embed. |
| Freehire | https://github.com/strelov1/freehire ; architecture and public jobs API | MIT | Architecture source, optional permitted discovery | Public API quotas/terms and data rights to be verified; don't copy full Go app. |
| JobSpy | https://github.com/speedyapply/JobSpy | MIT | Optional source adapter research | Unofficial board scraping fragile, may be disallowed; not Phase 1. |
| REA | https://github.com/morluto/rea | MIT | Inspect OUR app or permitted OSS behavior | Do not reverse-engineer Jobright's protected implementation without authorization. |
| Jobright public list | https://github.com/jobright-ai/2026-Software-Engineer-New-Grad | no confirmed reusable license | Manual reference for source discovery | Public visibility is not permission to mass ingest. |
| Simplify New-Grad Positions | https://github.com/SimplifyJobs/New-Grad-Positions | check actual terms/license | Curated discovery | Do not assume license to republish job entries. |

Other potential components: official public Greenhouse Board API, Ashby Job Posting API, Discord Interactions API, Cloudflare Worker/D1/R2; each integration must be reverified against current docs, terms, free quotas, and source permissions.

## Import procedure
1. Identify smallest reusable function, current upstream commit SHA and exact license. Record upstream URL, copyright notice, LICENSE/NOTICE files, relevant dependency versions and risk.
2. Copy no more code than necessary or depend on a pinned published release. Preserve provenance in PR and notice where required; do not silently strip original author credit.
3. Write differential tests against existing bot fixtures and fuzz/adversarial examples. Avoid unrelated framework/ORM migrations.
4. Explicitly distinguish public job FEED permissions from source CODE license. If unconfirmed, disable feed and write blocker, not a fake successful integration.
5. No external auth bypass, captcha solving, proxy evasion or Jobright reverse engineering without rights.
6. Add maintenance plan for upstream security/bug changes and rollback if adapter breaks.

## Provider choice (future)
Groq GPT-OSS 120B initial free-tier **candidate** (not guaranteed best) for bounded AI tasks. Confirm current privacy, data retention, rate limits and free API availability at integration time. Use model-neutral adapter; no paid fallback. Optional Cloudflare Workers AI or genuinely included API credits may be benchmarked with explicit owner approval and privacy check; don't assume a ChatGPT subscription includes usable API billing.

## Reference engineering hierarchy
Official employer/ATS source > verified licensed structured feed > curated public lead > unverified aggregated/social mention. Any job read from the latter tiers must be checked at employer before labeling actively open. Company/contact facts also need source time and provenance.
