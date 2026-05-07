"""Tests for TokenBucket and Notifier in src/notifier.py."""
from __future__ import annotations
import time
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

import pytest

from src.notifier import TokenBucket, Notifier
from src.models import Job

_NOW = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_job(**kwargs) -> Job:
    defaults = dict(
        id="test-job-1",
        company="Acme",
        title="Software Engineering Intern",
        location="San Francisco, CA",
        department="Engineering",
        category="Software",
        url="https://example.com/job/1",
        source_platform="workday",
        posted_at=None,
        detected_at=_NOW,
        raw_text="software engineering intern san francisco ca",
        role_type="internship",
        priority="preferred",
        matched_keywords=("intern", "software"),
    )
    defaults.update(kwargs)
    return Job(**defaults)


# ---------------------------------------------------------------------------
# TokenBucket tests
# ---------------------------------------------------------------------------

class TestTokenBucket:
    def test_bucket_starts_full_can_consume_immediately(self):
        bucket = TokenBucket(rate=4.0, capacity=8.0)
        start = time.monotonic()
        # Should be able to consume 8 tokens immediately (bucket starts full)
        for _ in range(8):
            bucket.consume(1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 1.0, f"Consuming 8 tokens from full bucket took too long: {elapsed:.2f}s"

    def test_consuming_faster_than_rate_blocks(self):
        """Consuming 12 tokens at 4/sec should take ~1 second (4 immediate, 8 after refill)."""
        bucket = TokenBucket(rate=4.0, capacity=8.0)
        start = time.monotonic()
        for _ in range(12):  # 8 from full capacity + 4 more = ~1s wait
            bucket.consume(1.0)
        elapsed = time.monotonic() - start
        # Should have blocked for at least ~0.8s (some slack for CI)
        assert elapsed >= 0.5, f"Expected blocking but elapsed only {elapsed:.2f}s"

    def test_tokens_refill_over_time(self):
        bucket = TokenBucket(rate=4.0, capacity=8.0)
        # Drain the bucket
        for _ in range(8):
            bucket.consume(1.0)
        # Wait enough for 2 tokens to refill
        time.sleep(0.6)
        # Should be able to consume 2 quickly
        start = time.monotonic()
        bucket.consume(1.0)
        bucket.consume(1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5

    def test_custom_capacity(self):
        bucket = TokenBucket(rate=10.0, capacity=3.0)
        start = time.monotonic()
        for _ in range(3):
            bucket.consume(1.0)
        elapsed = time.monotonic() - start
        assert elapsed < 0.5


# ---------------------------------------------------------------------------
# Notifier tests (mocked HTTP)
# ---------------------------------------------------------------------------

class TestNotifierSendJobAlert:
    def test_success_returns_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.ok = True

        with patch("src.notifier.requests.post", return_value=mock_resp) as mock_post:
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job()
            result = notifier.send_job_alert(job)

        assert result is True
        mock_post.assert_called_once()

    def test_embed_title_contains_company(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.ok = True

        captured = {}
        def capture_post(url, json=None, **kwargs):
            captured["payload"] = json
            return mock_resp

        with patch("src.notifier.requests.post", side_effect=capture_post):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job(company="Acme Corp", priority="normal")
            notifier.send_job_alert(job)

        embed = captured["payload"]["embeds"][0]
        assert "Acme Corp" in embed["title"]

    def test_embed_description_is_job_title(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.ok = True

        captured = {}
        def capture_post(url, json=None, **kwargs):
            captured["payload"] = json
            return mock_resp

        with patch("src.notifier.requests.post", side_effect=capture_post):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job(title="Data Engineering Intern")
            notifier.send_job_alert(job)

        embed = captured["payload"]["embeds"][0]
        assert embed["description"] == "Data Engineering Intern"

    def test_preferred_priority_appended_to_title(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 204
        mock_resp.ok = True

        captured = {}
        def capture_post(url, json=None, **kwargs):
            captured["payload"] = json
            return mock_resp

        with patch("src.notifier.requests.post", side_effect=capture_post):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job(priority="preferred", location="San Francisco, CA")
            notifier.send_job_alert(job)

        embed = captured["payload"]["embeds"][0]
        assert "PRIORITY" in embed["title"]

    def test_http_500_returns_false(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.ok = False
        mock_resp.text = "Internal Server Error"

        with patch("src.notifier.requests.post", return_value=mock_resp):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job()
            result = notifier.send_job_alert(job)

        assert result is False

    def test_429_retries_once(self):
        """On 429, should sleep retry-after and retry once."""
        resp_429 = MagicMock()
        resp_429.status_code = 429
        resp_429.ok = False
        resp_429.headers = {"retry-after": "0.01"}

        resp_200 = MagicMock()
        resp_200.status_code = 200
        resp_200.ok = True

        call_count = {"n": 0}

        def side_effect(url, json=None, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                return resp_429
            return resp_200

        with patch("src.notifier.requests.post", side_effect=side_effect):
            with patch("src.notifier.time.sleep"):  # don't actually sleep
                notifier = Notifier("https://discord.com/api/webhooks/test/token")
                job = make_job()
                result = notifier.send_job_alert(job)

        assert result is True
        assert call_count["n"] == 2

    def test_request_exception_returns_false(self):
        import requests as req_lib

        with patch("src.notifier.requests.post", side_effect=req_lib.RequestException("conn failed")):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            job = make_job()
            result = notifier.send_job_alert(job)

        assert result is False


class TestNotifierSendSummary:
    def test_success_returns_true(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True

        with patch("src.notifier.requests.post", return_value=mock_resp):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            result = notifier.send_summary("Test Title", "Test body")

        assert result is True

    def test_embed_has_correct_title_and_description(self):
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.ok = True

        captured = {}
        def capture_post(url, json=None, **kwargs):
            captured["payload"] = json
            return mock_resp

        with patch("src.notifier.requests.post", side_effect=capture_post):
            notifier = Notifier("https://discord.com/api/webhooks/test/token")
            notifier.send_summary("My Title", "My Description")

        embed = captured["payload"]["embeds"][0]
        assert embed["title"] == "My Title"
        assert embed["description"] == "My Description"
