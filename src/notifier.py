from __future__ import annotations
import time
import threading
import logging

import requests

from src.models import Job

logger = logging.getLogger(__name__)

ROLE_TYPE_EMOJI = {
    "internship": "🎓",
    "new-grad": "🆕",
    "entry-level": "📌",
    "unknown": "❓",
}

_PT_FORMAT = "%Y-%m-%d %H:%M PT"


class TokenBucket:
    """Thread-safe token bucket: rate=4/sec, capacity=8."""

    def __init__(self, rate: float = 4.0, capacity: float = 8.0):
        self._rate = rate
        self._capacity = capacity
        self._tokens = capacity  # start full
        self._last_refill = time.monotonic()
        self._lock = threading.Lock()

    def _refill(self) -> None:
        now = time.monotonic()
        elapsed = now - self._last_refill
        added = elapsed * self._rate
        self._tokens = min(self._capacity, self._tokens + added)
        self._last_refill = now

    def consume(self, tokens: float = 1.0) -> None:
        """Block until a token is available."""
        while True:
            with self._lock:
                self._refill()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return
                # Calculate how long to wait for enough tokens
                deficit = tokens - self._tokens
                wait = deficit / self._rate
            time.sleep(wait)


class Notifier:
    def __init__(self, webhook_url: str):
        self._url = webhook_url
        self._bucket = TokenBucket()

    def send_job_alert(self, job: Job) -> bool:
        """Send one Discord embed for a job. Returns True on success."""
        emoji = ROLE_TYPE_EMOJI.get(job.role_type, "❓")
        title = f"🆕 {emoji} {job.role_type.title()} · {job.company}"
        if job.priority == "preferred":
            title += f" [PRIORITY: {job.location}]"

        # Format detected_at
        try:
            import zoneinfo
            pt_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
            detected_str = job.detected_at.astimezone(pt_tz).strftime(_PT_FORMAT)
        except Exception:
            detected_str = job.detected_at.strftime("%Y-%m-%d %H:%M UTC")

        # Department / category field
        dept_parts = [p for p in [job.department, job.category] if p]
        dept_str = " / ".join(dept_parts) if dept_parts else "N/A"

        fields = [
            {"name": "📍 Location", "value": job.location or "Not specified", "inline": True},
            {"name": "🏢 Department", "value": dept_str, "inline": True},
            {
                "name": "🏷️ Tags",
                "value": f"{job.role_type} · {job.source_platform} · {job.priority}",
                "inline": False,
            },
            {
                "name": "🔑 Keywords",
                "value": ", ".join(job.matched_keywords[:8]) or "none",
                "inline": False,
            },
            {"name": "🔗 URL", "value": job.url, "inline": False},
            {"name": "🕐 Detected", "value": detected_str, "inline": True},
        ]

        embed = {
            "title": title,
            "description": job.title,
            "fields": fields,
            "color": 0x5865F2,  # Discord blurple
        }
        return self._send_embed(embed)

    def send_summary(self, title: str, description: str) -> bool:
        """Send a plain text summary embed."""
        embed = {"title": title, "description": description, "color": 0x57F287}
        return self._send_embed(embed)

    def _send_embed(self, embed: dict) -> bool:
        """POST the embed to Discord. Handle 429 with retry-after."""
        self._bucket.consume()
        payload = {"embeds": [embed]}
        try:
            resp = requests.post(self._url, json=payload, timeout=10)
            if resp.status_code == 429:
                retry_after = float(resp.headers.get("retry-after", 5))
                logger.warning(f"Discord 429 rate limit; sleeping {retry_after}s")
                time.sleep(retry_after)
                # Retry once
                resp = requests.post(self._url, json=payload, timeout=10)
            if resp.ok:
                return True
            logger.warning(f"Discord webhook error {resp.status_code}: {resp.text[:200]}")
            return False
        except requests.RequestException as e:
            logger.warning(f"Discord webhook request failed: {e}")
            return False
