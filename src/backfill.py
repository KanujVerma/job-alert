"""One bounded, resumable Discord backfill batch per scan.

Only postings *actually visible in a successfully delivered summary* are
marked alerted. Unshown postings remain pending for the next scheduled scan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Protocol
from urllib.parse import urlparse

from src.models import Job
from src.storage import (
    POLICY_VERSION,
    is_url_alerted,
    mark_alerted,
    mark_backfill_completed,
    normalize_url,
    record_alerted_url,
)

logger = logging.getLogger(__name__)
MAX_BACKFILL_JOBS_PER_BATCH = 10
MAX_SUMMARY_DESCRIPTION = 3800


class SummarySender(Protocol):
    def send_summary(self, title: str, description: str) -> bool: ...


@dataclass(frozen=True)
class BackfillBatchResult:
    delivered: int
    remaining: int
    completed: bool
    attempted: bool


def _safe_line(job: Job) -> str | None:
    from src.notifier import sanitize_discord_text

    url = (job.url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("https", "http") or not parsed.netloc:
        return None
    # Plain URLs avoid job-title Markdown-link injection or escaped mentions.
    name = sanitize_discord_text(job.company, max_len=55).replace("\n", " ")
    title = sanitize_discord_text(job.title, max_len=130).replace("\n", " ")
    loc = sanitize_discord_text(job.location or "location unspecified", max_len=70).replace("\n", " ")
    return f"• {name}: {title} ({loc})\n  {url}"


def deliver_backfill_batch(
    jobs: list[Job],
    state: dict,
    notifier: SummarySender | None,
    *,
    now: datetime | None = None,
    policy_version: str = POLICY_VERSION,
    max_items: int = MAX_BACKFILL_JOBS_PER_BATCH,
) -> BackfillBatchResult:
    """Send at most one summary of 1..max_items jobs. A 2xx is the only ACK.

    Later calls safely skip already-ACKed canonical URLs. The policy migration
    stays pending when some candidates have not been displayed. No resetting
    existing seen state or sending a second unbounded summary in one run.
    """
    if max_items < 1 or max_items > MAX_BACKFILL_JOBS_PER_BATCH:
        raise ValueError(f"max_items must be 1..{MAX_BACKFILL_JOBS_PER_BATCH}")
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        raise ValueError("backfill timestamp must be timezone aware")

    unique: list[Job] = []
    seen: set[str] = set()
    for job in jobs:
        key = normalize_url(job.url)
        if not key or key in seen or is_url_alerted(job.url, state):
            continue
        seen.add(key)
        unique.append(job)

    if not unique:
        mark_backfill_completed(state, policy_version, now)
        return BackfillBatchResult(0, 0, True, False)

    if notifier is None:
        logger.warning("No Discord notifier: %s backfill opportunities remain unalerted", len(unique))
        return BackfillBatchResult(0, len(unique), False, False)

    # Reserve space for header and continuation count, and never ACK a job whose
    # line could not be included in the Discord embed.
    lines: list[str] = []
    shown: list[Job] = []
    for job in unique:
        if len(shown) >= max_items:
            break
        line = _safe_line(job)
        if line is None:
            logger.warning("Backfill candidate %s has no usable direct URL; not acknowledging", job.id)
            continue
        if len("\n".join(lines)) + len(line) + 200 > MAX_SUMMARY_DESCRIPTION:
            # Leave an oversized posting pending rather than hiding it and
            # acknowledging it without its actual direct URL.
            logger.warning("Backfill candidate %s exceeds safe embed size; leaving pending", job.id)
            continue
        lines.append(line)
        shown.append(job)

    if not shown:
        logger.error("Backfill payload cannot represent the first candidate; leaving all jobs pending")
        return BackfillBatchResult(0, len(unique), False, False)

    remaining = len(unique) - len(shown)
    description = (
        f"Verified-eligible backfill: showing {len(shown)} of {len(unique)} "
        "currently unalerted opportunities from the last 7 days.\n"
        + "\n".join(lines)
        + (f"\n{remaining} remaining; next scheduled run will continue." if remaining else "")
    )
    try:
        delivered = bool(notifier.send_summary(title="Phase 1 Policy Backfill (Last 7 Days)", description=description))
    except Exception:
        logger.exception("Backfill summary delivery failed")
        delivered = False

    if not delivered:
        return BackfillBatchResult(0, len(unique), False, True)

    for job in shown:
        mark_alerted([job], job.company, state)
        record_alerted_url(job.url, job.company, job.id, state, now)
    if remaining == 0:
        mark_backfill_completed(state, policy_version, now)
    else:
        logger.info("Backfill delivered %s visible links; %s remain for later runs", len(shown), remaining)
    return BackfillBatchResult(len(shown), remaining, remaining == 0, True)
