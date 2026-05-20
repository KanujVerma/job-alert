from __future__ import annotations
import dataclasses
import hashlib
import re
from datetime import datetime, timezone
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

_NON_US_COUNTRY_CODES = {
    "in", "ca", "gb", "de", "fr", "au", "jp", "cn", "tw", "sg", "kr",
    "mx", "br", "ie", "nl", "se", "no", "dk", "fi", "ch", "es", "it",
    "pl", "cz", "ro", "hu", "il", "tr", "ae", "sa", "pk", "ph", "id",
    "my", "vn", "th", "hk", "nz", "ar", "co", "cl", "pe", "ng", "ke",
    "za", "ua", "ru", "bd", "lk", "qa", "kw", "bh", "om", "eg",
}

_NON_US_COUNTRY_CODES_3 = {
    # Asia Pacific
    "twn", "jpn", "chn", "kor", "ind", "aus", "nzl", "sgp", "hkg",
    "mys", "tha", "idn", "phl", "vnm",
    # Europe
    "gbr", "deu", "fra", "irl", "nld", "swe", "nor", "dnk", "fin",
    "che", "esp", "ita", "pol", "cze", "rou", "hun", "bel", "prt",
    "aut", "hrv", "svk", "grc", "srb",
    # Americas (non-US)
    "can", "mex", "bra", "arg", "col", "chl", "per", "cri", "pan",
    "gtm", "hnd", "slv", "nic",
    # Middle East / Africa / Other
    "isr", "tur", "are", "sau", "qat", "kwt", "bhr", "omn", "egy",
    "nga", "ken", "zaf", "ukr", "rus", "pak", "bgd", "lka",
}

NON_US_SIGNALS = {
    # Countries — major
    "india", "canada", "uk", "united kingdom", "germany", "france", "australia",
    "japan", "china", "singapore", "mexico", "brazil", "ireland", "netherlands",
    "sweden", "norway", "denmark", "finland", "switzerland", "spain", "italy",
    "poland", "czech republic", "romania", "hungary",
    "taiwan", "south korea", "korea", "philippines", "indonesia", "malaysia",
    "vietnam", "thailand", "hong kong", "new zealand",
    "argentina", "colombia", "chile", "peru",
    "israel", "turkey", "türkiye",
    "uae", "united arab emirates", "saudi arabia", "qatar", "kuwait", "bahrain", "oman",
    "egypt", "nigeria", "kenya", "south africa",
    "pakistan", "bangladesh", "sri lanka",
    "ukraine", "russia",
    # Countries — Central America / Caribbean
    "costa rica", "panama", "guatemala", "honduras", "nicaragua", "el salvador",
    # Countries — Europe (additions)
    "austria", "belgium", "portugal", "croatia", "serbia", "greece", "slovakia",
    # Cities — Europe (Western)
    "budapest", "london", "berlin", "paris", "amsterdam", "dublin", "stockholm",
    "oslo", "zurich", "madrid", "rome", "warsaw", "prague", "bucharest",
    "brussels", "lisbon", "porto",
    # Cities — Austria
    "vienna", "graz", "villach", "linz", "salzburg",
    # Cities — Southeast Europe
    "athens", "zagreb", "belgrade",
    # Cities — India
    "bangalore", "bengaluru", "mumbai", "delhi", "hyderabad", "chennai", "pune", "kolkata",
    # Cities — Canada
    "toronto", "vancouver", "montreal", "ottawa", "calgary",
    # Cities — Australia / NZ
    "sydney", "melbourne", "brisbane", "perth", "auckland", "wellington",
    # Cities — East Asia
    "tokyo", "osaka", "beijing", "shanghai", "guangzhou", "shenzhen",
    "seoul", "busan", "taipei", "tainan", "taichung", "kaohsiung", "hsinchu",
    "hong kong",
    # Cities — Southeast Asia
    "manila", "jakarta", "kuala lumpur", "petaling jaya", "bangkok", "ho chi minh", "hanoi",
    # Cities — Middle East
    "dubai", "abu dhabi", "riyadh", "jeddah", "doha", "tel aviv", "jerusalem",
    "istanbul", "ankara",
    # Cities — Africa / LatAm
    "cairo", "nairobi", "lagos", "cape town", "johannesburg",
    "buenos aires", "bogota", "santiago", "lima",
    # Cities — EE / Russia
    "moscow", "kyiv",
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

def filter_freshness(job: Job, filters: dict) -> FilterResult:
    """Step 0: Drop jobs older than freshness_hours when posted_at is known."""
    freshness_hours = filters.get("freshness_hours")
    if not freshness_hours:
        return FilterResult(True, "not configured")
    if job.posted_at is None:
        return FilterResult(True, "posted_at unknown, allowing")
    now = datetime.now(timezone.utc)
    age_hours = (now - job.posted_at).total_seconds() / 3600
    if age_hours > float(freshness_hours):
        return FilterResult(False, f"stale: {age_hours:.0f}h old (limit {freshness_hours}h)")
    return FilterResult(True, f"fresh: {age_hours:.0f}h old")


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

    # ISO country code checks — parse comma-separated location parts
    loc_parts = [p.strip() for p in location_lower.split(",")]

    # 2-letter ISO code in "city, region, COUNTRY" (3+ parts, to avoid "Denver, CO" false match)
    if len(loc_parts) >= 3 and len(loc_parts[-1]) == 2 and loc_parts[-1].isalpha():
        last = loc_parts[-1]
        if last == "us":
            return FilterResult(True, "US country code")
        if last in _NON_US_COUNTRY_CODES:
            return FilterResult(False, f"non-US country code: {last.upper()}")

    # 3-letter ISO code in "city, COUNTRY" (2+ parts — safe since no US state uses 3 letters)
    if len(loc_parts) >= 2 and len(loc_parts[-1]) == 3 and loc_parts[-1].isalpha():
        last3 = loc_parts[-1]
        if last3 == "usa":
            return FilterResult(True, "US country code USA")
        if last3 in _NON_US_COUNTRY_CODES_3:
            return FilterResult(False, f"non-US country code: {last3.upper()}")

    # Explicit US signals
    for us_signal in ("united states", "usa", "u.s.", "remote"):
        if us_signal in combined:
            return FilterResult(True, f"US confirmed: {us_signal}")

    # US state codes (2-letter word-boundary, case-insensitive to match lowercased strings)
    for code in US_STATE_CODES:
        pattern = r"(?<![a-zA-Z])" + re.escape(code) + r"(?![a-zA-Z])"
        if re.search(pattern, location_lower, re.IGNORECASE) or re.search(pattern, raw, re.IGNORECASE):
            return FilterResult(True, f"US state code: {code}")

    # US tech cities
    for city in US_TECH_CITIES:
        if city in combined:
            return FilterResult(True, f"US city match: {city}")

    # Non-empty but unrecognized locations are passed through rather than dropped,
    # to avoid false negatives (e.g. "Hybrid" or vague office names).
    return FilterResult(True, "location ambiguous")


def filter_exclude(job: Job, filters: dict) -> FilterResult:
    """Step 2: Exclude filter."""
    raw = job.raw_text.lower() if job.raw_text else ""

    # Hard excludes — word-boundary match prevents "hr" hitting "chrome", etc.
    for kw in filters.get("exclude_keywords", []):
        if _word_in_text(kw.lower(), raw):
            return FilterResult(False, f"hard exclude: {kw}")

    # Exclude-unless-intern — word-boundary match on the trigger keyword
    early_career_kws = [k.lower() for k in filters.get("early_career_keywords", [])]
    strong_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]
    title_kws = [k.lower() for k in filters.get("title_tech_keywords", [])]
    title_corpus = " ".join(filter(None, [job.title, job.category, job.department])).lower()

    for kw in filters.get("exclude_unless_intern", []):
        if _word_in_text(kw.lower(), raw):
            has_early = any(_phrase_in_text(ek, raw) for ek in early_career_kws)
            has_tech = (
                any(_word_in_text(tk, raw) for tk in strong_kws)
                or any(_word_in_text(tk, title_corpus) for tk in title_kws)
            )
            if not (has_early and has_tech):
                return FilterResult(False, f"conditional exclude (not intern+tech): {kw}")

    return FilterResult(True, "no excluded keywords")


