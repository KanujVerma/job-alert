# src/browser.py
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

try:
    from playwright.sync_api import sync_playwright as _sync_playwright
except ImportError:
    _sync_playwright = None  # type: ignore[assignment]

_DEBUG_HTML_MAX = 1_048_576  # 1 MB cap on saved HTML


@dataclass(frozen=True)
class BrowserSessionContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    final_url: str
    captured_urls: list[str]


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
        """Navigate to url, wait for SPA to settle, return cookies + safe headers.

        Primary wait: wait_for_selector if provided, else networkidle.
        Secondary: if wait_for_response_url is set, record matching XHR URLs
        in the returned captured_urls (non-blocking — does not fail if absent).

        On any exception: saves debug artifacts to debug_artifacts/{company}/{ts}/
        then re-raises so the adapter can log and return [].
        """
        self._ensure_started()
        timeout_ms = timeout_seconds * 1000
        captured_urls: list[str] = []

        page = self._context.new_page()
        try:
            if wait_for_response_url:
                needle = wait_for_response_url.replace("**", "")
                page.on(
                    "response",
                    lambda resp: captured_urls.append(resp.url)
                    if needle in resp.url
                    else None,
                )

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

            return BrowserSessionContext(
                cookies=cookies,
                headers=headers,
                final_url=final_url,
                captured_urls=captured_urls,
            )

        except Exception as exc:
            # Save debug artifacts while the page is still open, then re-raise
            self._save_artifacts(page, company, exc)
            raise

        finally:
            page.close()

    def capture_debug_artifacts(self, company: str, error: Exception) -> None:
        """Save error.txt for post-bootstrap failures (no page available)."""
        self._save_artifacts(None, company, error)

    def close(self) -> None:
        """Idempotent teardown. Call in do_run() finally block."""
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
