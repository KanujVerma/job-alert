"""Exit-code contract for main.do_run.

A scheduled bot that reports success while scraping nothing is worse than one
that fails: the failure is invisible until someone notices the alerts stopped.
These tests pin the backstop that makes a total outage visible to CI.
"""
from __future__ import annotations
import types
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch

import pytest

import main as m
from src.config import Config
from src.models import Job


class FailingAdapter:
    def __init__(self, name, cfg, http, browser=None):
        self.name = name

    def fetch(self):
        raise RuntimeError("simulated outage")


class EmptyAdapter:
    """Fetches fine, finds nothing. Not a failure — a site can legitimately have no jobs."""

    def __init__(self, name, cfg, http, browser=None):
        self.name = name

    def fetch(self):
        return []


def _make_job() -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        id="health-test-1", company="Acme", title="Software Engineering Intern",
        location="Remote", department="Engineering", category="Software",
        url="https://example.com/1", source_platform="stub", posted_at=None,
        detected_at=now, raw_text="software engineering intern",
        role_type="internship", priority="preferred",
        matched_keywords=("intern",),
    )


class HealthyAdapter:
    """Returns postings, so health stays green. Filters may still drop them all."""

    def __init__(self, name, cfg, http, browser=None):
        self.name = name

    def fetch(self):
        return [_make_job()]


def make_config(*company_names: str, adapter: str = "stub") -> Config:
    return Config(
        defaults={
            "request_delay_seconds": [0, 0],
            "state_path": "/nonexistent/state.json",
            "max_alerts_per_run": 25,
            "first_seen_ttl_days": 180,
        },
        filters={"freshness_hours": 48},
        companies=[
            {"name": n, "adapter": adapter, "enabled": True, "config": {}}
            for n in company_names
        ],
        user_agent="test-agent",
    )


def run_with(config: Config, registry: dict, company: str | None = None) -> int:
    args = types.SimpleNamespace(
        config="unused.yaml", company=company, dry_run=True,
        verbose=False, firehose_first_run=False, summary_first_run=False,
    )
    with patch.object(m, "load_config", return_value=config), \
         patch.dict(m.ADAPTER_REGISTRY, registry, clear=True):
        return m.do_run(args)


class TestTotalFailureIsVisible:
    def test_returns_nonzero_when_every_company_fetch_fails(self):
        rc = run_with(make_config("Acme", "Globex"), {"stub": FailingAdapter})
        assert rc != 0

    def test_returns_zero_when_at_least_one_company_succeeds(self):
        config = make_config("Acme", "Globex")
        config.companies[0]["adapter"] = "ok"
        rc = run_with(config, {"stub": FailingAdapter, "ok": EmptyAdapter})
        assert rc == 0

    def test_returns_nonzero_when_no_company_was_attempted(self):
        """A filter that matches nothing is a misconfiguration, not a clean run."""
        rc = run_with(make_config("Acme"), {"stub": EmptyAdapter}, company="__missing__")
        assert rc != 0


class TestKnownLimitation:
    def test_adapter_returning_empty_still_counts_as_success(self):
        """Documents the boundary: this backstop catches total outage, NOT a single
        adapter that degrades gracefully to []. Per-company health reporting is the
        separate fix for that."""
        rc = run_with(make_config("Acme"), {"stub": EmptyAdapter})
        assert rc == 0


class TestHealthNotifications:
    """A dead adapter must announce itself exactly once, on the channel that is read."""

    def _run_with_notifier(self, config, registry, notifier, state):
        args = types.SimpleNamespace(
            config="unused.yaml", company=None, dry_run=False,
            verbose=False, firehose_first_run=False, summary_first_run=False,
        )
        with patch.object(m, "load_config", return_value=config), \
             patch.dict(m.ADAPTER_REGISTRY, registry, clear=True), \
             patch.object(m, "Notifier", return_value=notifier), \
             patch.object(m, "load_state", return_value=state), \
             patch.object(m, "save_state"), \
             patch.dict(m.os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/hook"}):
            return m.do_run(args)

    def _stale_state(self):
        """A company last seen non-empty two days ago — well past the 24h threshold."""
        long_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        return {
            "version": 2,
            "first_run_completed_at": long_ago,
            "companies": {
                "Acme": {
                    "last_checked_at": long_ago,
                    "seen_jobs": {},
                    "health": {
                        "first_tracked_at": long_ago,
                        "last_nonempty_at": long_ago,
                        "alerted": False,
                    },
                }
            },
        }

    def test_dead_company_sends_one_health_notice(self):
        notifier = MagicMock()
        notifier.send_summary.return_value = True
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": EmptyAdapter}, notifier, state
        )

        assert notifier.send_summary.call_count == 1
        assert state["companies"]["Acme"]["health"]["alerted"] is True

    def test_alerted_not_set_when_discord_send_fails(self):
        """Otherwise a failed post silently burns the single notice you get."""
        notifier = MagicMock()
        notifier.send_summary.return_value = False
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": EmptyAdapter}, notifier, state
        )

        assert state["companies"]["Acme"]["health"]["alerted"] is False

    def test_healthy_company_sends_no_health_notice(self):
        notifier = MagicMock()
        notifier.send_summary.return_value = True
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": HealthyAdapter}, notifier, state
        )

        assert notifier.send_summary.call_count == 0


