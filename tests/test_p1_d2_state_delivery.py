from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
import pytest
import requests

from src.models import Job
from src.filtering import apply_filter_pipeline
from src.adapters.lever import LeverAdapter
from src.http import HTTPClient
from src.storage import (
    _empty_state,
    migrate_state,
    is_backfill_pending,
    mark_backfill_completed,
    get_backfill_candidates,
    is_url_alerted,
    record_alerted_url,
    POLICY_VERSION,
)
from main import do_run

_NOW = datetime(2026, 11, 4, 18, 0, 0, tzinfo=timezone.utc)


def _make_dummy_job(jid: str, posted_days_ago: float, company: str = "Apple") -> Job:
    return Job(
        id=f"{company.lower()}::{jid}",
        company=company,
        title="Software Engineer, New Grad",
        location="Cupertino, CA",
        department="Engineering",
        category="Software",
        url=f"https://example.com/job/{jid}",
        source_platform="workday",
        posted_at=_NOW - timedelta(days=posted_days_ago),
        detected_at=_NOW,
        raw_text="Software Engineer, New Grad. 0-2 years experience. December 2026 graduation. Cupertino, CA.",
        role_type="new-grad",
        priority="normal",
        matched_keywords=(),
    )


class TestBackfillFreshnessDecoupling:
    """Requirement: 7-day backfill must not be dropped by the standard 48-hour freshness filter."""

    def test_five_day_old_job_passes_under_backfill_freshness(self):
        job = _make_dummy_job("job_5d", posted_days_ago=5.0)

        # Standard 48-hour filter drops it
        normal_filters = {"mode": "new_grad_full_time", "freshness_hours": 48}
        filtered_normal, reasons_normal = apply_filter_pipeline(job, normal_filters, {})
        assert filtered_normal is None
        assert any("freshness" in r for r in reasons_normal)

        # Decoupled backfill filter (7 days = 168 hours) retains it
        backfill_filters = dict(normal_filters, freshness_hours=7 * 24.0)
        filtered_bf, reasons_bf = apply_filter_pipeline(job, backfill_filters, {})
        assert filtered_bf is not None
        assert filtered_bf.role_type == "new-grad"

        # And get_backfill_candidates includes it
        state = _empty_state()
        candidates = get_backfill_candidates([filtered_bf], state, _NOW, lookback_days=7)
        assert len(candidates) == 1
        assert candidates[0].id == job.id


class TestConfirmedDeliveryInvariant:
    """Requirement: Never mark jobs alerted unless delivery is confirmed."""

    def test_missing_credentials_does_not_mark_alerted(self, tmp_path):
        state_file = tmp_path / "seen_jobs.json"
        config_file = tmp_path / "companies.yaml"

        # Config with one company
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

        state = _empty_state()
        # Mark first run complete so alerts would normally trigger
        state["first_run_completed_at"] = (_NOW - timedelta(days=1)).isoformat()
        import json
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_fresh", posted_days_ago=0.5, company="Salesforce")

        # Mock adapter to return mock_job, but NO webhook url in environment
        args = MagicMock(
            config=str(config_file),
            dry_run=False,
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=False,
        )

        with patch.dict(os.environ, {}, clear=True), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]):
            rc = do_run(args)
            assert rc == 0

        # Read back saved state
        reloaded = json.loads(state_file.read_text())
        seen_entry = reloaded["companies"]["Salesforce"]["seen_jobs"][mock_job.id]
        # Crucial invariant: alerted MUST be False because notifier was None (no credentials)
        assert seen_entry["alerted"] is False
        assert not is_url_alerted(mock_job.url, reloaded)

    def test_failed_send_does_not_mark_alerted(self, tmp_path):
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
        state = _empty_state()
        state["first_run_completed_at"] = (_NOW - timedelta(days=1)).isoformat()
        import json
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_fresh_fail", posted_days_ago=0.5, company="Salesforce")
        args = MagicMock(
            config=str(config_file),
            dry_run=False,
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=False,
        )

        # Mock notifier to fail (return False)
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock"}), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]), \
             patch("src.notifier.Notifier.send_job_alert", return_value=False):
            rc = do_run(args)
            assert rc == 0

        reloaded = json.loads(state_file.read_text())
        seen_entry = reloaded["companies"]["Salesforce"]["seen_jobs"][mock_job.id]
        # Alert was unconfirmed -> must stay False
        assert seen_entry["alerted"] is False
        assert not is_url_alerted(mock_job.url, reloaded)


