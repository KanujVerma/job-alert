# Fact-preserving, natural resume tailoring — specification and evaluation

**Status:** Not implemented. Phase 4 feature with dependencies from Phase 3. Current owner PDFs are private inputs, never to be copied into this public repo. Three existing styles (general SWE/Epic, AI/data/HCL, other role-specific/Tesla) illustrate different emphasis; they are not independent proof of new accomplishments.

## Outcome and definition of "good"
A recipient should see a credible early-career engineer with relevant real work for THIS company/role. Improvements must be natural, specific, concise and genuinely more relevant than the original without changing source facts. Do not optimize toward invented ATS percentages or maximize keywords at expense of honesty.

## Ground truth and evidence
Canonical facts are extracted from approved resume versions, individually confirmed user additions, and approved GitHub source/PR evidence. A repo README may document IMPLEMENTATION, not automatically prove production deployment, independent evaluation, customer impact, personal ownership, clinical validity or live finance operations.

For each evidence atom store:
`fact_id`, exact text, actor/role attribution, tech/tools actually used, scope and outcome (only if documented), exact citation (source version + page/span OR approved repo URL/SHA/path/line/PR), visibility permission, confirmed/revoked state. Never allow "all code in private repo" as public disclosure.

Protect:
- identity, contact information, school, degree and Dec 2026 graduation;
- employer names, official role titles, dates, internship vs employee distinctions;
- numbers, measurements, currency and technical details;
- scope (co-developed vs individually owned, mock vs real, experiment vs deployed);
- work authorization, no-sponsorship language; never present permanent resident as already naturalized.

## Pipeline implementation steps
1. Snapshot official employer JD/URL/posted/observed timestamps. If no official role, use user-supplied JD marked `unverified_job_snapshot`.
2. Extract requirements with exact citations. Split required/preferred, responsibilities, company product context, role type and known unknowns.
3. Choose highest-evidence role profile: SWE/backend, AI/FDE, startup/product, data/ML. Ranking may promote a project absent from one-page baseline only if approved candidate fact source supports it.
4. Produce a deterministic *content plan* before prose: selected facts/bullets, gaps to avoid, sections/order, one-page budget. Identify claims where user confirmation is needed.
5. LLM generates STRUCTURED edit operations with original text + replacement + fact IDs + job requirement IDs + short rationale. No freeform rewrite of a PDF.
6. Independent validation: frozen protected fields; every numeral/technical claim, employment/ownership change, and implied product maturity checked; unsupported edit rejected or asks user. Model self-explanations cannot override validators.
7. Present exact diff: additions, deletions, reorders, typography changes, limitations, source facts. User can accept/reject/edit and revalidate; stale source/version invalidates proposal.
8. Render one-page tagged/selectable-text PDF via pinned RenderCV and editable DOCX from same structured source; reparse with PyMuPDF/pdftotext + DOCX extraction, compare canonical text and preserved fields, visually inspect clipping/widows; validate clickable links.
9. Store immutable artifacts with hashes, model/prompt/render version, approved timestamp, job snapshot, and editable source for reproduction. Attach specific version to application.

## Writing standard
- Prefer genuine verbs and direct engineering descriptions: "Built...", "Implemented...", "Developed...", "Tested..." when evidence supports.
- Show challenge/action/outcome where source says outcome. No invented percentage, ROI, reliability/latency improvement or "production-grade" assertion.
- Avoid "passionate", "results-driven", "cutting-edge", "leveraged", "spearheaded", "orchestrated" and repetitive formulas.
- Avoid em dashes in generated resume. Vary syntax naturally. One technically coherent point per bullet; don't pad to force character count.
- Job keywords belong only in honestly supported contexts; a company JD mentioning Kubernetes does not grant Kubernetes experience.
- Preserve natural voice and a readable consistent 1-page technical layout. No unnecessary made-up professional summary or buzzword stack.
- For early startup roles emphasize ownership of specific modules, customer-impact awareness, product judgment when evidenced, not "founder" unless actually accurate.
- For AI agent roles emphasize agents, evals, retrieval, privacy/source controls where actually evidenced.
- For generic SWE emphasize shipped implementations, APIs, state, tests and systems decisions.
- For ML/data emphasize evaluation design and observable analytics, avoid claiming real trading outcomes from synthetic studies.

## Rendering options and reuse
Main candidate: `rendercv/rendercv` (MIT) for structured YAML/JSON -> PDF; `python-docx` for DOCX, same canonical content with parity checks. `srbhr/Resume-Matcher` (Apache 2.0) has tested preservation checks/structured tailoring/rubrics and can be selectively adapted with license/NOTICE. `reactive-resume` (MIT) provides user edit proposal/undo patterns but not necessarily a good fit as embedded full app. Validate local compatibility and avoid vendor lock-in.

Jobright is a PUBLIC feature benchmark only: user-visible matching/tailoring workflow can be studied with legitimate authorization, not scraped or reversed without rights. REA `morluto/rea` may be used for our own code/authorized open source and not to circumvent Jobright restrictions.

## Evaluation gold set / release gate
Freeze 24 legitimate job descriptions (6 per SWE/backend, applied AI/FDE, startup/founding, data/ML), each with frozen candidate facts and source refs. Baseline vs tailored outputs scored blind on:
- Zero accepted unsupported numerals/skills/ownership/title/dates in synthetic/adversarial corpus. One severe hallucination BLOCKS release until fixed.
- No fabricated candidate work or claims about source job company/size/salary.
- Exact preserved fields in 100% of rendered regression files.
- All 24 PDFs DOCX structurally parse and pass correct reading order, links, page count (1-page default; exception only owner-approved).
- Human owner reviews at least 12 diverse outputs before live rollout; >=10/12 must be rated more relevant AND at least as natural as baseline with no fabricated claim. Record disagreements, failed examples, and any manual corrections. This is internal product gate, NOT a proven employer/ATS advantage.
- Multiple provider/challenger models if accessible for $0; log per-model factual fail rate, quality, latency, quota errors and context privacy.
- Stale proposal/changed factual claim before acceptance must invalidate draft and require regeneration/revalidation.
- No generated resume is sent to employer automatically. Only user downloads and submits.

## Failure handling
If model unavailable or quota exceeded, return error with original resume safely intact. If model proposes unsupported claim, remove/reject it rather than rephrase deceptively. If PDF is two pages or unreadable, fail build and show actionable layout errors. If user didn't approve final draft, never call it submitted.
