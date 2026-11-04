# Phase 4 executable contract — natural, honest job-specific resume tailoring

STATUS PLANNED. Requires Phase 3 released. Four PRs P4-A/B/C/D. `docs/RESUME_TAILORING.md` and `docs/EVALS.md` are normative. No AI may self-certify its output.

## P4-A: reliable fact selection / provider challenge
- Use confirmed CandidateFacts (from uploaded source resumes and explicitly approved GitHub evidence). Preserve exact title, employer, chronology, source version and scope. Select strongest evidence for each role.
- Build frozen 24-case evaluation set (6 SWE/backend; 6 AI/FDE; 6 small startup/founding; 6 adjacent data/ML) with source JDs archived where rights permit, otherwise hashed metadata/short evidence excerpts.
- Provider abstraction starting candidate Groq GPT-OSS 120B; benchmark available free alternatives and permitted zero-incremental-cost API credits WITHOUT spending unapproved money. Track model/version/input digest/latency/rate-limit/error/cost.
- Record human naturalness judgments; avoid verbose generic phrasing. Model cannot manufacture achievements.

## P4-B: tailored resume planner + preservation validator
- Model proposes list of structured operations: `replace bullet`, `reorder verified bullet/project`, `remove irrelevant content`, `reorder skill`, `rewrite concise summary`. Each operation cites fact IDs and original source text.
- Deterministic validator checks unchanged identity/employer/role/title/date/degree; numerical quantity preservation; no unauthorized new tech/ownership/performance/validation claims. Unsupported output -> reject specific change and request owner fact confirmation.
- At most 1 page by default, ATS-safe, no fake ATS-score optimization. Original resume immutable; revisions produce version and fine-grained diff. Explicit owner approves final.
- Natural copy: challenge-action-result where evidence supports, no corporate filler, no em dashes, no gratuitous keyword insertion, varied sentence structure, 1 idea per bullet.

## P4-C: deterministic PDF/DOCX
- Adopt pinned compatible RenderCV (MIT) or equivalent for structured PDF, plus typed DOCX output and independent text-extraction test.
- Same canonical structured content for both; 1-page visual/layout validation, proper selectable text, working links, correct order, no clipping or hidden fields. PDF and DOCX parity.
- Artifacts SHA256, version, model/prompt version and job_snapshot ID. Unauthorized downloads prohibited.

## P4-D: review UX and release
- Private review page opened from Discord, side-by-side source/proposed bullet changes, accept/reject/edit, undo, page preview; stale edit detection.
- `/resume tailor`, `/resume versions`, download links. Application records can attach exact approved file, never mutate past attached version.
- Compare original vs tailored in blind human review; no unsupported claims in accepted output, actual PDF parsing, naturalness threshold per EVALS; provider fallback on quota without bad claims.
- Confirm with actual sample user approved variant and document downloads; if review/approval absent, mark `BLOCKED_LIVE` instead of releasing silently.
