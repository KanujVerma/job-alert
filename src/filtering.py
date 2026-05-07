from __future__ import annotations
import dataclasses
import hashlib
import re
import unicodedata
from typing import NamedTuple

from src.models import Job

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

US_STATE_CODES = {
    "AL", "AK", "AZ", "AR", "CA", "CO", "CT", "DE", "FL", "GA",
    "HI", "ID", "IL", "IN", "IA", "KS", "KY", "LA", "ME", "MD",
    "MA", "MI", "MN", "MS", "MO", "MT", "NE", "NV", "NH", "NJ",
    "NM", "NY", "NC", "ND", "OH", "OK", "OR", "PA", "RI", "SC",
    "SD", "TN", "TX", "UT", "VT", "VA", "WA", "WV", "WI", "WY", "DC"
}

US_TECH_CITIES = {
    "san francisco", "san jose", "mountain view", "palo alto", "sunnyvale",
    "santa clara", "seattle", "bellevue", "redmond", "new york", "brooklyn",
    "austin", "boston", "cambridge", "chicago", "los angeles", "santa monica",
    "san diego", "denver", "boulder", "atlanta", "portland", "phoenix",
    "salt lake city", "houston", "dallas", "raleigh", "durham", "pittsburgh",
    "washington dc", "washington d.c.", "arlington", "minneapolis", "folsom",
    "reno", "hillsboro", "detroit", "ann arbor", "miami", "tampa", "nashville",
    "charlotte", "columbus", "madison", "boise", "richmond", "sacramento",
    "san antonio", "fort worth", "orlando", "indianapolis", "kansas city",
    "cincinnati", "cleveland", "milwaukee", "memphis", "new haven"
}

NON_US_SIGNALS = {
    "india", "canada", "uk", "united kingdom", "germany", "france", "australia",
    "japan", "china", "singapore", "mexico", "brazil", "ireland", "netherlands",
    "sweden", "norway", "denmark", "finland", "switzerland", "spain", "italy",
    "poland", "czech republic", "romania", "hungary", "budapest",
    "bangalore", "mumbai", "delhi", "hyderabad",
    "toronto", "vancouver", "montreal",
    "london", "berlin", "paris",
    "sydney", "melbourne", "tokyo", "beijing", "shanghai", "seoul",
    "amsterdam", "dublin", "stockholm", "oslo", "zurich", "madrid", "rome",
    "warsaw", "prague", "bucharest",
}


# ---------------------------------------------------------------------------
# FilterResult
# ---------------------------------------------------------------------------

class FilterResult(NamedTuple):
    passes: bool
    reason: str


# ---------------------------------------------------------------------------
# Helper utilities
# ---------------------------------------------------------------------------

def _word_in_text(word: str, text: str) -> bool:
    """Check if word/phrase exists as a whole-word match in text (lowercased)."""
    # Escape special regex chars; for multi-word phrases allow any whitespace
    escaped = re.escape(word)
    pattern = r"(?<![a-z0-9])" + escaped + r"(?![a-z0-9])"
    return bool(re.search(pattern, text))


def _phrase_in_text(phrase: str, text: str) -> bool:
    """Case-insensitive substring check for phrases (multi-word ok)."""
    return phrase in text


# ---------------------------------------------------------------------------
# Filter functions
# ---------------------------------------------------------------------------

def filter_location(job: Job, filters: dict) -> FilterResult:
    """Step 1: Location filter."""
    location_lower = (job.location or "").lower()
    raw = job.raw_text.lower() if job.raw_text else ""
    combined = f"{location_lower} {raw}"

    # Check NON_US_SIGNALS first (word-boundary match)
    for signal in NON_US_SIGNALS:
        pattern = r"(?<![a-z])" + re.escape(signal) + r"(?![a-z])"
        if re.search(pattern, combined):
            return FilterResult(False, f"non-US location: {signal}")

    # Explicit US signals
    for us_signal in ("united states", "usa", "u.s.", "remote"):
        if us_signal in combined:
            return FilterResult(True, f"US confirmed: {us_signal}")

    # US state codes (2-letter word-boundary)
    for code in US_STATE_CODES:
        pattern = r"(?<![a-zA-Z])" + re.escape(code) + r"(?![a-zA-Z])"
        if re.search(pattern, location_lower) or re.search(pattern, raw):
            return FilterResult(True, f"US state code: {code}")

    # US tech cities
    for city in US_TECH_CITIES:
        if city in combined:
            return FilterResult(True, f"US city match: {city}")

    # Empty/ambiguous location
    if not location_lower.strip():
        return FilterResult(True, "location ambiguous")

    return FilterResult(True, "location ambiguous")


def filter_exclude(job: Job, filters: dict) -> FilterResult:
    """Step 2: Exclude filter."""
    raw = job.raw_text.lower() if job.raw_text else ""

    # Hard excludes
    for kw in filters.get("exclude_keywords", []):
        if _phrase_in_text(kw.lower(), raw):
            return FilterResult(False, f"excluded keyword: {kw}")

    # Exclude-unless-intern
    early_career_kws = [k.lower() for k in filters.get("early_career_keywords", [])]
    technical_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]

    for kw in filters.get("exclude_unless_intern", []):
        if _phrase_in_text(kw.lower(), raw):
            has_early = any(_phrase_in_text(ek, raw) for ek in early_career_kws)
            has_tech = any(_phrase_in_text(tk, raw) for tk in technical_kws)
            if not (has_early and has_tech):
                return FilterResult(False, f"excluded unless intern: {kw}")

    return FilterResult(True, "no excluded keywords")


