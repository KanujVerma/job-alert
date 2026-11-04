# Repository rename checklist — owner action still required

Target GitHub repo: `KanujVerma/jobbie` (exact spelling: j-o-b-b-i-e, lowercase). Current GitHub repo at foundation authoring: `KanujVerma/job-alert`. **The connected GitHub tools used for this doc work cannot rename a repo; do not claim it has happened.**

## Owner action
1. Open `https://github.com/KanujVerma/job-alert/settings` with repository admin access.
2. In `Settings -> General -> Repository name` enter `jobbie` and select `Rename`. If the target name is unavailable, do not choose a different spelling; report blocker.
3. Verify the page at `https://github.com/KanujVerma/jobbie` loads the SAME repository and repo ID, preserving commit history, issues, Actions and secrets. Confirm old links redirect. Verify with `gh repo view KanujVerma/jobbie --json nameWithOwner,visibility,defaultBranchRef,id`.
4. Update local remotes: `git remote set-url origin git@github.com:KanujVerma/jobbie.git` (or HTTPS URL). Confirm `git remote -v` and `git ls-remote origin HEAD`.
5. Verify Actions workflows still enabled, existing `DISCORD_WEBHOOK_URL` repository secret remains configured without showing its value, scheduled job can run and commit public state, branch protection/rulesets and integrations still point to correct repo.
6. Review external links, README title, badge URLs, Discord/webhook references, any connected CI/integrations, README/canonical references. GitHub redirects are not a substitute for updating configured remotes and integrations.
7. Run one manual dry-run, then observe one scheduled workflow, compare output state before declaring rename operationally complete.

## Agent responsibility after owner action
Inspect `get_repo` or `gh repo view`. Only after verifying actual canonical `nameWithOwner` should agent update doc status and source URLs in a separate PR. Do not attempt to create a second new repository or transfer history by copying code. If this cannot be verified, all code PRs continue targeting existing `KanujVerma/job-alert` and the rename remains an explicit blocker to the final identity task.
