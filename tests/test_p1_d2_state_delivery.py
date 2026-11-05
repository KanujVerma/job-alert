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

def _make_dummy_job(jid: str, posted_days_ago: float, company: str = "Apple", now: datetime | None = None) -> Job:
    ref = now or datetime.now(timezone.utc)
    return Job(
        id=f"{company.lower()}::{jid}",
        company=company,
        title="Software Engineer, New Grad",
        location="Cupertino, CA",
        department="Engineering",
        category="Software",
        url=f"https://example.com/job/{jid}",
        source_platform="workday",
        posted_at=ref - timedelta(days=posted_days_ago),
        detected_at=ref,
        raw_text="Software Engineer, New Grad. 0-2 years experience. December 2026 graduation. Cupertino, CA.",
        role_type="new-grad",
        priority="normal",
        matched_keywords=(),
    )


class TestBackfillFreshnessDecoupling:
    """Requirement: 7-day backfill must not be dropped by the standard 48-hour freshness filter."""

    def test_five_day_old_job_passes_under_backfill_freshness(self):
        now = datetime.now(timezone.utc)
        job = _make_dummy_job("job_5d", posted_days_ago=5.0, now=now)

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
        candidates = get_backfill_candidates([filtered_bf], state, now, lookback_days=7)
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

        now = datetime.now(timezone.utc)
        state = _empty_state()
        # Mark first run complete so alerts would normally trigger
        state["first_run_completed_at"] = (now - timedelta(days=1)).isoformat()
        import json
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_fresh", posted_days_ago=0.5, company="Salesforce", now=now)

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
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["first_run_completed_at"] = (now - timedelta(days=1)).isoformat()
        import json
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_fresh_fail", posted_days_ago=0.5, company="Salesforce", now=now)
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
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["first_run_completed_at"] = (now - timedelta(days=2)).isoformat()
        # Backfill pending
        state["migrations"] = {
            POLICY_VERSION: {
                "started_at": (now - timedelta(days=1)).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        }
        state["policy_version"] = POLICY_VERSION
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_bf_fail", posted_days_ago=4.0, company="Salesforce", now=now)
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
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["first_run_completed_at"] = (now - timedelta(days=2)).isoformat()
        state["migrations"] = {
            POLICY_VERSION: {
                "started_at": (now - timedelta(days=1)).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        }
        state["policy_version"] = POLICY_VERSION
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_bf_success", posted_days_ago=4.0, company="Salesforce", now=now)
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
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["first_run_completed_at"] = (now - timedelta(days=2)).isoformat()
        # Backfill was previously marked completed
        mark_backfill_completed(state, POLICY_VERSION)
        assert is_backfill_pending(state, POLICY_VERSION) is False
        state_file.write_text(json.dumps(state))

        mock_job = _make_dummy_job("job_rerun", posted_days_ago=3.0, company="Salesforce", now=now)
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


class TestBackfillSeparationFromIndividualAlerts:
    """Requirement: Historical postings (48-168h) must NOT trigger individual alerts or exhaust the per-run alert cap."""

    def test_historical_postings_kept_out_of_individual_alerts(self, tmp_path):
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
        state["migrations"] = {
            POLICY_VERSION: {
                "started_at": (now - timedelta(days=1)).isoformat(),
                "completed_at": None,
                "backfill_completed": False,
            }
        }
        state["policy_version"] = POLICY_VERSION
        state_file.write_text(json.dumps(state))

        job_fresh = _make_dummy_job("fresh_role", posted_days_ago=0.5, company="Salesforce", now=now)
        job_historical = _make_dummy_job("hist_role", posted_days_ago=4.5, company="Salesforce", now=now)

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
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[job_fresh, job_historical]), \
             patch("src.notifier.Notifier.send_job_alert", return_value=True) as mock_send_alert, \
             patch("src.notifier.Notifier.send_summary", return_value=True) as mock_send_summary:
            rc = do_run(args)
            assert rc == 0

            # Only the fresh role receives an individual alert!
            assert mock_send_alert.call_count == 1
            alerted_job = mock_send_alert.call_args[0][0]
            assert alerted_job.id == job_fresh.id

            # The backfill summary receives the historical role
            assert mock_send_summary.called
            summary_kwargs = mock_send_summary.call_args[1]
            assert "Phase 1 Policy Backfill" in summary_kwargs.get("title", "")
            assert "hist_role" in summary_kwargs.get("description", "")


class TestReviewQueuePreservation:
    """Requirement: Preserve classification evidence and prevent false pruning of review queue items."""

    def test_clean_review_queue_preserves_department_tech_evidence(self):
        from src.storage import clean_review_queue, record_review_job
        now = datetime.now(timezone.utc)
        state = _empty_state()
        job = Job(
            id="dept_swe_1",
            company="Salesforce",
            title="Engineer I",
            location="San Francisco, CA",
            department="Software Engineering",
            category=None,
            url="https://example.com/job/1",
            source_platform="workday",
            posted_at=None,
            detected_at=now,
            raw_text="Engineer I. 3 years required. San Francisco, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        record_review_job(state, job, ["eligibility: needs_review: TECHNICAL_ROLE, UNCLEAR_EXPERIENCE"], now)

        # Cleaning review queue must NOT prune this item!
        pruned = clean_review_queue(state)
        assert pruned == 0
        assert "dept_swe_1" in state["review_queue"]

    def test_clean_review_queue_preserves_legacy_item_with_prior_tech(self):
        from src.storage import clean_review_queue
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["review_queue"]["legacy_item"] = {
            "company": "Salesforce",
            "title": "Engineer I",
            "location": "San Francisco, CA",
            "department": None,
            "category": None,
            "reasons": ["eligibility: needs_review: TECHNICAL_ROLE, UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        # Legacy item lacked department in state, but had TECHNICAL_ROLE reason -> must be preserved!
        pruned = clean_review_queue(state)
        assert pruned == 0
        assert "legacy_item" in state["review_queue"]

    def test_clean_review_queue_prunes_definitive_exclusions(self):
        from src.storage import clean_review_queue
        now = datetime.now(timezone.utc)
        state = _empty_state()
        state["review_queue"]["senior_role"] = {
            "company": "Salesforce",
            "title": "Senior Software Engineer",
            "location": "San Francisco, CA",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }
        state["review_queue"]["intern_role"] = {
            "company": "Salesforce",
            "title": "Software Engineering Intern",
            "location": "San Francisco, CA",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }
        state["review_queue"]["non_us_role"] = {
            "company": "Salesforce",
            "title": "Software Engineer",
            "location": "London, United Kingdom",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        pruned = clean_review_queue(state)
        assert pruned == 3
        assert len(state["review_queue"]) == 0

    def test_stale_review_job_preserved_on_refetch(self, tmp_path):
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
        state["first_run_completed_at"] = (now - timedelta(days=5)).isoformat()
        # Pre-seed a review job that is already in review_queue
        jid = "salesforce::swe_ambig"
        state["review_queue"][jid] = {
            "company": "Salesforce",
            "title": "Software Engineer II",
            "location": "San Francisco, CA",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": (now - timedelta(days=3)).isoformat(),
            "last_seen": (now - timedelta(days=3)).isoformat(),
        }
        state_file.write_text(json.dumps(state))

        # Re-fetch the same job, now 3 days old (> 48 hours freshness threshold)
        mock_job = Job(
            id=jid,
            company="Salesforce",
            title="Software Engineer II",
            location="San Francisco, CA",
            department="Engineering",
            category="Software",
            url="https://example.com/job/swe_ambig",
            source_platform="workday",
            posted_at=now - timedelta(days=3.0),
            detected_at=now,
            raw_text="Software Engineer II. San Francisco, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )

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
             patch("src.adapters.workday.WorkdayAdapter.fetch", return_value=[mock_job]):
            rc = do_run(args)
            assert rc == 0

        # Reload state: the review job must STILL be present in review_queue!
        reloaded = json.loads(state_file.read_text())
        assert jid in reloaded["review_queue"]
        assert reloaded["review_queue"][jid]["company"] == "Salesforce"

    def test_review_digest_ranks_nonpositive_scores_when_capacity_allows(self):
        from src.storage import get_daily_review_digest
        now = datetime.now(timezone.utc)
        state = _empty_state()
        # Item 1: High positive score (Apple Swe 1 in SF) -> score > 0
        state["review_queue"]["job_pos"] = {
            "company": "Apple",
            "title": "Software Engineer 1",
            "location": "San Francisco, CA",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }
        # Item 2: Mixed US/Canada location with penalty -> score < 0 (Apple SWE II SF + Toronto = 10 + 8 + 5 - 30 = -7)
        state["review_queue"]["job_mixed"] = {
            "company": "Apple",
            "title": "Software Engineer II",
            "location": "San Francisco, CA; Toronto, Canada",
            "reasons": ["eligibility: needs_review: UNCLEAR_EXPERIENCE"],
            "first_seen": now.isoformat(),
            "last_seen": now.isoformat(),
        }

        # Daily review digest with cap=10 must include BOTH items, ranked by score!
        res = get_daily_review_digest(state, now, cap=10)
        assert res is not None
        items, total = res
        assert total == 2
        assert len(items) == 2
        # Highest score first
        assert items[0]["title"] == "Software Engineer 1"
        assert items[1]["title"] == "Software Engineer II"
