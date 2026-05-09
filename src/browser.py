# src/browser.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:
    _sync_playwright = None  # type: ignore[assignment]

_DEBUG_HTML_MAX = 1_048_576  # 1 MB cap on saved HTML

_HEADER_BLOCK_PREFIXES = ("sec-fetch-", "sec-ch-", ":", "x-playwright-")
_HEADER_BLOCK_EXACT = frozenset({"host", "connection", "content-length", "transfer-encoding"})


def _filter_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop browser-internal and pseudo-headers; keep forwarding-safe ones."""
    result = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if any(k_lower.startswith(p) for p in _HEADER_BLOCK_PREFIXES):
            continue
        if k_lower in _HEADER_BLOCK_EXACT:
            continue
        result[k] = v
    return result


@dataclass(frozen=True)
class BrowserSessionContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    final_url: str
    captured_urls: tuple[str, ...]
    captured_request_headers: dict[str, str] = field(default_factory=dict)
    captured_first_response: str | None = None


class BrowserClient:
    """Shared headless-browser for JS-rendered career sites.

    Lazy-starts chromium on first bootstrap_session call. Must be used as
    a context manager (or close() called explicitly) so chromium shuts down.

    Only src/browser.py and src/adapters/eightfold_playwright.py import Playwright.
    """

    def __init__(self) -> None:
        self.available: bool = True
        self._pw = None
        self._browser = None
        self._context = None
        self._page = None

    def __enter__(self) -> "BrowserClient":
        return self

    def __exit__(self, *_) -> None:
        self.close()

    # ------------------------------------------------------------------
    # Core API
    # ------------------------------------------------------------------

    def _ensure_started(self) -> None:
        if self._pw is not None:
            return
        if _sync_playwright is None:
            self.available = False
            raise RuntimeError(
                "playwright package not installed. "
                "Run: pip install playwright && python -m playwright install chromium"
            )
        try:
            self._pw = _sync_playwright().start()
            self._browser = self._pw.chromium.launch(headless=True)
            self._context = self._browser.new_context()
        except Exception as exc:
            logger.error("BrowserClient: failed to start chromium: %s", exc)
            self.available = False
            self.close()
            raise

    def bootstrap_session(
        self,
        url: str,
        *,
        company: str = "unknown",
        wait_for_selector: str | None = None,
        wait_for_response_url: str | None = None,
        timeout_seconds: int = 30,
    ) -> BrowserSessionContext:
        """Navigate to url, wait for SPA to settle, return session context.

        If wait_for_response_url is provided, intercepts the first matching XHR
        and captures its request headers + response body.
        The page stays open after return — call close() when done.
        On any exception: saves debug artifacts then re-raises.
        """
        self._ensure_started()
        timeout_ms = timeout_seconds * 1000
        captured_urls: list[str] = []
        captured_request_headers: dict[str, str] = {}
        captured_first_response: str | None = None

        page = self._context.new_page()
        try:
            if wait_for_response_url:
                needle = wait_for_response_url.replace("**", "")

                def handle_response(resp) -> None:
                    nonlocal captured_request_headers, captured_first_response
                    if needle in resp.url:
                        captured_urls.append(resp.url)
                        if not captured_request_headers:  # first match only
                            captured_request_headers = _filter_request_headers(
                                dict(resp.request.headers)
                            )
                            try:
                                captured_first_response = resp.text()
                            except Exception:
                                pass

                page.on("response", handle_response)

            page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if wait_for_selector:
                try:
                    page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
                except Exception:
                    # Selector not found — fall back to networkidle
                    page.wait_for_load_state("networkidle", timeout=timeout_ms)
            else:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)

            final_url = page.url
            raw_cookies = self._context.cookies()
            cookies = {c["name"]: c["value"] for c in raw_cookies}

            # Build headers: derive from URL (safe subset only, no browser internals)
            parsed = urlparse(url)
            origin = f"{parsed.scheme}://{parsed.netloc}"
            headers: dict[str, str] = {
                "Origin": origin,
                "Referer": final_url,
            }
            try:
                ua = page.evaluate("navigator.userAgent")
                if ua:
                    headers["User-Agent"] = str(ua)
            except Exception:
                pass

            self._page = page  # keep alive for evaluate_fetch fallback
            return BrowserSessionContext(
                cookies=cookies,
                headers=headers,
                final_url=final_url,
                captured_urls=tuple(captured_urls),
                captured_request_headers=captured_request_headers,
                captured_first_response=captured_first_response,
            )

        except Exception as exc:
            self._save_artifacts(page, company, exc)
            page.close()  # close only on failure
            self._page = None
            raise
        # No finally: page.close() — success path keeps the page alive

    def evaluate_fetch(self, url: str, params: dict) -> dict:
        """Run a fetch() call inside the live Playwright page. Returns parsed JSON.

        Requires bootstrap_session to have been called first.
        Uses credentials: 'include' so localStorage/sessionStorage tokens apply.
        """
        if self._page is None:
            raise RuntimeError(
                "No active page — bootstrap_session must be called before evaluate_fetch"
            )
        js = """
        async (args) => {
            const p = new URLSearchParams(args.params);
            const resp = await fetch(args.url + '?' + p.toString(), {credentials: 'include'});
            if (!resp.ok) {
                throw new Error('fetch failed: ' + resp.status + ' ' + resp.statusText);
            }
            return resp.json();
        }
        """
        return self._page.evaluate(
            js, {"url": url, "params": {k: str(v) for k, v in params.items()}}
        )

    def capture_debug_artifacts(self, company: str, error: Exception) -> None:
        """Save error.txt for post-bootstrap failures (no page available)."""
        self._save_artifacts(None, company, error)

    def close(self) -> None:
        """Idempotent teardown. Call in do_run() finally block."""
        if self._page is not None:
            try:
                self._page.close()
            except Exception:
                pass
            self._page = None
        for attr, method in [("_context", "close"), ("_browser", "close"), ("_pw", "stop")]:
            obj = getattr(self, attr, None)
            if obj is not None:
                try:
                    getattr(obj, method)()
                except Exception:
                    pass
                setattr(self, attr, None)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _save_artifacts(self, page, company: str, error: Exception) -> None:
        sanitized = re.sub(r"[^A-Za-z0-9_-]", "_", company)
        if not sanitized:
            sanitized = "_unknown_"
        ts = datetime.now(tz=timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        artifact_dir = Path("debug_artifacts") / sanitized / ts
        try:
            artifact_dir.mkdir(parents=True, exist_ok=True)
        except OSError as e:
            logger.warning("BrowserClient: cannot create artifact dir: %s", e)
            return

        if page is not None:
            try:
                page.screenshot(path=str(artifact_dir / "screenshot.png"))
            except Exception as e:
                logger.debug("BrowserClient: screenshot failed: %s", e)

            try:
                html = page.content()
                if len(html) > _DEBUG_HTML_MAX:
                    html = html[:_DEBUG_HTML_MAX] + "\n<!-- TRUNCATED -->"
                (artifact_dir / "page.html").write_text(html, encoding="utf-8")
            except Exception as e:
                logger.debug("BrowserClient: html dump failed: %s", e)

        (artifact_dir / "error.txt").write_text(
            f"{type(error).__name__}: {error}", encoding="utf-8"
        )
        logger.info("BrowserClient: debug artifacts saved to %s", artifact_dir)
