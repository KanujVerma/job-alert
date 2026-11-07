#!/usr/bin/env python3
"""Fail a functional pull request when its durable agent handoff is stale.

This guard checks file presence, NOT statement truth. Reviewers must inspect
code/CI/live evidence and compare it to the changed Markdown. The bot's normal
state-only commits are explicitly exempt.
"""
from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path, PurePosixPath

REQUIRED = frozenset({
    "docs/STATUS.md",
    "docs/HANDOFF.md",
    "docs/RELEASE_LOG.md",
})

FUNCTIONAL_ROOT_FILES = frozenset({
    "main.py",
    "companies.yaml",
    "requirements.txt",
    "requirements-dev.txt",
})


def functional_source_changed(path: str) -> bool:
    """True for actual implementation/test/dependency changes, not bot state."""
    path = str(PurePosixPath(path))
    if path in FUNCTIONAL_ROOT_FILES:
        return True
    if path.startswith(("src/", "tests/")):
        return path.endswith((".py", ".json", ".yaml", ".yml", ".toml"))
    if path.startswith("scripts/"):
        return path.endswith((".py", ".sh", ".ts", ".js"))
    if path.startswith(".github/workflows/"):
        return path.endswith((".yml", ".yaml"))
    return False


def existing_handoff_documents(root: Path) -> set[str]:
    """Return actual, non-empty regular handoff docs from the PR checkout.

    A deleted, renamed, symlinked, or empty document MUST fail the PR gate
    even when its old path appears in "git diff --name-only" as changed.
    """
    found: set[str] = set()
    for path in REQUIRED:
        doc = root / path
        if doc.is_file() and not doc.is_symlink() and doc.stat().st_size >= 200:
            found.add(path)
    return found


def missing_handoff_documents(
    paths: set[str], *, existing: set[str] | None = None
) -> set[str]:
    """Required docs must both be changed AND exist in the reviewed tree.

    "existing=None" supports pure diff-based unit cases. The executable CLI
    always passes existing_handoff_documents(Path.cwd()) for real PR safety.
    """
    if not any(functional_source_changed(p) for p in paths):
        return set()
    if existing is None:
        existing = set(REQUIRED)
    return (set(REQUIRED) - paths) | (set(REQUIRED) - existing)


def changed_paths(base_ref: str, head_ref: str) -> set[str]:
    """Compare full PR diff from merge base. Fail closed if checkout is shallow."""
    result = subprocess.run(
        ["git", "diff", "--name-only", f"{base_ref}...{head_ref}"],
        check=True,
        capture_output=True,
        text=True,
    )
    return set(result.stdout.splitlines())


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", default="origin/main")
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args(argv)
    try:
        paths = changed_paths(args.base, args.head)
    except (subprocess.CalledProcessError, OSError) as error:
        print("Documentation continuity check could not compute PR diff.", file=sys.stderr)
        print(error, file=sys.stderr)
        print("Ensure actions/checkout uses fetch-depth: 0 and base ref exists.", file=sys.stderr)
        return 2
    missing = sorted(missing_handoff_documents(
        paths, existing=existing_handoff_documents(Path.cwd())
    ))
    if missing:
        print("Functional code/config/CI changed without required handoff updates:", file=sys.stderr)
        for path in missing:
            print(f"  - {path}", file=sys.stderr)
        print(
            "Update all three documents in THIS PR with actual behavior, CI evidence, "
            "remaining blockers, and next agent task (see docs/MAINTENANCE.md).",
            file=sys.stderr,
        )
        return 1
    print(f"Documentation continuity PASS ({len(paths)} changed files).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
