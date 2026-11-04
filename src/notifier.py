from __future__ import annotations
import re
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

# Discord's hard limit on an embed title; a longer one is rejected with 400.
_DISCORD_TITLE_MAX = 256

_PT_FORMAT = "PT"
_UTC_FORMAT = "UTC"


def _fmt_ts(dt, zone_label: str) -> str:
    """"2026-05-06 1:05 PM PT" — 12-hour clock, no leading zero on the hour.

    The hour is built explicitly rather than with strftime("%-I"): that flag is
    a glibc/BSD extension, absent on Windows, and this formats user-facing text
    so a silent platform difference would be a real defect. "%I" is portable and
    zero-padded, so strip the pad; midnight formats as "12", which lstrip("0")
    would empty, hence the fallback.
    """
    hour = dt.strftime("%I").lstrip("0") or "12"
    return f"{dt.strftime('%Y-%m-%d')} {hour}:{dt.strftime('%M %p')} {zone_label}"


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


def sanitize_discord_text(text: str, max_len: int = 1024) -> str:
    """Strip control characters, neutralize disallowed mentions, and truncate safely."""
    if not text:
        return ""
    zwsp = "\u200b"
    clean = re.sub(r"@everyone\b", f"@{zwsp}everyone", text)
    clean = re.sub(r"@here\b", f"@{zwsp}here", clean)
    clean = re.sub(r"<@&?(\d+)>", f"@{zwsp}[\\g<1>]", clean)
    clean = re.sub(r"<@!?(\d+)>", f"@{zwsp}[\\g<1>]", clean)
    # Strip non-printable control chars except \n and \t
    clean = "".join(c for c in clean if c in ("\n", "\t") or (ord(c) >= 32 and ord(c) != 127))
    if len(clean) > max_len:
        clean = clean[: max_len - 1].rstrip() + "…"
    return clean


def sanitize_url(url: str) -> str:
    """Ensure URL uses http or https, otherwise return placeholder."""
    clean = (url or "").strip()
    if clean.startswith("http://") or clean.startswith("https://"):
        return clean
    return "https://invalid-url"


def build_job_embed(job: Job) -> dict:
    """Construct a sanitized, validated Discord embed dictionary following P1-B contract."""
    # Prefix badge
    badge = "⭐ NETWORK PRIORITY" if getattr(job, "network_priority", False) else "DISCOVERED"
    emoji = ROLE_TYPE_EMOJI.get(job.role_type, "❓")

    # Employer normalization
    if job.company in ("Microsoft", "Microsoft Research"):
        display_company = "Microsoft"
        company_field_val = "Microsoft" if job.company == "Microsoft" else "Microsoft (via Microsoft Research)"
    else:
        display_company = job.company
        company_field_val = job.company

    title = f"{badge} · {emoji} {job.role_type.title()} · {display_company}"

    # Location priority
    if job.priority == "preferred":
        budget = _DISCORD_TITLE_MAX - len(title) - len(" [PRIORITY: ]")
        loc_str = job.location or ""
        if len(loc_str) > budget:
            loc_str = loc_str[: max(budget - 1, 0)].rstrip(" ;,") + "…"
        title += f" [PRIORITY: {loc_str}]"

    title = sanitize_discord_text(title, _DISCORD_TITLE_MAX)
    desc = sanitize_discord_text(job.title, 256)

    # Format timestamps in PT
    try:
        import zoneinfo
        pt_tz = zoneinfo.ZoneInfo("America/Los_Angeles")
        detected_str = _fmt_ts(job.detected_at.astimezone(pt_tz), _PT_FORMAT)
        posted_str = (
            _fmt_ts(job.posted_at.astimezone(pt_tz), _PT_FORMAT)
            if job.posted_at is not None
            else "Unknown"
        )
    except Exception:
        detected_str = _fmt_ts(job.detected_at, _UTC_FORMAT)
        posted_str = (
            _fmt_ts(job.posted_at, _UTC_FORMAT)
            if job.posted_at is not None
            else "Unknown"
        )

    # Department / category
    dept_parts = [p for p in [job.department, job.category] if p]
    dept_str = " / ".join(dept_parts) if dept_parts else "N/A"

    # Role verification
    v_level = getattr(job.verdict, "career_level", None) if job.verdict else job.role_type
    if v_level == "new_grad":
        verif_str = "Full-Time New Grad (Verified)"
    elif v_level in ("entry_level", "junior"):
        verif_str = "Full-Time Entry-Level (Verified)"
    elif job.role_type == "new-grad":
        verif_str = "Full-Time New Grad (Verified)"
    else:
        verif_str = f"Full-Time {job.role_type.title()} (Verified)"

    # Referral status
    raw_ref = getattr(job, "referral_status", "unconfirmed") or "unconfirmed"
    ref_title = raw_ref.replace("_", " ").title()
    if getattr(job, "network_priority", False):
        ref_val = f"{ref_title} (Original Cohort)"
    else:
        ref_val = ref_title

    fields = [
        {"name": "📍 Location", "value": sanitize_discord_text(job.location or "Not specified", 256), "inline": True},
        {"name": "🏢 Company", "value": sanitize_discord_text(company_field_val, 256), "inline": True},
        {"name": "📋 Verification", "value": verif_str, "inline": True},
        {"name": "🤝 Referral Status", "value": ref_val, "inline": True},
        {"name": "📅 Posted", "value": posted_str, "inline": True},
        {"name": "🕐 Detected", "value": detected_str, "inline": True},
        {
            "name": "🏷️ Tags",
            "value": sanitize_discord_text(f"{job.role_type} · {job.source_platform} · {job.priority}", 256),
            "inline": True,
        },
        {"name": "🔗 Direct URL", "value": sanitize_url(job.url), "inline": False},
    ]

    # Salary ONLY when verified
    sal = getattr(job, "salary", None)
    if sal:
        fields.append({"name": "💰 Salary", "value": sanitize_discord_text(str(sal), 256), "inline": True})

    color = 0xFEE75C if getattr(job, "network_priority", False) else 0x5865F2

    return {
        "title": title,
        "description": desc,
        "fields": fields,
        "color": color,
    }


class Notifier:
    def __init__(self, webhook_url: str):
        self._url = webhook_url
        self._bucket = TokenBucket()

    def send_job_alert(self, job: Job) -> bool:
        """Send one Discord embed for a job. Returns True on success."""
        embed = build_job_embed(job)
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
