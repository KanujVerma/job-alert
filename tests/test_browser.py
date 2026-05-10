from __future__ import annotations
from src.browser import BrowserSessionContext


def test_session_context_is_frozen():
    ctx = BrowserSessionContext(
        cookies={"sid": "abc"},
        headers={"Origin": "https://careers.snowflake.com"},
        final_url="https://careers.snowflake.com/us/en/jobs",
        captured_urls=("https://careers.snowflake.com/api/apply/v2/jobs?limit=20",),
    )
    assert ctx.cookies == {"sid": "abc"}
    assert ctx.final_url == "https://careers.snowflake.com/us/en/jobs"
    assert len(ctx.captured_urls) == 1


def test_session_context_frozen_raises_on_mutate():
    import pytest
    ctx = BrowserSessionContext(cookies={}, headers={}, final_url="", captured_urls=())
    assert isinstance(ctx.captured_urls, tuple)
    with pytest.raises((AttributeError, TypeError)):
        ctx.cookies = {}  # type: ignore


from unittest.mock import MagicMock, patch, call
import pytest
from src.browser import BrowserClient, BrowserSessionContext


def _make_mock_pw():
    """Build a minimal sync_playwright mock tree."""
    mock_cookie = {"name": "PHPSESSID", "value": "abc123"}
    mock_page = MagicMock()
    mock_page.url = "https://careers.snowflake.com/us/en/jobs"
    mock_page.evaluate.return_value = "Mozilla/5.0 Chrome/120"
    mock_context = MagicMock()
    mock_context.cookies.return_value = [mock_cookie]
    mock_context.new_page.return_value = mock_page
    mock_context.pages = [mock_page]
    mock_browser = MagicMock()
    mock_browser.new_context.return_value = mock_context
    mock_chromium = MagicMock()
    mock_chromium.launch.return_value = mock_browser
    mock_pw_instance = MagicMock()
    mock_pw_instance.chromium = mock_chromium
    mock_pw_manager = MagicMock()
    mock_pw_manager.start.return_value = mock_pw_instance
    return mock_pw_manager, mock_pw_instance, mock_browser, mock_context, mock_page


def test_bootstrap_session_returns_context():
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        ctx = client.bootstrap_session(
            "https://careers.snowflake.com",
            company="Snowflake",
        )

    assert isinstance(ctx, BrowserSessionContext)
    assert ctx.cookies == {"PHPSESSID": "abc123"}
    assert ctx.headers["Origin"] == "https://careers.snowflake.com"
    assert "careers.snowflake.com" in ctx.headers["Referer"]
    assert ctx.headers["User-Agent"] == "Mozilla/5.0 Chrome/120"
    # Page stays open after bootstrap (Task 6 v3 change); close is called lazily via client.close()
    mock_page.close.assert_not_called()


def test_bootstrap_session_captures_xhr_urls():
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()

    def setup_response_listener(event, callback):
        # Simulate a matching XHR response being observed
        mock_resp = MagicMock()
        mock_resp.url = "https://careers.snowflake.com/api/apply/v2/jobs?limit=20"
        callback(mock_resp)

    mock_page.on.side_effect = setup_response_listener

    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        ctx = client.bootstrap_session(
            "https://careers.snowflake.com",
            company="Snowflake",
            wait_for_response_url="**/api/apply/v2/jobs**",
        )

    assert any("api/apply/v2/jobs" in u for u in ctx.captured_urls)


def test_bootstrap_session_playwright_not_installed():
    with patch("src.browser._sync_playwright", None):
        client = BrowserClient()
        with pytest.raises(RuntimeError, match="playwright package not installed"):
            client.bootstrap_session("https://example.com")
    assert client.available is False


