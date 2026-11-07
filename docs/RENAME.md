# Verified repository rename and remaining local integrations

**GitHub rename DONE, verified 2026-11-06.** Canonical repository is [KanujVerma/jobbie](https://github.com/KanujVerma/jobbie), repository ID **1339847701**, public, default `main`. The original repository had the same ID before its rename. PRs, Actions and state history remain within the same repository. Do NOT make a second repository or keep referring to the identity task as blocked.

The old `job-alert` URL may redirect for web navigation, but an external integration or local clone should not rely on that permanently.

## Check each local clone / third-party integration if used
1. `git remote -v`; if it still points at `job-alert`, change origin to `https://github.com/KanujVerma/jobbie.git` (or the SSH equivalent).
2. `git ls-remote origin HEAD` to confirm access.
3. Verify GitHub Actions runs and repository secrets through Settings without exposing values. The current Actions history has runs after rename; this does not verify every local credential or webhook account.
4. Inspect any external dashboard, badge, dependency, app integration or README link that embeds the former slug. Correct if necessary.
5. Preserve the full commit history and `state/seen_jobs.json`; do not reset or force-push.

No user action is needed to rename the GitHub repo again.
