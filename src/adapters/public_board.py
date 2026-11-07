"""Shared safeguards for the *public* Greenhouse/Ashby listing APIs.

No endpoint discovery, authentication, application POSTs or arbitrary next-page
URLs. Both documented list APIs return one complete list. Fail on unexpected
truncation instead of quietly presenting a partial board as healthy/complete.
"""
from __future__ import annotations

import html
import ipaddress
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import parse_qsl, urlsplit, urlunsplit

import requests
from bs4 import BeautifulSoup
from bs4.element import Comment, Declaration, Doctype, ProcessingInstruction

from src.http import HTTPClient
from src.models import CompensationRange

logger = logging.getLogger(__name__)
MAX_RESPONSE_BYTES = 16 * 1024 * 1024
MAX_DESCRIPTION_CHARS = 250_000
MAX_JOBS = 10_000
MAX_DETAIL_REQUESTS = 10
HOSTED = {
    "greenhouse": frozenset({"boards.greenhouse.io", "job-boards.greenhouse.io"}),
    "ashby": frozenset({"jobs.ashbyhq.com"}),
}
_SLUG = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{0,99}\Z")
_SENSITIVE_QUERY = {"token", "access_token", "api_key", "apikey", "authorization", "password"}


class PublicBoardError(RuntimeError):
    """A source/config/schema failure, not an empty healthy board."""


@dataclass(frozen=True)
class PublicBoardConfig:
    platform: str
    slug: str
    board_url: str
    employer_careers_url: str
    allowed_job_hosts: frozenset[str]
    detail_limit: int = 0


def public_https_url(value: object, allowed_hosts: frozenset[str] | None = None) -> str | None:
    """Validate display/provenance URLs; no requests are made to these links."""
    if not isinstance(value, str) or not value or len(value) > 2048:
        return None
    if any(ord(c) < 33 or c in "<>\\" for c in value):
        return None
    try:
        p = urlsplit(value)
        host = (p.hostname or "").lower()
        if p.scheme != "https" or not host or p.username or p.password or p.port not in (None, 443):
            return None
        if host in {"localhost", "metadata.google.internal"} or host.endswith((".localhost", ".local", ".internal")):
            return None
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if "." not in host:
                return None
        else:
            return None  # no IP literals, including public ones, for job links
        if allowed_hosts is not None and host not in allowed_hosts:
            return None
        if any(k.lower() in _SENSITIVE_QUERY for k, _ in parse_qsl(p.query)):
            return None
        return urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))
    except (TypeError, ValueError):
        return None


def validate_public_board_config(platform: str, config: dict) -> PublicBoardConfig:
    if platform not in HOSTED or not isinstance(config, dict):
        raise ValueError("unsupported public board platform/config")
    key = "board_token" if platform == "greenhouse" else "board_name"
    slug = config.get(key)
    if not isinstance(slug, str) or not _SLUG.fullmatch(slug):
        raise ValueError(f"{platform} requires an unencoded public {key} (letters/digits/_/-)")
    board = public_https_url(config.get("board_url"), HOSTED[platform])
    employer = public_https_url(config.get("employer_careers_url"))
    if not board or urlsplit(board).path.strip("/") != slug or urlsplit(board).query:
        raise ValueError(f"{platform}: board_url must be the matching hosted board, not an API endpoint")
    if not employer:
        raise ValueError(f"{platform}: employer_careers_url must be a verified public HTTPS employer page")
    limit = config.get("detail_limit", 0)
    if type(limit) is not int or not 0 <= limit <= MAX_DETAIL_REQUESTS:
        raise ValueError(f"detail_limit must be 0..{MAX_DETAIL_REQUESTS}")
    # Extra application hosts are an explicit, reviewable allowlist, never a wildcard.
    extra = config.get("allowed_job_hosts", [])
    if not isinstance(extra, list) or len(extra) > 8:
        raise ValueError("allowed_job_hosts must be a list of at most 8 exact public hostnames")
    hosts = set(HOSTED[platform]) | {urlsplit(employer).hostname.lower()}
    for host in extra:
        if not isinstance(host, str) or any(c in host for c in "/:@*?#") or not public_https_url(f"https://{host}"):
            raise ValueError("allowed_job_hosts contains an invalid public hostname")
        hosts.add(host.lower())
    if any(k in config for k in ("api_url", "base_url", "api_key", "token", "authorization")):
        raise ValueError("public-board adapters do not accept custom endpoints or credentials")
    return PublicBoardConfig(platform, slug, board, employer, frozenset(hosts), limit)


def read_public_json(http: HTTPClient, endpoint: str, params: dict | None = None) -> dict:
    """Bounded GET with shared retry policy; source errors propagate to health."""
    response = None
    try:
        response = http.get(endpoint, params=params or {}, allow_redirects=False, stream=True)
        if response.status_code != 200:
            raise PublicBoardError(f"public listing returned HTTP {response.status_code}")
        if 'rel="next"' in response.headers.get("Link", ""):
            raise PublicBoardError("unexpected pagination: public board response is incomplete")
        size = 0
        chunks = []
        for part in response.iter_content(chunk_size=65536):
            size += len(part)
            if size > MAX_RESPONSE_BYTES:
                raise PublicBoardError("public board response exceeds bounded size")
            chunks.append(part)
        def reject_constant(_):
            raise ValueError("non-finite JSON constant")
        payload = json.loads(b"".join(chunks), parse_constant=reject_constant)
        if not isinstance(payload, dict):
            raise PublicBoardError("public board response must be a JSON object")
        return payload
    except (requests.RequestException, ValueError) as error:
        # Do not include source response text, headers, query credentials, or HTML in logs.
        if isinstance(error, requests.HTTPError) and error.response is not None:
            status = error.response.status_code
            error.response.close()
            raise PublicBoardError(f"public board HTTP {status}") from None
        raise PublicBoardError(f"public board read failed ({type(error).__name__})") from None
    finally:
        if response is not None:
            response.close()