def filter_early_career(job: Job, filters: dict) -> FilterResult:
    """Step 3: Early-career filter."""
    raw = job.raw_text.lower() if job.raw_text else ""

    for kw in filters.get("early_career_keywords", []):
        if _phrase_in_text(kw.lower(), raw):
            return FilterResult(True, f"early-career keyword: {kw}")

    if job.role_type == "internship":
        return FilterResult(True, "adapter hint: internship source")

    return FilterResult(False, "no early-career signal")


def filter_tech_role(job: Job, filters: dict) -> FilterResult:
    """Step 4: Technical role filter."""
    raw = job.raw_text.lower() if job.raw_text else ""

    for kw in filters.get("technical_role_keywords", []):
        if _phrase_in_text(kw.lower(), raw):
            return FilterResult(True, f"tech keyword: {kw}")

    return FilterResult(False, "no technical role signal")


def filter_per_company_override(
    job: Job,
    filters: dict,
    source_config: dict,
) -> FilterResult:
    """Step 5: Per-company/source override filter."""
    if source_config.get("require_early_career"):
        raw = job.raw_text.lower() if job.raw_text else ""
        early_career_kws = [k.lower() for k in filters.get("early_career_keywords", [])]
        has_early = any(_phrase_in_text(ek, raw) for ek in early_career_kws)
        if not has_early and job.role_type != "internship":
            return FilterResult(False, "per-source early-career required")

    return FilterResult(True, "no override")


def label_job(job: Job, filters: dict, location_ambiguous: bool) -> Job:
    """Step 6: Derive role_type, priority, matched_keywords. Returns new frozen Job."""
    raw = job.raw_text.lower() if job.raw_text else ""

    # Role type detection
    if job.role_type == "internship":
        role_type = "internship"
    elif any(phrase in raw for phrase in ["intern", "internship", "co-op"]):
        role_type = "internship"
    elif any(phrase in raw for phrase in [
        "new grad", "new graduate", "graduate program", "campus hire", "university graduate"
    ]):
        role_type = "new-grad"
    elif any(phrase in raw for phrase in ["entry level", "entry-level", "associate "]):
        role_type = "entry-level"
    else:
        role_type = "unknown"

    # Priority
    if location_ambiguous:
        priority = "normal"
    else:
        loc_lower = (job.location or "").lower()
        preferred = filters.get("preferred_locations", [])
        if any(pl.lower() in loc_lower for pl in preferred):
            priority = "preferred"
        else:
            priority = "normal"

    # Matched keywords
    early_career_kws = [k.lower() for k in filters.get("early_career_keywords", [])]
    technical_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]
    matched = []
    for kw in early_career_kws + technical_kws:
        if _phrase_in_text(kw, raw) and kw not in matched:
            matched.append(kw)

    # Return new frozen Job with updated fields
    return dataclasses.replace(
        job,
        role_type=role_type,
        priority=priority,
        matched_keywords=tuple(matched),
    )


# ---------------------------------------------------------------------------
# Pipeline
# ---------------------------------------------------------------------------

def apply_filter_pipeline(
    job: Job,
    filters: dict,
    source_config: dict,
) -> tuple[Job | None, list[str]]:
    """
    Run all 6 filter steps. Returns (filtered_job, reasons).
    filtered_job is None if the job was dropped.
    reasons is a list of strings explaining each step outcome (for --verbose logging).
    """
    reasons = []

    # Step 1: Location
    result = filter_location(job, filters)
    reasons.append(f"location: {result.reason}")
    if not result.passes:
        return None, reasons
    location_ambiguous = "ambiguous" in result.reason

    # Step 2: Exclude
    result = filter_exclude(job, filters)
    reasons.append(f"exclude: {result.reason}")
    if not result.passes:
        return None, reasons

    # Step 3: Early career
    result = filter_early_career(job, filters)
    reasons.append(f"early_career: {result.reason}")
    if not result.passes:
        return None, reasons

    # Step 4: Tech role
    result = filter_tech_role(job, filters)
    reasons.append(f"tech_role: {result.reason}")
    if not result.passes:
        return None, reasons

    # Step 5: Per-company override
    result = filter_per_company_override(job, filters, source_config)
    reasons.append(f"per_company: {result.reason}")
    if not result.passes:
        return None, reasons

    # Step 6: Label job
    labelled = label_job(job, filters, location_ambiguous)
    reasons.append(f"label: role_type={labelled.role_type} priority={labelled.priority}")

    return labelled, reasons


# ---------------------------------------------------------------------------
# ID utilities
# ---------------------------------------------------------------------------

def normalize_for_hash(text: str) -> str:
    """Lowercase, collapse whitespace, strip non-alphanumeric except spaces."""
    text = text.lower()
    # Strip non-alphanumeric except spaces
    text = re.sub(r"[^a-z0-9 ]", "", text)
    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()
    return text


def make_job_id(
    company: str,
    source_platform: str,
    title: str,
    location: str,
    official_id: str | None = None,
) -> str:
    """
    If official_id provided: return "company::source_platform::official_id".
    Otherwise: sha1 of "company::normalized_title::normalized_location::source_platform",
               return first 16 hex chars.
    """
    if official_id:
        return f"{company}::{source_platform}::{official_id}"

    parts = "::".join([
        normalize_for_hash(company),
        normalize_for_hash(title),
        normalize_for_hash(location),
        normalize_for_hash(source_platform),
    ])
    return hashlib.sha1(parts.encode()).hexdigest()[:16]
