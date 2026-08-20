"""Does any enabled company need a browser?

The workflow installs Chromium on every one of its 96 daily runs. That cost is
only justified when some enabled company actually needs a browser, so the app
has to be able to answer the question itself — in one place, from the adapter
classes rather than from a config flag an adapter author can forget to set.
"""
from __future__ import annotations
import types
from unittest.mock import patch

import pytest

import main as m
from src.adapters import ADAPTER_REGISTRY, browser_required
from src.adapters.base import BaseAdapter
from src.adapters.eightfold_playwright import EightfoldPlaywrightAdapter
from src.adapters.phenom_people import PhenomPeopleAdapter
from src.config import Config


class _BrowserAdapter(BaseAdapter):
    source_platform = "needs-browser"
    requires_browser = True

    def fetch(self):
        return iter([])


class _PlainAdapter(BaseAdapter):
    source_platform = "no-browser"

    def fetch(self):
        return iter([])


_REGISTRY = {"browser": _BrowserAdapter, "plain": _PlainAdapter}


def company(name: str = "Acme", **kwargs) -> dict:
    c = {"name": name, "adapter": "plain", "config": {}}
    c.update(kwargs)
    return c


class TestRequiresBrowserDeclaration:
    """The declaration lives on the class, so a new adapter inherits the safe default."""

    def test_base_adapter_defaults_to_not_requiring_a_browser(self):
        assert BaseAdapter.requires_browser is False
        assert _PlainAdapter.requires_browser is False

    def test_the_two_adapters_that_use_self_browser_declare_it(self):
        assert PhenomPeopleAdapter.requires_browser is True
        assert EightfoldPlaywrightAdapter.requires_browser is True

    def test_every_other_registered_adapter_does_not(self):
        needing = {
            key for key, cls in ADAPTER_REGISTRY.items() if cls.requires_browser
        }
        assert needing == {"phenom_people", "eightfold_playwright"}


class TestBrowserRequired:
    def test_no_companies(self):
        assert browser_required([], _REGISTRY) is False

    def test_enabled_company_whose_adapter_requires_a_browser(self):
        assert browser_required([company(adapter="browser")], _REGISTRY) is True

    def test_missing_enabled_key_means_enabled(self):
        c = company(adapter="browser")
        c.pop("enabled", None)
        assert browser_required([c], _REGISTRY) is True

    def test_disabled_company_whose_adapter_requires_a_browser(self):
        """The whole point: a disabled Snowflake must not cost a Chromium install."""
        assert (
            browser_required([company(adapter="browser", enabled=False)], _REGISTRY)
            is False
        )

    def test_legacy_use_playwright_flag_still_counts(self):
        c = company(adapter="plain", config={"use_playwright": True})
        assert browser_required([c], _REGISTRY) is True

    def test_disabled_company_with_legacy_flag_does_not_count(self):
        c = company(adapter="plain", enabled=False, config={"use_playwright": True})
        assert browser_required([c], _REGISTRY) is False

    def test_unknown_adapter_key_does_not_raise(self):
        assert browser_required([company(adapter="not-registered")], _REGISTRY) is False

    def test_missing_adapter_key_does_not_raise(self):
        c = company()
        c.pop("adapter")
        assert browser_required([c], _REGISTRY) is False

    def test_missing_config_key_does_not_raise(self):
        c = company()
        c.pop("config")
        assert browser_required([c], _REGISTRY) is False

    def test_one_needy_company_among_many_is_enough(self):
        companies = [
            company("A"),
            company("B", adapter="browser"),
            company("C"),
        ]
        assert browser_required(companies, _REGISTRY) is True

    def test_all_plain_companies(self):
        assert browser_required([company("A"), company("B")], _REGISTRY) is False


class TestDoRunUsesBrowserRequired:
    """Rewiring main.py must not change when a BrowserClient gets constructed."""

    def _run(self, companies: list[dict], registry: dict):
        config = Config(
            defaults={
                "request_delay_seconds": [0, 0],
                "state_path": "/nonexistent/state.json",
                "max_alerts_per_run": 25,
                "first_seen_ttl_days": 180,
            },
            filters={"freshness_hours": 48},
            companies=companies,
            user_agent="test-agent",
        )
        args = types.SimpleNamespace(
            config="unused.yaml", company=None, dry_run=True,
            verbose=False, firehose_first_run=False, summary_first_run=False,
        )
        with patch.object(m, "load_config", return_value=config), \
             patch.dict(m.ADAPTER_REGISTRY, registry, clear=True), \
             patch.object(m, "BrowserClient") as browser_cls:
            m.do_run(args)
        return browser_cls

    def test_browser_constructed_when_adapter_declares_it(self):
        browser_cls = self._run([company(adapter="browser")], _REGISTRY)
        assert browser_cls.call_count == 1

    def test_browser_not_constructed_when_nothing_needs_one(self):
        browser_cls = self._run([company(adapter="plain")], _REGISTRY)
        assert browser_cls.call_count == 0

    def test_browser_still_constructed_for_the_legacy_flag(self):
        c = company(adapter="plain", config={"use_playwright": True})
        browser_cls = self._run([c], _REGISTRY)
        assert browser_cls.call_count == 1


class TestNeedsBrowserCommand:
    """The workflow reads stdout verbatim, so it must be exactly `true` / `false`."""

    def _invoke(self, companies: list[dict]) -> int:
        config = Config(
            defaults={}, filters={}, companies=companies, user_agent="test-agent"
        )
        args = types.SimpleNamespace(config="unused.yaml")
        with patch.object(m, "load_config", return_value=config):
            return m.cmd_needs_browser(args)

    def test_prints_true_and_exits_zero(self, capsys):
        rc = self._invoke([{"name": "Snow", "adapter": "phenom_people", "config": {}}])
        assert rc == 0
        assert capsys.readouterr().out == "true\n"

    def test_prints_false_and_exits_zero(self, capsys):
        rc = self._invoke([{"name": "Acme", "adapter": "workday", "config": {}}])
        assert rc == 0
        assert capsys.readouterr().out == "false\n"

    def test_disabled_browser_company_prints_false(self, capsys):
        rc = self._invoke(
            [{"name": "Snow", "adapter": "phenom_people", "enabled": False,
              "config": {"use_playwright": True}}]
        )
        assert rc == 0
        assert capsys.readouterr().out == "false\n"

    def test_subcommand_is_wired_and_respects_global_config_flag(self, capsys):
        """`--config` is a global flag (main.py), not a per-subcommand one."""
        config = Config(
            defaults={}, filters={},
            companies=[{"name": "Snow", "adapter": "phenom_people", "config": {}}],
            user_agent="test-agent",
        )
        seen: list[str] = []

        def fake_load_config(path):
            seen.append(path)
            return config

        argv = ["job-alert", "--config", "other.yaml", "needs-browser"]
        with patch.object(m.sys, "argv", argv), \
             patch.object(m, "load_config", side_effect=fake_load_config):
            with pytest.raises(SystemExit) as exc:
                m.main()

        assert exc.value.code == 0
        assert seen == ["other.yaml"]
        assert capsys.readouterr().out == "true\n"