def listing_rows(payload: dict, *, greenhouse: bool = False) -> list[dict]:
    rows = payload.get("jobs")
    if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
        raise PublicBoardError("jobs must be an array of objects")
    if len(rows) > MAX_JOBS:
        raise PublicBoardError("board exceeds explicit job-count bound; refusing partial scan")
    for key in ("next", "nextPage", "nextCursor", "next_page_token", "hasMore", "has_more"):
        if payload.get(key):
            raise PublicBoardError("unexpected pagination; do not infer unverified API cursor semantics")
    if greenhouse and "meta" in payload:
        meta = payload["meta"]
        if not isinstance(meta, dict):
            raise PublicBoardError("invalid Greenhouse metadata")
        total = meta.get("total")
        if total is not None and (type(total) is not int or total != len(rows)):
            raise PublicBoardError("Greenhouse meta.total does not match returned list; incomplete/invalid source")
    return rows


def text(value: object) -> str:
    if not isinstance(value, str):
        return ""
    return "".join(c for c in value if c in "\n\t" or ord(c) >= 32).strip()


def description(value: object, *, is_html: bool) -> tuple[str, bool]:
    value = text(value)
    if is_html and value:
        # Greenhouse frequently double-encodes editor markup.
        for _ in range(3):
            decoded = html.unescape(value)
            if decoded == value:
                break
            value = decoded
        soup = BeautifulSoup(value, "html.parser")
        for node in soup(["script", "style", "iframe", "template", "noscript"]):
            node.decompose()
        # HTML whitespace inside a text node is layout, not a requirement
        # boundary. Inline formatting must not split "5 years" from "of
        # professional experience": only block elements and <br> add breaks.
        for node in list(soup.find_all(string=True)):
            if isinstance(node, (Comment, Declaration, Doctype, ProcessingInstruction)):
                node.extract()
            else:
                node.replace_with(re.sub(r"\s+", " ", str(node)))
        for node in soup.find_all("br"):
            node.replace_with("\n")
        for node in soup.find_all([
            "p", "div", "li", "ul", "ol", "section", "article", "header",
            "footer", "h1", "h2", "h3", "h4", "h5", "h6", "tr", "dt",
            "dd", "table", "blockquote", "pre",
        ]):
            node.insert_before("\n")
            node.insert_after("\n")
        value = "\n".join(
            re.sub(r"[ \t]+", " ", line).strip()
            for line in soup.get_text(" ", strip=False).splitlines()
            if line.strip()
        )
    complete = bool(value) and len(value) <= MAX_DESCRIPTION_CHARS
    return value[:MAX_DESCRIPTION_CHARS], complete


def timestamp(value: object) -> datetime | None:
    if not isinstance(value, str) or "T" not in value:
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return dt.astimezone(timezone.utc) if dt.tzinfo is not None else None
    except ValueError:
        return None


def unique_parts(parts: list[str], sep: str = "; ") -> str:
    return sep.join(dict.fromkeys(p.strip() for p in parts if isinstance(p, str) and p.strip()))


def postal_address(value: object) -> str:
    if not isinstance(value, dict):
        return ""
    value = value.get("postalAddress", value)
    if not isinstance(value, dict):
        return ""
    return unique_parts([text(value.get(k)) for k in ("addressLocality", "addressRegion", "addressCountry")], ", ")


def amount(value: object) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (int, float, str, Decimal)):
        return None
    try:
        n = Decimal(str(value))
        return n if n.is_finite() and 0 <= n <= Decimal("100000000000") else None
    except InvalidOperation:
        return None


def pay_range(low: object, high: object, currency: object, interval: str | None,
              source_field: str, label: object = "", divisor: int = 1) -> CompensationRange | None:
    if not isinstance(currency, str) or not re.fullmatch(r"[A-Z]{3}", currency):
        return None
    lo, hi = amount(low), amount(high)
    if (low is not None and lo is None) or (high is not None and hi is None):
        return None
    if lo is None and hi is None or lo is not None and hi is not None and lo > hi:
        return None
    return CompensationRange(
        minimum=lo / divisor if lo is not None else None,
        maximum=hi / divisor if hi is not None else None,
        currency=currency, interval=interval, source_field=source_field,
        label=text(label)[:100],
    )


def format_pay(ranges: tuple[CompensationRange, ...]) -> str | None:
    output = []
    for item in ranges:
        def fmt(n: Decimal) -> str:
            return f"{n:,.2f}".rstrip("0").rstrip(".") if n % 1 else f"{n:,.0f}"
        if item.minimum is not None and item.maximum is not None:
            span = f"{fmt(item.minimum)}–{fmt(item.maximum)}"
        elif item.minimum is not None:
            span = f"from {fmt(item.minimum)}"
        else:
            span = f"up to {fmt(item.maximum)}"
        units = {"1 YEAR": "year", "1 MONTH": "month", "1 HOUR": "hour"}
        interval = units.get(item.interval, "period unspecified")
        label = f" [{item.label}]" if item.label else ""
        output.append(f"{item.currency} {span} / {interval}{label}")
    return "; ".join(output) or None