def filter_early_career(job: Job, filters: dict) -> FilterResult:
    """Step 3: Early-career filter."""
    raw = job.raw_text.lower() if job.raw_text else ""

    for kw in filters.get("early_career_keywords", []):
        if _word_in_text(kw.lower(), raw):
            return FilterResult(True, f"early-career keyword: {kw}")

    if job.role_type == "internship":
        return FilterResult(True, "adapter hint: internship source")

    return FilterResult(False, "no early-career signal")


def filter_tech_role(job: Job, filters: dict) -> FilterResult:
    """Step 4: Technical role filter — two tiers.

    Tier 1 (strong): technical_role_keywords matched anywhere in raw_text.
    Tier 2 (title-required): title_tech_keywords matched only in title/category/department.
    """
    raw = job.raw_text.lower() if job.raw_text else ""

    # Tier 1: high-confidence keywords — match anywhere in raw_text
    for kw in filters.get("technical_role_keywords", []):
        if _word_in_text(kw.lower(), raw):
            return FilterResult(True, f"strong tech keyword in raw_text: {kw}")

    # Tier 2: ambiguous keywords — only meaningful when naming the role itself
    title_corpus = " ".join(filter(None, [job.title, job.category, job.department])).lower()
    for kw in filters.get("title_tech_keywords", []):
        if _word_in_text(kw.lower(), title_corpus):
            return FilterResult(True, f"title tech keyword in title/category/dept: {kw}")

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

    # Role type detection — use word boundaries so "international" / "internationalization"
    # don't match as "intern".
    if job.role_type == "internship":
        role_type = "internship"
    elif re.search(r'\b(?:intern(?:ship)?|co-op)\b', raw):
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
        if any(
            re.search(r"(?<![a-z0-9])" + re.escape(pl.lower()) + r"(?![a-z0-9])", loc_lower)
            for pl in preferred
        ):
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

    # Step 0: Freshness
    result = filter_freshness(job, filters)
    reasons.append(f"freshness: {result.reason}")
    if not result.passes:
        return None, reasons

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

    # Step 7: Internship-only mode (optional global gate)
    if filters.get("internship_only") and labelled.role_type != "internship":
        reasons.append("internship_only: dropped")
        return None, reasons

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