class TestCrossCompanyDuplicateAlerts:
    """One posting must produce one Discord alert, even when two companies carry it.

    companies.yaml has both `Microsoft` (eightfold_pcsx) and `Microsoft Research`
    (microsoft_research). They are NOT disjoint: 75 of the 99 MSR postings have
    an apply URL of https://apply.careers.microsoft.com/careers/job/<id> — the
    exact ids the PCSX adapter enumerates.

    Nothing downstream can collapse them. seen_jobs is keyed per company
    (src/storage.py) and make_job_id namespaces by company + platform, so the
    two get different ids by construction and both alert. The apply URL is the
    only thing that identifies the underlying posting.
    """

    SHARED_URL = "https://apply.careers.microsoft.com/careers/job/1970393556867858"

    def _adapter_yielding(self, company_label: str, platform: str, url: str):
        outer = self

        class _Adapter:
            def __init__(self, name, cfg, http, browser=None):
                self.name = name

            def fetch(self):
                now = datetime.now(timezone.utc)
                return [Job(
                    id=f"{company_label}::{platform}::x", company=company_label,
                    title="AI Software Engineering Intern", location="Redmond, WA",
                    department="Software Engineering", category=None, url=url,
                    source_platform=platform, posted_at=now, detected_at=now,
                    raw_text="ai software engineering intern redmond wa",
                    role_type="internship", priority="preferred",
                    matched_keywords=("intern",),
                )]
        return _Adapter

    def _run(self, config, registry, notifier):
        args = types.SimpleNamespace(
            config="unused.yaml", company=None, dry_run=False,
            verbose=False, firehose_first_run=False, summary_first_run=False,
        )
        # make_config's filters are minimal; without a tech keyword the pipeline
        # drops the job before it can ever reach the alerting path.
        config.filters = {
            "freshness_hours": 48,
            "early_career_keywords": ["intern"],
            "technical_role_keywords": ["software engineer", "software engineering"],
        }
        state = {"version": 2, "first_run_completed_at":
                 (datetime.now(timezone.utc) - timedelta(days=2)).isoformat(),
                 "companies": {}}
        with patch.object(m, "load_config", return_value=config), \
             patch.dict(m.ADAPTER_REGISTRY, registry, clear=True), \
             patch.object(m, "Notifier", return_value=notifier), \
             patch.object(m, "load_state", return_value=state), \
             patch.object(m, "save_state"), \
             patch.dict(m.os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/hook"}):
            m.do_run(args)

    def test_same_apply_url_alerts_once_across_two_companies(self):
        notifier = MagicMock()
        notifier.send_job_alert.return_value = True
        notifier.send_summary.return_value = True

        config = make_config("Microsoft", "Microsoft Research")
        config.companies[0]["adapter"] = "pcsx"
        config.companies[1]["adapter"] = "msr"
        registry = {
            "pcsx": self._adapter_yielding("Microsoft", "eightfold_pcsx", self.SHARED_URL),
            "msr": self._adapter_yielding("Microsoft Research", "microsoft_research", self.SHARED_URL),
        }
        self._run(config, registry, notifier)

        assert notifier.send_job_alert.call_count == 1, (
            f"one posting produced {notifier.send_job_alert.call_count} Discord alerts"
        )

    def test_different_urls_both_still_alert(self):
        """The guard must not collapse genuinely distinct postings."""
        notifier = MagicMock()
        notifier.send_job_alert.return_value = True
        notifier.send_summary.return_value = True

        config = make_config("Microsoft", "Microsoft Research")
        config.companies[0]["adapter"] = "pcsx"
        config.companies[1]["adapter"] = "msr"
        registry = {
            "pcsx": self._adapter_yielding("Microsoft", "eightfold_pcsx", self.SHARED_URL),
            "msr": self._adapter_yielding(
                "Microsoft Research", "microsoft_research",
                "https://www.microsoft.com/en-us/research/job/999"),
        }
        self._run(config, registry, notifier)

        assert notifier.send_job_alert.call_count == 2
