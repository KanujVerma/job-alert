from __future__ import annotations
import time
import random
import logging

import requests

logger = logging.getLogger(__name__)

_RETRY_DELAYS = [1, 2, 4]


class HTTPClient:
    def __init__(self, user_agent: str, timeout: int = 15, max_retries: int = 3):
        self.session = requests.Session()
        self.session.headers["User-Agent"] = user_agent
        self.timeout = timeout
        self.max_retries = max_retries

    def get(self, url: str, **kwargs) -> requests.Response:
        """GET with exponential backoff on 5xx."""
        return self._request("GET", url, **kwargs)

    def post(self, url: str, **kwargs) -> requests.Response:
        """POST with exponential backoff on 5xx."""
        return self._request("POST", url, **kwargs)

    def _request(self, method: str, url: str, **kwargs) -> requests.Response:
        kwargs.setdefault("timeout", self.timeout)
        last_exc: Exception | None = None
        last_resp: requests.Response | None = None

        for attempt in range(self.max_retries + 1):
            try:
                resp = self.session.request(method, url, **kwargs)
                if resp.status_code >= 500:
                    last_resp = resp
                    if attempt < self.max_retries:
                        delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
                        logger.warning(
                            f"{method} {url} → {resp.status_code}; "
                            f"retrying in {delay}s (attempt {attempt + 1}/{self.max_retries})"
                        )
                        time.sleep(delay)
                        continue
                    # Final attempt still 5xx
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
