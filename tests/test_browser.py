from __future__ import annotations
from src.browser import BrowserSessionContext


def test_session_context_is_frozen():
    ctx = BrowserSessionContext(
        cookies={"sid": "abc"},
        headers={"Origin": "https://careers.snowflake.com"},
        final_url="https://careers.snowflake.com/us/en/jobs",
        captured_urls=["https://careers.snowflake.com/api/apply/v2/jobs?limit=20"],
    )
    assert ctx.cookies == {"sid": "abc"}
    assert ctx.final_url == "https://careers.snowflake.com/us/en/jobs"
    assert len(ctx.captured_urls) == 1


def test_session_context_frozen_raises_on_mutate():
    import pytest
    ctx = BrowserSessionContext(cookies={}, headers={}, final_url="", captured_urls=[])
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
    mock_page.close.assert_called_once()


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
