# P2-A observed verification evidence

This record is a durable checkpoint for PR #23, not a claim of production activation.

## Exact source and checkout
- PR: https://github.com/KanujVerma/jobbie/pull/23
- Reviewed runtime source head: `5e56bc668a6615002b5ac0fbe8592b2a84987162`.
- PR base at check: `d98afe73674925f8aaeb9d6fe21df0b077375689`.
- GitHub Actions synthetic merge checkout: `00111df2b1a09be5b487723be8a0df1c5e79bffe` (Merge 5e56bc6 into d98afe7, confirmed in checkout logs). This is the `source_sha` in the raw receipt. It is NOT a merge to main.
- Documentation-only evidence updates after this source head do not create new runtime evidence; compare source blobs before reusing these results.

## Unit / integration verification
- Workflow: Tests; run https://github.com/KanujVerma/jobbie/actions/runs/42342377756
- Job ID: 128312672867.
- Python 3.12.16; configuration valid; documentation continuity PASS.
- Actual log final line: `812 passed in 32.95s`.
- 727 baseline cases + 78 adapter/source/integration cases + 7 inline-HTML regressions = 812.

## Live read-only API verification
- Workflow: P2A public boards (read-only).
- Run: https://github.com/KanujVerma/jobbie/actions/runs/42342377775
- Job ID: 128312673212; artifact ID: 13562066104.
- Original artifact: `p2a-readonly-42342377775-1`; archive digest `sha256:ea668c21045f1872f40a2bf4cdc0460bb5648c705963e2505ec2815bae14d629`.
- Read timestamps: 2026-11-07T05:21:30.835016+00:00 through 2026-11-07T05:21:32.974531+00:00.
- Unaltered metadata JSON preserved in [P2-A-live-2026-11-07.json](P2-A-live-2026-11-07.json) so the proof survives seven-day Actions artifact expiry.
- Greenhouse own board: **19 postings**, 0 missing descriptions, 0 missing posted timestamp.
- Ashby own board: **73 postings**, 3 missing descriptions, 0 missing posted timestamp.
- Candidate classifier returned **excluded for all 92** at the time of this check. The board counts prove live discovery, NOT appropriate new-grad jobs.
- Both APIs used GET only. Config/state SHA256 hashes were identical before/after. `discord_sent=false`, `production_enabled=false`, `state_and_config_unchanged=true`.

## Independent review
- Codex summary: https://github.com/KanujVerma/jobbie/pull/23#issuecomment-6702690334
- Reviewed source: 5e56bc668a6615002b5ac0fbe8592b2a84987162.
- Completed at 2026-11-07T05:24:10.891873Z; no findings and no unresolved findings in its machine-readable review summary.
- Initial finding: HTML get_text(newline) could separate inline `5 years` from `professional experience`, causing a false eligible new-grad result. Fixed by preserving inline continuity and inserting only block boundaries; seven regression cases passed before re-review.

## Still not established by this evidence
- A production merge or deployment of PR #23.
- Activation of additional employers in companies.yaml (none added).
- New job alerts or application submissions (none sent).
- Closure of Phase 1 issue #6's post-P1-E runtime gate.
- Fifteen-minute cron reliability or completeness of every employer's API data.

Use [the Gemini completion checklist](../agent-prompts/PHASE-2A-VERIFY.md) to resolve the remaining operational/merge gates without rewriting the implementation.
