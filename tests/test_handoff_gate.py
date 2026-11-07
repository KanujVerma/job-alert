"""Doc continuity checker must require a real handoff with implementation PRs."""
from scripts.check_handoff_docs import (
    REQUIRED,
    existing_handoff_documents,
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
        "tests/fixtures/applied_digital.html",
        "tests/fixtures/example.txt",
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


def test_deleting_or_renaming_all_three_docs_is_rejected():
    changed = {"src/filtering.py", *REQUIRED}
    assert missing_handoff_documents(changed, existing=set()) == set(REQUIRED)


def test_deleted_single_handoff_doc_still_fails_with_updated_diff():
    changed = {"main.py", *REQUIRED}
    present = set(REQUIRED) - {"docs/HANDOFF.md"}
    assert missing_handoff_documents(changed, existing=present) == {"docs/HANDOFF.md"}


def test_actual_regular_nonempty_docs_only(tmp_path):
    for path in REQUIRED:
        p = tmp_path / path
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("approved notes with evidence\n" * 12)
    assert existing_handoff_documents(tmp_path) == set(REQUIRED)

    missing = tmp_path / "docs/RELEASE_LOG.md"
    missing.unlink()
    assert "docs/RELEASE_LOG.md" not in existing_handoff_documents(tmp_path)

    (tmp_path / "docs/RELEASE_LOG.md").write_text("")
    assert "docs/RELEASE_LOG.md" not in existing_handoff_documents(tmp_path)


def test_symlink_handoff_cannot_bypass_guard(tmp_path):
    status = tmp_path / "docs/STATUS.md"
    status.parent.mkdir(parents=True, exist_ok=True)
    target = tmp_path / "other.md"
    target.write_text("x" * 400)
    status.symlink_to(target)
    assert "docs/STATUS.md" not in existing_handoff_documents(tmp_path)


def test_html_fixture_is_a_functional_change():
    path = "tests/fixtures/applied_digital.html"
    assert functional_source_changed(path)
    assert missing_handoff_documents({path}) == set(REQUIRED)


def test_git_mv_out_of_src_remains_detectable(tmp_path, monkeypatch):
    """Disable rename folding so both the original src/ and new paths appear."""
    import subprocess

    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=tmp_path, check=True, text=True,
            capture_output=True,
        )

    git("init", "-q")
    git("config", "user.name", "Jobbie Test")
    git("config", "user.email", "jobbie@example.invalid")
    (tmp_path / "src").mkdir()
    (tmp_path / "src/scheduler.py").write_text("def run(): return 42\n")
    git("add", ".")
    git("commit", "-q", "-m", "source")
    (tmp_path / "archive").mkdir()
    git("mv", "src/scheduler.py", "archive/scheduler.py")
    git("commit", "-q", "-m", "archive old source")
    monkeypatch.chdir(tmp_path)
    from scripts.check_handoff_docs import changed_paths
    files = changed_paths("HEAD~1", "HEAD")
    assert {"src/scheduler.py", "archive/scheduler.py"} <= files
    assert missing_handoff_documents(files) == set(REQUIRED)
