# Agent restart handoff: complete context without chat history

Read this file and [STATUS.md](STATUS.md) before changing Jobbie. Then read [AGENTS.md](../AGENTS.md), [DECISIONS.md](DECISIONS.md), [PRODUCT.md](PRODUCT.md), [PHASES.md](PHASES.md), the active phase, [CONTRACTS.md](CONTRACTS.md), [SECURITY.md](SECURITY.md), [OPERATIONS.md](OPERATIONS.md), [EVALS.md](EVALS.md) and [OPEN_SOURCE.md](OPEN_SOURCE.md). Current runtime and future architecture are intentionally separate in IMPLEMENTED_ARCHITECTURE.md and ARCHITECTURE.md.

## Current task: finish verification/merge of implemented P2-A
- Repository: `KanujVerma/jobbie`; branch `feat/p2-a-public-job-boards`; **PR #23**, issue #20.
- Source work is written, tested and publicly read-verified. Do NOT rebuild it or begin P2-B/C.
- Reviewed source commit: `5e56bc668a6615002b5ac0fbe8592b2a84987162`.
- **812 full-suite tests pass** at https://github.com/KanujVerma/jobbie/actions/runs/42342377756 .
- Real read-only check https://github.com/KanujVerma/jobbie/actions/runs/42342377775 fetched **19 Greenhouse + 73 Ashby** jobs. All were excluded by the candidate classifier. This proves API fetch/normalization, not actual suitable openings or Discord delivery.
- Codex review completed at that source commit with no findings: PR #23 summary comment 6702690334. Initial review caught inline HTML splitting required tenure; source fix plus seven regressions resolved it.
- Config and state were unchanged by the smoke. New example employers are disabled and outside production `companies.yaml`.
- **Remaining:** latest-head check/review consistency, Phase 1 issue #6 post-P1-E live gate, conditional merge, post-merge verification and accurate status update. PR is left open until those gates are satisfied.
- Exact Gemini checklist: [agent-prompts/PHASE-2A-VERIFY.md](agent-prompts/PHASE-2A-VERIFY.md).
- Evidence, including synthetic merge SHA explanation: [evidence/P2-A-VERIFICATION.md](evidence/P2-A-VERIFICATION.md).

## Takeover procedure
1. Query GitHub repo metadata, current main HEAD, PR #23 state/head/base, checks, and all review discussions. Do not assume a branch is unmerged if someone already completed it.
2. Fetch origin, inspect working tree; never discard local work. If PR is open, check out `feat/p2-a-public-job-boards` and fast-forward. If already merged, verify the real main merge and follow post-merge checks instead of duplicating work.
3. Inspect `git diff origin/main...HEAD -- companies.yaml state/seen_jobs.json .github/workflows/job-alerts.yml`. The implementation must not alter these production files. Reconcile any newer main state commits without overwriting history.
4. Run `python main.py validate-config`, `python -m compileall -q src scripts`, `pytest -q`, and `python scripts/check_handoff_docs.py --base origin/main --head HEAD` on the actual checkout using Python 3.12 and requirements-dev.txt.
5. Read source docs and the actual PR's metadata-only live receipt. When code changes, rerun the live smoke with a fresh /tmp receipt and explicit `--allow-network`; do not substitute old fixture/receipt results for the new SHA.
6. Verify issue #6's production prerequisite through actual scheduled run evidence containing P1-E code. No synthetic job alerts or state resets to manufacture proof. If unavailable, record BLOCKED_LIVE and leave PR open.
7. Merge only green, independently reviewed code with gates satisfied; then confirm main CI and update the three handoff docs with actual merge evidence. Keep all newly added employers disabled absent separately authorized activation.

## As-built code map
| Area | Files | Invariant |
|---|---|---|
| Legacy poll orchestration | main.py, companies.yaml, src/config.py | 13 enabled original companies; dry-run no state writes/webhooks |
| Employer fetch | src/adapters/*.py | BaseAdapter + shared HTTPClient; failures are not fabricated empty success |
| New public boards | greenhouse.py, ashby.py, public_board.py | GET-only fixed endpoints; listed jobs, safe IDs/URLs, bounded reads |
| Source facts | src/models.py | frozen Job, optional fields preserve old constructors; explicit salary units |
| Eligibility | filtering.py, eligibility.py, experience.py | tri-state; required qualifications and source employment override title guesses |
| Delivery | notifier.py, storage.py, backfill.py | accurate date labels, canonical URL dedup, acknowledge only delivered visible links |
| Health | src/health.py | actual failed/empty distinction and scheduler gap evidence |
| P2-A tests | tests/test_public_board_adapters.py, test_public_board_html.py | 85 new cases plus existing 727-suite baseline |
| Read-only live check | scripts/verify_public_boards.py, examples/p2a-public-boards.yaml | no production config enabling, no Notifier calls, hashes before/after |

## Locked product constraints
Personal single user; Dec 2026 UW–Madison BS CS; January 2027 target start; full-time US new-grad/SWE/related technical roles; internships excluded. $100k annual base is preferred, not a hard cutoff. SF Bay Area first, other CA/NYC/Chicago/TX/FL prioritized. US authorized without sponsorship; permanent residence is not citizenship. Original 13 network sources retain a separate UNCONFIRMED referral status. Do not add unrelated titles just to increase match counts.

Private resumes, family contacts, credentials and private GitHub code never go in public commits/logs. Private repository reading requires explicit allowlist approval; reading is not outward-disclosure approval. No auto-apply, unauthorized Jobright/LinkedIn scraping, unsolicited founder emails, or unapproved paid inference. Later phases use approved evidence for matching/tailoring and exact owner approval for outbound messages.

## Future plan and change control
P2-B permitted curated feeds, P2-C canonical catalogue/dedup/shadow migration, P3 private profile + Discord commands, P4 natural evidence-locked PDF/DOCX tailoring, P5 startup research/approved outreach, P6 application events/reminders/feedback. Each has a bounded phase document and PR sequence; none is deployed merely because a spec exists.

EVERY functional PR updates STATUS.md, HANDOFF.md and RELEASE_LOG.md together, plus any affected contracts/architecture/security/operations. CI checks missing/deleted/empty/symlinked handoff files, HTML fixture changes and renamed source paths. The guard checks presence, not factual truth. Record exact tests, reviewer SHA, actual source/run URLs, blockers and next step; no private chat memory is required.
