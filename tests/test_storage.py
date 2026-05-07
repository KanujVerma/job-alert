"""Tests for src/storage.py."""
from __future__ import annotations
import json
import os
from datetime import datetime, timezone

import pytest

from src.storage import (
    load_state,
    save_state,
    get_new_jobs,
    mark_seen,
    is_first_run,
    mark_first_run_complete,
)
from src.models import Job

_NOW = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_job(job_id: str, company: str = "Acme") -> Job:
    return Job(
        id=job_id,
        company=company,
        title="Software Engineer Intern",
        location="Remote",
        department=None,
        category=None,
        url="https://example.com/job/1",
        source_platform="workday",
        posted_at=None,
        detected_at=_NOW,
        raw_text="software engineer intern remote",
        role_type="internship",
        priority="normal",
        matched_keywords=("intern", "software"),
    )


class TestLoadState:
    def test_no_file_returns_empty_state(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        state = load_state(path)
        assert state["version"] == 1
        assert state["first_run_completed_at"] is None
        assert state["companies"] == {}

    def test_loads_existing_file(self, tmp_path):
        path = tmp_path / "state.json"
        data = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["abc123"]}},
        }
        path.write_text(json.dumps(data))
        state = load_state(str(path))
        assert state["first_run_completed_at"] == "2026-01-01T00:00:00+00:00"
        assert "Acme" in state["companies"]
        assert "abc123" in state["companies"]["Acme"]["seen_ids"]

    def test_corrupt_json_returns_empty_state(self, tmp_path):
        path = tmp_path / "state.json"
        path.write_text("{corrupt json{{")
        state = load_state(str(path))
        assert state["companies"] == {}


class TestSaveState:
    def test_round_trip(self, tmp_path):
        path = str(tmp_path / "state.json")
        original = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["id1"]}},
        }
        save_state(original, path)
        loaded = load_state(path)
        assert loaded["companies"]["Acme"]["seen_ids"] == ["id1"]

    def test_atomic_no_temp_file_left(self, tmp_path):
        path = str(tmp_path / "state.json")
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        save_state(state, path)
        # No .tmp files should remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_creates_parent_dirs(self, tmp_path):
        path = str(tmp_path / "nested" / "dir" / "state.json")
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        save_state(state, path)
        assert os.path.exists(path)


class TestGetNewJobs:
    def test_new_id_is_included(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("new-id-1"), make_job("new-id-2")]
        new = get_new_jobs(jobs, "Acme", state)
        assert len(new) == 2

    def test_known_id_is_excluded(self):
        state = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {"Acme": {"last_checked_at": None, "seen_ids": ["old-id"]}},
        }
        jobs = [make_job("old-id"), make_job("brand-new")]
        new = get_new_jobs(jobs, "Acme", state)
        assert len(new) == 1
        assert new[0].id == "brand-new"

    def test_empty_jobs_returns_empty(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        new = get_new_jobs([], "Acme", state)
        assert new == []


class TestMarkSeen:
    def test_adds_ids(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("id1"), make_job("id2")]
        mark_seen(jobs, "Acme", state)
        assert "id1" in state["companies"]["Acme"]["seen_ids"]
        assert "id2" in state["companies"]["Acme"]["seen_ids"]

    def test_updates_last_checked_at(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_seen([make_job("x")], "Acme", state)
        ts = state["companies"]["Acme"]["last_checked_at"]
        assert ts is not None
        # Should be a valid ISO timestamp
        datetime.fromisoformat(ts)

    def test_no_duplicate_ids(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        jobs = [make_job("same-id")]
        mark_seen(jobs, "Acme", state)
        mark_seen(jobs, "Acme", state)
        ids = state["companies"]["Acme"]["seen_ids"]
        assert ids.count("same-id") == 1

    def test_prunes_to_5000(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        # Pre-fill with 5000 IDs
        state["companies"]["Acme"] = {
            "last_checked_at": None,
            "seen_ids": [f"old-{i}" for i in range(5000)],
        }
        new_jobs = [make_job("brand-new")]
        mark_seen(new_jobs, "Acme", state)
        ids = state["companies"]["Acme"]["seen_ids"]
        assert len(ids) == 5000
        assert "brand-new" in ids

    def test_creates_company_entry_if_missing(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_seen([], "NewCo", state)
        assert "NewCo" in state["companies"]


class TestIsFirstRun:
    def test_true_when_none(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        assert is_first_run(state) is True

    def test_true_when_missing(self):
        state = {"version": 1, "companies": {}}
        assert is_first_run(state) is True

    def test_false_when_set(self):
        state = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {},
        }
        assert is_first_run(state) is False


class TestMarkFirstRunComplete:
    def test_sets_timestamp(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_first_run_complete(state)
        ts = state["first_run_completed_at"]
        assert ts is not None
        datetime.fromisoformat(ts)

    def test_is_first_run_becomes_false(self):
        state = {"version": 1, "first_run_completed_at": None, "companies": {}}
        mark_first_run_complete(state)
        assert is_first_run(state) is False
