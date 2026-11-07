from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from decimal import Decimal

ROLE_TYPES = {"internship", "new-grad", "entry-level", "unknown"}
PRIORITY_TYPES = {"preferred", "normal"}


@dataclass(frozen=True)
class CompensationRange:
    """An explicitly published salary/pay range, never annualized or equity-summed."""
    minimum: Decimal | None
    maximum: Decimal | None
    currency: str
    interval: str | None
    source_field: str
    label: str = ""


@dataclass(frozen=True)
class Job:
    id: str
    company: str
    title: str
    location: str
    department: str | None
    category: str | None
    url: str
    source_platform: str
    posted_at: datetime | None
    detected_at: datetime
    raw_text: str  # lowercased corpus: title+location+dept+cat+description if available
    role_type: str  # "internship" | "new-grad" | "entry-level" | "unknown"
    priority: str   # "preferred" | "normal"
    matched_keywords: tuple[str, ...]  # use tuple so dataclass stays hashable/frozen
    verdict: Any = None
    network_priority: bool = False
    cohort: str = "discovered"  # "original_2026_11_04" | "discovered"
    referral_status: str = "unavailable"  # "unconfirmed" | "unavailable" | etc.
    salary: str | None = None
    # P2-A: optional source facts; defaults preserve every existing constructor.
    source_url: str | None = None
    source_board: str | None = None
    source_job_id: str | None = None
    source_internal_job_id: str | None = None
    source_updated_at: datetime | None = None
    posted_at_kind: str = "posted"
    employment_type: str | None = None
    description_complete: bool | None = None
    compensation: tuple[CompensationRange, ...] = ()

    def __post_init__(self):
        if self.role_type not in ROLE_TYPES:
            raise ValueError(f"Invalid role_type: {self.role_type!r}. Must be one of {ROLE_TYPES}")
        if self.priority not in PRIORITY_TYPES:
            raise ValueError(f"Invalid priority: {self.priority!r}. Must be one of {PRIORITY_TYPES}")
