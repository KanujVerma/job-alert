from unittest.mock import MagicMock
from src.adapters.base import BaseAdapter
from src.http import HTTPClient
from src.browser import BrowserClient


class _ConcreteAdapter(BaseAdapter):
    source_platform = "test"

    def fetch(self):
        return iter([])


def test_base_adapter_accepts_browser_kwarg():
    http = MagicMock(spec=HTTPClient)
    browser = MagicMock(spec=BrowserClient)
    adapter = _ConcreteAdapter("TestCo", {}, http, browser=browser)
    assert adapter.browser is browser


def test_base_adapter_browser_defaults_to_none():
    http = MagicMock(spec=HTTPClient)
    adapter = _ConcreteAdapter("TestCo", {}, http)
    assert adapter.browser is None
