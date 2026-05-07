from __future__ import annotations
from abc import ABC, abstractmethod
from collections.abc import Iterator

from src.models import Job
from src.http import HTTPClient


class BaseAdapter(ABC):
    source_platform: str  # class-level constant, e.g. "workday"

    def __init__(self, company: str, config: dict, http: HTTPClient):
        self.company = company
        self.config = config
        self.http = http

    @abstractmethod
    def fetch(self) -> Iterator[Job]:
        """
        Yield normalized Job objects.
        - Set role_type hint if this is a known intern-only source.
        - Include official job ID if source provides one.
        - Populate raw_text from available list-response fields only (no extra HTTP).
        - Never raise — log errors and yield nothing on failure.
        """
