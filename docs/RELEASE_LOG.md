# Engineering release and verification log

This is an **append-only summary of verified engineering milestones**, not a claim that every implemented feature is currently working live. Each entry has a code/CI/review layer distinct from user-facing live operational evidence. More detailed logs are in GitHub PRs, Actions and phase documents. Runtime state-only commits are NOT separate product releases.

## 2026-11-06: P1-E final corrective code
- [PR #18](https://github.com/KanujVerma/jobbie/pull/18) **merged**; squash source commit `9c9365ae5f3d936b20fc8a90c7ac22a5e0c6ff42`.
- Work: `src/experience.py` adds bachelor-relevant experience-path checks, protects mandatory vs preferred qualification clauses; `src/eligibility.py` abstains on 2–4-year stretch conditions and prevents using a lower unrelated master/PhD or tool skill number; `src/backfill.py` and `main.py` acknowledge only displayed, confirmed-delivered URLs in batches of 10. Original state format, source cohort and CLI preserved.
- Evidence: [CI run #42329594922](https://github.com/KanujVerma/jobbie/actions/runs/42329594922) **716 passing tests** on branch with reconciled live-state main. Codex reviewed identical source code at `69acbe23dc9aede2dd881eb52bc72a2b0972da47` and reported **no findings** (see PR #18 discussion). Final merge-state commit only adds latest `state/seen_jobs.json`, no source deltas from reviewed blob set.
- **Operational qualification:** No post-merge full production scan recorded during documentation authoring. Earlier Intel alerts were under older classifier and must not be portrayed as examples of genuine new-grad roles. Source merged and tested, live post-release check pending.

## 2026-11-05: Phase 1D quality hardening
- [PR #15](https://github.com/KanujVerma/jobbie/pull/15) `e1608cf6223d21ef7ebaf2ce565c0e96f0159970`: seniority/location and Workday-detail checks.
- [PR #16](https://github.com/KanujVerma/jobbie/pull/16) `c9acd1cffc8ce11cca27c3821b3b0d0d29249acd`: migration and notification safety, rerunnable backfill, failed Lever API source accounting.
- [PR #17](https://github.com/KanujVerma/jobbie/pull/17) `b920f706d20b94a45d02261ed97ec911d0d85094`: automated CI, release evidence. [CI #41953363672](https://github.com/KanujVerma/jobbie/actions/runs/41953363672) **654 tests passed**, Codex finished final review with no major issues.
- Live scheduled scans subsequently reported 2 and 1 confirmed-delivery Intel job alerts in state heartbeats; eligibility of those actual jobs was subsequently questioned and is not independently confirmed.

## 2026-11-04: Phase 1 original implementation
- [PR #12](https://github.com/KanujVerma/jobbie/pull/12) `476975d043600e9d467c4c7e46f4d4c2e1a60a65`: deterministic eligibility, adversarial fixtures.
- [PR #13](https://github.com/KanujVerma/jobbie/pull/13) `ebca5eadc1cdff463564e972bd7ea0c648f45e63`: original 13 network-priority labels, unconfirmed referral metadata.
- [PR #14](https://github.com/KanujVerma/jobbie/pull/14) `9f94b560cf1600d6e933a1c6c0535084c611d63c`: versioned state, basic backfill, dedup and diagnostics.
- [Manual Actions #41915003368](https://github.com/KanujVerma/jobbie/actions/runs/41915003368) succeeded with 0 eligible matches/0 new-grad alerts. That was **workflow execution proof**, not a successful product-match proof.

## 2026-11-04: canonical documentation foundation
- [PR #1](https://github.com/KanujVerma/jobbie/pull/1) `c3e9dd130da5aeecfbf857155c2afe4209cd2f51`: AGENTS, locked product/security/data contracts, six-phase plan, phase-by-phase /code objectives and PR template.
- Original repository later renamed from `job-alert` to `jobbie`. Verified current canonical name and same repo ID before this log; no second repository created.

## Future release log protocol
Every functional PR must append a concise entry naming its PR slot, actual commit/CI URLs and truthful stage: `IMPLEMENTED`, `TESTED`, `LIVE_VERIFIED`, `BLOCKED_LIVE`, or `RELEASED`. Never invent a final merge SHA before merge; use "pending actual squash" and update after merge. No secret values or private resume contents. Update `docs/STATUS.md` and `docs/HANDOFF.md` in the same PR; CI enforces three-file handoff continuity.
