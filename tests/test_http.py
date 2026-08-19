"""Tests for HTTPClient retry behaviour in src/http.py."""
from __future__ import annotations
from unittest.mock import MagicMock, patch

import pytest
import requests

from src.http import HTTPClient


def make_resp(status: int, headers: dict | None = None) -> MagicMock:
    """A response stub that raises HTTPError from raise_for_status like requests does."""
    resp = MagicMock(spec=requests.Response)
    resp.status_code = status
    resp.headers = headers or {}
    resp.ok = status < 400

    def raise_for_status():
        if status >= 400:
            raise requests.HTTPError(f"{status} Client Error", response=resp)

    resp.raise_for_status.side_effect = raise_for_status
    return resp


def make_client(responses: list) -> tuple[HTTPClient, MagicMock]:
    client = HTTPClient(user_agent="test-agent", timeout=15, max_retries=3)
    session = MagicMock()
    session.request.side_effect = responses
    client.session = session
    return client, session


class TestRateLimitRetry:
    def test_retries_429_then_returns_success(self):
        """A 429 is transient; the client must retry rather than give up on the company."""
        client, session = make_client([make_resp(429), make_resp(200)])

        with patch("src.http.time.sleep"):
            resp = client.get("https://example.com/jobs")

        assert resp.status_code == 200
        assert session.request.call_count == 2

    def test_429_honors_retry_after_header(self):
        """Ignoring Retry-After is how you get escalated from throttled to banned."""
        client, _ = make_client([make_resp(429, {"Retry-After": "7"}), make_resp(200)])

        with patch("src.http.time.sleep") as sleep:
            client.get("https://example.com/jobs")

        assert sleep.call_args_list[0].args[0] == 7.0

    def test_429_retry_after_is_capped(self):
        """An hour-long Retry-After must not park the run past its CI step budget."""
        client, _ = make_client([make_resp(429, {"Retry-After": "3600"}), make_resp(200)])

        with patch("src.http.time.sleep") as sleep:
            client.get("https://example.com/jobs")

        assert sleep.call_args_list[0].args[0] <= 30.0

    def test_429_on_every_attempt_finally_raises(self):
        """Exhausted retries must surface, not silently return a throttled response."""
        client, session = make_client([make_resp(429) for _ in range(4)])

        with patch("src.http.time.sleep"):
            with pytest.raises(requests.HTTPError):
                client.get("https://example.com/jobs")

        assert session.request.call_count == 4


class TestExistingRetryBehaviourUnchanged:
    def test_still_retries_5xx(self):
        client, session = make_client([make_resp(503), make_resp(200)])

        with patch("src.http.time.sleep"):
            resp = client.get("https://example.com/jobs")

        assert resp.status_code == 200
        assert session.request.call_count == 2

    def test_404_raises_immediately_without_retry(self):
        """Client errors other than 429 are not transient; retrying wastes the budget."""
        client, session = make_client([make_resp(404)])

        with patch("src.http.time.sleep"):
            with pytest.raises(requests.HTTPError):
                client.get("https://example.com/jobs")

        assert session.request.call_count == 1
