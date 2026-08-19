"""Exit-code contract for main.do_run.

A scheduled bot that reports success while scraping nothing is worse than one
that fails: the failure is invisible until someone notices the alerts stopped.
These tests pin the backstop that makes a total outage visible to CI.
"""
from __future__ import annotations
import types
from unittest.mock import patch

import pytest

import main as m
from src.config import Config


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
