from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch
import pytest
import yaml

from src.health import (
    compute_run_diagnostics,
    record_run_heartbeat,
)
from src.storage import _empty_state
from main import do_run


class TestCIWorkflowVerification:
    """Requirement: GitHub Actions CI workflow running pytest and validating config on PRs and main."""

    def test_workflow_file_valid_yaml(self):
        wf_path = Path(".github/workflows/test.yml")
        assert wf_path.exists(), "CI workflow .github/workflows/test.yml must exist"

        content = wf_path.read_text()
        parsed = yaml.safe_load(content)
        assert parsed is not None
        assert parsed.get("name") == "Tests"

        # Triggers (handle 'on' string or PyYAML boolean True)
        triggers = parsed.get("on") or parsed.get(True) or {}
        assert "push" in triggers
        assert "pull_request" in triggers
        assert "main" in triggers["push"].get("branches", [])
        assert "main" in triggers["pull_request"].get("branches", [])

        # Jobs and steps
        jobs = parsed.get("jobs", {})
        assert "test" in jobs
        steps = jobs["test"].get("steps", [])
        step_runs = [s.get("run", "") for s in steps]
        assert any("pytest" in r for r in step_runs), "CI must execute pytest"
        assert any("main.py validate-config" in r for r in step_runs), "CI must validate configuration"


class TestSchedulerCadenceVerification:
    """Requirement: Measure and verify GitHub Actions scheduling gaps and drift vs configured cadence."""

    def test_nominal_cadence_detects_no_gap(self):
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["last_heartbeat"] = {
            "finished_at": (now - timedelta(minutes=15)).isoformat(),
        }

        start_time = now
        finish_time = now + timedelta(seconds=12)
        diagnostics = compute_run_diagnostics(
            state=state,
            start_time=start_time,
            finish_time=finish_time,
            configured_cadence_minutes=15,
            company_stats={"Salesforce": {"status": "ok", "matched": 1}},
            alert_count=1,
        )

        assert diagnostics["gap_since_last_run_seconds"] is not None
        # 15 minutes = ~900s
        assert 890 <= diagnostics["gap_since_last_run_seconds"] <= 910
        assert diagnostics["scheduler_gap_detected"] is False

    def test_excessive_gap_triggers_scheduler_gap_detected(self):
        now = datetime.now(timezone.utc)
        state = _empty_state()
        # Simulated 3-hour GitHub Actions cron delay
        state["last_heartbeat"] = {
            "finished_at": (now - timedelta(hours=3)).isoformat(),
        }

        start_time = now
        finish_time = now + timedelta(seconds=10)
        diagnostics = compute_run_diagnostics(
            state=state,
            start_time=start_time,
            finish_time=finish_time,
            configured_cadence_minutes=15,
            company_stats={"Salesforce": {"status": "ok", "matched": 1}},
            alert_count=1,
        )

        # 3 hours = 10,800 seconds > max(45*60, 15*3*60)
        assert diagnostics["gap_since_last_run_seconds"] >= 10700
        assert diagnostics["scheduler_gap_detected"] is True

    def test_heartbeat_history_persistence(self):
        now = datetime.now(timezone.utc)
        state = _empty_state()

        for i in range(15):
            diag = {
                "started_at": (now - timedelta(minutes=i * 15)).isoformat(),
                "duration_seconds": 10.0,
                "gap_since_last_run_seconds": 900.0,
            }
            record_run_heartbeat(state, diag, max_history=10)

        # Retains bounded history of at most 10 items
        history = state.get("heartbeat_history", [])
        assert len(history) == 10
        assert state["last_heartbeat"] == history[-1]


class TestDryRunZeroMutationVerification:
    """Requirement: Dry-run execution must produce zero mutations to state or external transports."""

    def test_dry_run_leaves_state_unmutated(self, tmp_path):
        import json
        state_file = tmp_path / "seen_jobs.json"
        config_file = tmp_path / "companies.yaml"
        config_file.write_text(
            """
defaults:
  schedule_minutes: 15
  state_path: """ + str(state_file) + """
  max_alerts_per_run: 25
filters:
  mode: new_grad_full_time
  freshness_hours: 48
companies:
  - name: Salesforce
    adapter: workday
    enabled: true
    config:
      domain: salesforce.wd12.myworkdayjobs.com
      path: External_Career_Site
"""
        )
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["first_run_completed_at"] = (now - timedelta(days=2)).isoformat()
        initial_json = json.dumps(state)
        state_file.write_text(initial_json)

        args = MagicMock(
            config=str(config_file),
            dry_run=True,  # Dry run!
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=False,
        )

        from src.models import Job
        dummy_job = Job(
            id="sf::job_1",
            company="Salesforce",
            title="Software Engineer, New Grad",
            location="San Francisco, CA",
            department="Engineering",
            category="Software",
            url="https://example.com/job/1",
            source_platform="workday",
            posted_at=now - timedelta(hours=12),
            detected_at=now,
            raw_text="Software Engineer, New Grad. San Francisco, CA.",
            role_type="new-grad",
            priority="normal",
            matched_keywords=(),
        )

        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock"}), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[dummy_job]), \
             patch("src.notifier.Notifier.send_job_alert") as mock_send_alert, \
             patch("src.notifier.Notifier.send_summary") as mock_send_summary:
            rc = do_run(args)
            assert rc == 0
            # Zero alerts or summaries sent during dry-run
            assert not mock_send_alert.called
            assert not mock_send_summary.called

        # State file remains completely unchanged
        assert state_file.read_text() == initial_json
