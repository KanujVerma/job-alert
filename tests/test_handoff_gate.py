"""Doc continuity checker must require a real handoff with implementation PRs."""
from scripts.check_handoff_docs import (
    REQUIRED,
    functional_source_changed,
    missing_handoff_documents,
)


def test_all_source_changes_require_three_handoff_documents():
    functional = [
        "src/eligibility.py",
        "src/adapters/ashby.py",
        "main.py",
        "companies.yaml",
        "requirements-dev.txt",
        "tests/test_ashby.py",
        "scripts/check_handoff_docs.py",
        ".github/workflows/job-alerts.yml",
        ".github/workflows/test.yml",
    ]
    for changed in functional:
        assert functional_source_changed(changed), changed
        assert missing_handoff_documents({changed}) == set(REQUIRED)
        assert not missing_handoff_documents({changed, *REQUIRED})


def test_state_only_commits_and_doc_changes_are_exempt():
    for path in [
        "state/seen_jobs.json",
        "docs/ARCHITECTURE.md",
        "docs/STATUS.md",
        "docs/HANDOFF.md",
        "README.md",
        ".github/PULL_REQUEST_TEMPLATE.md",
        "assets/preview.png",
    ]:
        assert not functional_source_changed(path)
        assert missing_handoff_documents({path}) == set()


def test_missing_two_documents_remains_blocking():
    changed = {"src/experience.py", "docs/STATUS.md"}
    assert missing_handoff_documents(changed) == {
        "docs/HANDOFF.md", "docs/RELEASE_LOG.md"
    }


def test_mixed_state_source_change_still_requires_handoff():
    assert missing_handoff_documents({
        "state/seen_jobs.json", "src/storage.py", "docs/HANDOFF.md",
    }) == {"docs/STATUS.md", "docs/RELEASE_LOG.md"}


def test_all_three_updated_is_sufficient_for_presence_guard():
    assert not missing_handoff_documents({
        "src/eligibility.py", "tests/test_eligibility.py", *REQUIRED
    })
