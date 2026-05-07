from __future__ import annotations
from dataclasses import dataclass, field
from datetime import datetime

ROLE_TYPES = {"internship", "new-grad", "entry-level", "unknown"}
PRIORITY_TYPES = {"preferred", "normal"}


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

    def __post_init__(self):
        if self.role_type not in ROLE_TYPES:
            raise ValueError(f"Invalid role_type: {self.role_type!r}. Must be one of {ROLE_TYPES}")
        if self.priority not in PRIORITY_TYPES:
            raise ValueError(f"Invalid priority: {self.priority!r}. Must be one of {PRIORITY_TYPES}")
