from __future__ import annotations
import time
import random
import logging

import requests

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1, 2, 4]

# An ATS that throttles us can ask for an arbitrarily long wait. Honour the ask,
# but never past this, or one rude Retry-After parks the whole run until the CI
# step times out and every remaining company goes unscraped.
_MAX_RETRY_AFTER_SECONDS = 30.0


class HTTPClient:
    def __init__(self, user_agent: str, timeout: int = 15, max_retries: int = 3):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.timeout = timeout
        self.max_retries = max_retries

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with exponential backoff on 5xx and 429."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST with exponential backoff on 5xx and 429."""
        return self._request("POST", url, **kwargs)

    @staticmethod
    def _retry_after_delay(resp: requests.Response, fallback: float) -> float:
        """Seconds to wait per the Retry-After header, capped. Falls back on absence.

        Only the numeric form is honoured; the HTTP-date form falls back to the
        normal backoff rather than pretending to parse it.
        """
        raw = resp.headers.get("Retry-After")
        if raw is None:
            return fallback
        try:
            return min(float(raw), _MAX_RETRY_AFTER_SECONDS)
        except (TypeError, ValueError):
            return fallback

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        last_resp: requests.Response | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code >= 500 or resp.status_code == 429:
                    last_resp = resp
                    if attempt < self.max_retries:
                        delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        if resp.status_code == 429:
                            delay = self._retry_after_delay(resp, delay)
                        logger.warning(
                            f"{method} {url} → {resp.status_code}; "
                            f"retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    # Final attempt still 5xx / 429
                    resp.raise_for_status()
                else:
                    resp.raise_for_status()
                    return resp
            except requests.HTTPError:
                raise
            except requests.RequestException as e:
                last_exc = e
                if attempt < self.max_retries:
                    delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                    logger.warning(f"{method} {url} failed: {e}; retrying in {delay}s")
                    time.sleep(delay)

        if last_resp is not None:
            last_resp.raise_for_status()
        raise last_exc or requests.RequestException(f"All retries failed for {url}")

    def polite_delay(self, min_s: float = 2.0, max_s: float = 4.0) -> None:
        """Sleep random seconds between min_s and max_s."""
        time.sleep(random.uniform(min_s, max_s))