class TestBackfillDeliveryAndRerun:
    """Requirement: Backfill summary delivery confirmation and safe rerunnability."""

    def test_backfill_delivery_failure_leaves_backfill_pending(self, tmp_path):
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
        state = _empty_state()
        state["first_run_completed_at"] = (_NOW - timedelta(days=2)).isoformat()
        # Backfill pending
        state["migrations"] = {
            POLICY_VERSION: {
                "started_at": (_NOW - timedelta(days=1)).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        }
        state["policy_version"] = POLICY_VERSION
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_bf_fail", posted_days_ago=4.0, company="Salesforce")
        args = MagicMock(
            config=str(config_file),
            dry_run=False,
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=False,
        )

        # Webhook set, but send_summary fails
        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock"}), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]), \
             patch("src.notifier.Notifier.send_summary", return_value=False):
            rc = do_run(args)
            assert rc == 0

        reloaded = json.loads(state_file.read_text())
        # Backfill must still be pending!
        assert is_backfill_pending(reloaded, POLICY_VERSION) is True
        assert not is_url_alerted(mock_job.url, reloaded)

    def test_backfill_delivery_success_completes_backfill(self, tmp_path):
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
        state = _empty_state()
        state["first_run_completed_at"] = (_NOW - timedelta(days=2)).isoformat()
        state["migrations"] = {
            POLICY_VERSION: {
                "started_at": (_NOW - timedelta(days=1)).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        }
        state["policy_version"] = POLICY_VERSION
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_bf_success", posted_days_ago=4.0, company="Salesforce")
        args = MagicMock(
            config=str(config_file),
            dry_run=False,
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=False,
        )

        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock"}), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]), \
             patch("src.notifier.Notifier.send_summary", return_value=True):
            rc = do_run(args)
            assert rc == 0

        reloaded = json.loads(state_file.read_text())
        # Backfill completed!
        assert is_backfill_pending(reloaded, POLICY_VERSION) is False
        assert is_url_alerted(mock_job.url, reloaded) is True

    def test_rerun_backfill_flag_re_triggers_backfill(self, tmp_path):
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
        state = _empty_state()
        state["first_run_completed_at"] = (_NOW - timedelta(days=2)).isoformat()
        # Backfill was previously marked completed
        mark_backfill_completed(state, POLICY_VERSION)
        assert is_backfill_pending(state, POLICY_VERSION) is False
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_rerun", posted_days_ago=3.0, company="Salesforce")
        args = MagicMock(
            config=str(config_file),
            dry_run=False,
            verbose=False,
            company="Salesforce",
            firehose_first_run=False,
            summary_first_run=False,
            rerun_backfill=True,  # Forced rerun
        )

        with patch.dict(os.environ, {"DISCORD_WEBHOOK_URL": "https://discord.com/api/webhooks/mock"}), \
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]), \
             patch("src.notifier.Notifier.send_summary", return_value=True) as mock_send_summary:
            rc = do_run(args)
            assert rc == 0
            # Summary was sent
            assert mock_send_summary.called


class TestPlaidLeverErrorClassification:
    """Requirement: Plaid HTTP 404 must be reported as a failed adapter, not a healthy zero source."""

    def test_lever_adapter_raises_on_http_404(self):
        http = MagicMock(spec=HTTPClient)
        http.get.side_effect = requests.HTTPError("404 Client Error: Not Found for url: https://api.lever.co/v0/postings/plaid?mode=json")
        adapter = LeverAdapter(company="Plaid", config={"slug": "plaid"}, http=http)

        with pytest.raises(requests.HTTPError) as exc_info:
            list(adapter.fetch())
        assert "404" in str(exc_info.value)