def test_bootstrap_session_saves_artifacts_on_failure(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    mock_pw_manager, _, _, mock_context, mock_page = _make_mock_pw()
    mock_page.goto.side_effect = Exception("Navigation timeout")

    # Make screenshot actually write a file so the assertion can verify it exists
    def fake_screenshot(path):
        from pathlib import Path
        Path(path).write_bytes(b"PNG")

    mock_page.screenshot.side_effect = fake_screenshot
    mock_page.content.return_value = "<html></html>"

    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        with pytest.raises(Exception, match="Navigation timeout"):
            client.bootstrap_session(
                "https://careers.snowflake.com",
                company="Snowflake",
            )

    artifact_dirs = list((tmp_path / "debug_artifacts" / "Snowflake").iterdir())
    assert len(artifact_dirs) == 1
    assert (artifact_dirs[0] / "error.txt").read_text() == "Exception: Navigation timeout"
    assert (artifact_dirs[0] / "screenshot.png").exists()
    assert (artifact_dirs[0] / "page.html").exists()


def test_close_is_idempotent():
    mock_pw_manager, _, _, _, _ = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        client = BrowserClient()
        client._ensure_started()
        client.close()
        client.close()  # second call must not raise
    assert client._pw is None
    assert client._browser is None
    assert client._context is None


def test_context_manager_closes_on_exit():
    mock_pw_manager, mock_pw_instance, mock_browser, mock_context, _ = _make_mock_pw()
    with patch("src.browser._sync_playwright", return_value=mock_pw_manager):
        with BrowserClient() as client:
            client._ensure_started()
    mock_context.close.assert_called_once()
    mock_browser.close.assert_called_once()
    mock_pw_instance.stop.assert_called_once()


def test_capture_debug_artifacts_no_page(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    client = BrowserClient()
    client.capture_debug_artifacts("Snowflake", ValueError("post-bootstrap failure"))
    artifact_dirs = list((tmp_path / "debug_artifacts" / "Snowflake").iterdir())
    assert len(artifact_dirs) == 1
    assert (artifact_dirs[0] / "error.txt").read_text() == "ValueError: post-bootstrap failure"
    # No screenshot or page.html when page is None
    assert not (artifact_dirs[0] / "screenshot.png").exists()
    assert not (artifact_dirs[0] / "page.html").exists()


# ---------------------------------------------------------------------------
# Task 6 (v3): XHR interception + evaluate_fetch
# ---------------------------------------------------------------------------

from unittest.mock import call


class TestBrowserSessionContextV3:
    def test_new_fields_have_defaults(self):
        """Existing 4-arg construction still works — new fields are optional."""
        ctx = BrowserSessionContext(
            cookies={"sid": "abc"},
            headers={"Origin": "https://example.com"},
            final_url="https://example.com/jobs",
            captured_urls=(),
        )
        assert ctx.captured_request_headers == {}
        assert ctx.captured_first_response is None

    def test_new_fields_can_be_set(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
            captured_request_headers={"Authorization": "Bearer token"},
            captured_first_response='{"data": {"positions": []}}',
        )
        assert ctx.captured_request_headers == {"Authorization": "Bearer token"}
        assert ctx.captured_first_response == '{"data": {"positions": []}}'


def _make_mock_browser_for_intercept():
    """Build a BrowserClient with a mocked Playwright stack for intercept tests."""
    mock_page = MagicMock()
    mock_page.url = "https://careers.snowflake.com/us/en/jobs"
    mock_page.evaluate.return_value = "Mozilla/5.0 Test"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.cookies.return_value = [{"name": "PHPSESSID", "value": "sess123"}]

    mock_browser_obj = MagicMock()
    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser_obj
    mock_browser_obj.new_context.return_value = mock_context

    with patch("src.browser._sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value.start.return_value = mock_pw

        client = BrowserClient()
        client._pw = mock_pw
        client._browser = mock_browser_obj
        client._context = mock_context

    return client, mock_page


class TestBootstrapSessionXHRInterception:
    def test_captures_request_headers_on_matching_response(self):
        client, mock_page = _make_mock_browser_for_intercept()

        # Simulate a response event for the matching URL
        captured_handler = None

        def fake_on(event, handler):
            nonlocal captured_handler
            if event == "response":
                captured_handler = handler

        mock_page.on.side_effect = fake_on

        # After goto, fire a fake matching response
        def fake_goto(*args, **kwargs):
            if captured_handler:
                mock_resp = MagicMock()
                mock_resp.url = "https://careers.snowflake.com/api/apply/v2/jobs?limit=20"
                mock_resp.request.headers = {
                    "Authorization": "Bearer tok",
                    "sec-fetch-site": "same-origin",  # should be filtered
                    ":method": "GET",                  # should be filtered
                }
                mock_resp.text.return_value = '{"data": {"positions": [], "count": 0}}'
                captured_handler(mock_resp)

        mock_page.goto.side_effect = fake_goto
        mock_page.wait_for_load_state = MagicMock()

        session = client.bootstrap_session(
            "https://careers.snowflake.com",
            wait_for_response_url="**/api/apply/v2/jobs**",
        )

        assert "Authorization" in session.captured_request_headers
        assert "sec-fetch-site" not in session.captured_request_headers
        assert ":method" not in session.captured_request_headers
        assert session.captured_first_response is not None

    def test_page_stays_open_after_bootstrap(self):
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.wait_for_load_state = MagicMock()

        client.bootstrap_session("https://careers.snowflake.com")

        mock_page.close.assert_not_called()
        assert client._page is mock_page

    def test_page_closed_on_bootstrap_failure(self, monkeypatch, tmp_path):
        monkeypatch.chdir(tmp_path)  # prevent debug_artifacts/ from landing in repo root
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.goto.side_effect = RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            client.bootstrap_session("https://careers.snowflake.com", company="Snowflake")

        mock_page.close.assert_called_once()
        assert client._page is None

    def test_close_closes_page(self):
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.wait_for_load_state = MagicMock()
        client.bootstrap_session("https://careers.snowflake.com")

        client.close()

        mock_page.close.assert_called_once()
        assert client._page is None

    def test_captures_request_method_url_body(self):
        client, mock_page = _make_mock_browser_for_intercept()
        captured_handler = None

        def fake_on(event, handler):
            nonlocal captured_handler
            if event == "response":
                captured_handler = handler

        mock_page.on.side_effect = fake_on

        def fake_goto(*args, **kwargs):
            if captured_handler:
                mock_resp = MagicMock()
                mock_resp.url = "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
                mock_resp.status = 200
                mock_resp.request.method = "POST"
                mock_resp.request.headers = {"Content-Type": "application/json"}
                mock_resp.request.post_data = '{"from":0,"size":20}'
                mock_resp.text.return_value = '{"jobs":[],"total":0}'
                captured_handler(mock_resp)

        mock_page.goto.side_effect = fake_goto
        mock_page.wait_for_load_state = MagicMock()

        session = client.bootstrap_session(
            "https://careers.snowflake.com/us/en/search",
            wait_for_response_url="**/api/SNCOUS/searchJobs**",
        )

        assert session.captured_request_method == "POST"
        assert session.captured_request_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert session.captured_request_body == '{"from":0,"size":20}'


class TestBrowserSessionContextPhenom:
    def test_new_fields_have_defaults(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
        )
        assert ctx.captured_request_method == "GET"
        assert ctx.captured_request_url == ""
        assert ctx.captured_request_body is None

    def test_new_fields_can_be_set(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
            captured_request_method="POST",
            captured_request_url="https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            captured_request_body='{"from":0,"size":20}',
        )
        assert ctx.captured_request_method == "POST"
        assert ctx.captured_request_url == "https://content-us.phenompeople.com/api/SNCOUS/searchJobs"
        assert ctx.captured_request_body == '{"from":0,"size":20}'


class TestEvaluateFetch:
    def test_raises_without_active_page(self):
        client = BrowserClient()
        with pytest.raises(RuntimeError, match="bootstrap_session must be called"):
            client.evaluate_fetch("https://example.com/api", {})

    def test_calls_page_evaluate_with_correct_args(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"data": {"positions": [], "count": 0}}

        result = client.evaluate_fetch(
            "https://careers.snowflake.com/api/apply/v2/jobs",
            {"limit": 20, "offset": 0},
        )

        assert result == {"data": {"positions": [], "count": 0}}
        mock_page.evaluate.assert_called_once()
        call_args = mock_page.evaluate.call_args
        assert "fetch" in call_args[0][0]  # JS code contains fetch
        assert call_args[0][1]["url"] == "https://careers.snowflake.com/api/apply/v2/jobs"
        assert call_args[0][1]["params"]["limit"] == "20"


class TestEvaluateFetchGetPost:
    def test_evaluate_fetch_post_calls_correct_js(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"jobs": [], "total": 0}

        client.evaluate_fetch(
            "https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            {},
            method="POST",
            body={"from": 0, "size": 20},
        )

        call_args = mock_page.evaluate.call_args
        js = call_args[0][0]
        passed = call_args[0][1]
        assert "POST" in js
        assert "JSON.stringify" in js
        assert passed["method"] == "POST"
        assert passed["body"] == {"from": 0, "size": 20}

    def test_evaluate_fetch_get_uses_query_params(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"jobs": [], "total": 0}

        client.evaluate_fetch(
            "https://content-us.phenompeople.com/api/SNCOUS/searchJobs",
            {"from": "0", "size": "20"},
        )

        call_args = mock_page.evaluate.call_args
        js = call_args[0][0]
        passed = call_args[0][1]
        assert "URLSearchParams" in js
        assert passed["params"]["from"] == "0"

    def test_evaluate_fetch_includes_cors_and_credentials(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {}

        client.evaluate_fetch("https://example.com/api", {})

        js = mock_page.evaluate.call_args[0][0]
        assert "cors" in js
        assert "credentials" in js
        assert "include" in js


class TestHeaderFiltering:
    def test_pseudo_headers_filtered(self):
        from src.browser import _filter_request_headers
        headers = {
            ":method": "GET",
            ":authority": "careers.snowflake.com",
            "Authorization": "Bearer tok",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "Accept": "application/json",
        }
        result = _filter_request_headers(headers)
        assert ":method" not in result
        assert ":authority" not in result
        assert "sec-fetch-site" not in result
        assert "Authorization" in result
        assert "Accept" in result
