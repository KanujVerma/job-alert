from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from src.models import Job

POLICY_VERSION = "2026-11-newgrad-v1"

# Dimension values per docs/CONTRACTS.md
EMPLOYMENT_TYPES = {"full_time", "internship", "co_op", "contract", "part_time", "unknown"}
CAREER_LEVELS = {"new_grad", "entry_level", "junior", "mid", "senior", "unknown"}
ELIGIBILITY_STATUSES = {"eligible", "needs_review", "excluded"}

# Stable machine-readable reason codes
REASON_INTERNSHIP_ROLE = "INTERNSHIP_ROLE"
REASON_CO_OP_ROLE = "CO_OP_ROLE"
REASON_CONTRACT_ROLE = "CONTRACT_ROLE"
REASON_PART_TIME_ROLE = "PART_TIME_ROLE"
REASON_SENIOR_LEVEL = "SENIOR_LEVEL"
REASON_EXPERIENCE_EXCEEDS_RANGE = "EXPERIENCE_EXCEEDS_RANGE"
REASON_NON_TECH_ROLE = "NON_TECH_ROLE"
REASON_PHD_REQUIRED = "PHD_REQUIRED"
REASON_MASTERS_REQUIRED = "MASTERS_REQUIRED"
REASON_DEGREE_MISMATCH = "DEGREE_MISMATCH"
REASON_US_CITIZEN_REQUIRED = "US_CITIZEN_REQUIRED"
REASON_SECURITY_CLEARANCE_REQUIRED = "SECURITY_CLEARANCE_REQUIRED"
REASON_NON_US_ONLY = "NON_US_ONLY"
REASON_GRADUATION_OUTSIDE_WINDOW = "GRADUATION_OUTSIDE_WINDOW"

REASON_COHORT_2027_UNSPECIFIED = "COHORT_2027_UNSPECIFIED"
REASON_AMBIGUOUS_LEVEL = "AMBIGUOUS_LEVEL"
REASON_EXPERIENCE_UNSPECIFIED = "EXPERIENCE_UNSPECIFIED"
REASON_LOCATION_UNKNOWN = "LOCATION_UNKNOWN"
REASON_WORK_AUTH_UNKNOWN = "WORK_AUTH_UNKNOWN"
REASON_FULL_TIME_UNSPECIFIED = "FULL_TIME_UNSPECIFIED"

REASON_CONFIRMED_NEW_GRAD = "CONFIRMED_NEW_GRAD"
REASON_ENTRY_LEVEL_TITLE = "ENTRY_LEVEL_TITLE"
REASON_ZERO_TO_TWO_YEARS = "ZERO_TO_TWO_YEARS"
REASON_TECH_ROLE_CONFIRMED = "TECH_ROLE_CONFIRMED"
REASON_US_LOCATION_CONFIRMED = "US_LOCATION_CONFIRMED"


@dataclass(frozen=True)
class EligibilityVerdict:
    job_id: str
    policy_version: str
    status: str  # "eligible" | "needs_review" | "excluded"
    employment_type: str  # "full_time" | "internship" | "co_op" | "contract" | "part_time" | "unknown"
    career_level: str  # "new_grad" | "entry_level" | "junior" | "mid" | "senior" | "unknown"
    reasons: tuple[str, ...]
    evidence_spans: tuple[str, ...]
    unknowns: tuple[str, ...]

    def __post_init__(self):
        if self.status not in ELIGIBILITY_STATUSES:
            raise ValueError(f"Invalid status: {self.status!r}. Must be one of {ELIGIBILITY_STATUSES}")
        if self.employment_type not in EMPLOYMENT_TYPES:
            raise ValueError(f"Invalid employment_type: {self.employment_type!r}. Must be one of {EMPLOYMENT_TYPES}")
        if self.career_level not in CAREER_LEVELS:
            raise ValueError(f"Invalid career_level: {self.career_level!r}. Must be one of {CAREER_LEVELS}")


# ---------------------------------------------------------------------------
# Regex patterns & vocabulary
# ---------------------------------------------------------------------------

_TECH_TITLE_PATTERNS = [
    r"\bsoftware (?:development\s+)?(?:engineer|engineering|developer)\b",
    r"\bsde\b",
    r"\bswe\b",
    r"\bbackend (?:engineer|developer)\b",
    r"\bfrontend (?:engineer|developer)\b",
    r"\bfull[\s-]?stack (?:engineer|developer)\b",
    r"\bproduct engineer(?:ing)?\b",
    r"\b(?:applied )?ai engineer(?:ing)?\b",
    r"\bforward deployed engineer(?:ing)?\b",
    r"\bfde\b",
    r"\bmachine learning (?:engineer|developer)\b",
    r"\bml (?:engineer|developer)\b",
    r"\bdata engineer(?:ing)?\b",
    r"\bdata scientist\b",
    r"\bapplied scientist\b",
    r"\bcloud engineer(?:ing)?\b",
    r"\bplatform engineer(?:ing)?\b",
    r"\binfrastructure engineer(?:ing)?\b",
    r"\bsystems engineer(?:ing)?\b",
    r"\bsecurity engineer(?:ing)?\b",
    r"\bapplication security engineer\b",
]

_NON_TECH_ROLE_TITLES = [
    r"\bsales (?:associate|development|representative|executive|specialist|analytics|director|manager|lead|ops|operations)\b",
    r"\baccount executive\b",
    r"\bbusiness development\b",
    r"\bcustomer support\b",
    r"\bcustomer success\b",
    r"\bcall center\b",
    r"\brecruiter\b",
    r"\brecruiting\b",
    r"\btalent acquisition\b",
    r"\bhuman resources\b",
    r"\bhr (?:specialist|generalist|coordinator|manager)\b",
    r"\bwarehouse\b",
    r"\bfulfillment\b",
    r"\bretail\b",
    r"\blegal\b",
    r"\bfinance\b",
    r"\baccounting\b",
    r"\bfacilities\b",
    r"\bmaintenance\b",
    r"\bsecurity guard\b",
    r"\boperations specialist\b",
    r"\bmarketing (?:specialist|manager|coordinator)\b",
    r"\bprogram manager\b",
    r"\bproject manager\b",
    r"\bproduct manager\b",
    r"\btpm\b",
    r"\btechnical program manager\b",
]

_SENIOR_TITLE_PATTERN = re.compile(
    r"\b(?:senior|sr|sr\.|staff|principal|lead|director|manager|head of|vp|chief|architect|"
    r"vice\s+president|president|exec(?:utive)?|fellow|distinguished|"
    r"smts|pmts|lmts|"
    r"software\s+(?:development\s+)?engineer\s+(?:3|4|5|6|iii|iv|v|vi)|"
    r"sde\s+(?:3|4|5|6|iii|iv|v|vi)|swe\s+(?:3|4|5|6|iii|iv|v|vi)|"
    r"engineer\s+(?:3|4|5|6|iii|iv|v|vi)|developer\s+(?:3|4|5|6|iii|iv|v|vi)|"
    r"applied\s+scientist\s+(?:3|4|5|6|iii|iv|v|vi)|"
    r"data\s+engineer\s+(?:3|4|5|6|iii|iv|v|vi)|"
    r"\(e[3-9]\)|\(l[4-9]\))\b",
    re.IGNORECASE,
)

_MID_AMBIGUOUS_TITLE_PATTERN = re.compile(
    r"\b(?:software engineer ii|swe ii|engineer ii|sde ii|developer ii|"
    r"software engineer 2|swe 2|engineer 2|sde 2|developer 2|"
    r"software development engineer ii|software development engineer 2|"
    r"applied scientist ii|applied scientist 2|data engineer ii|data engineer 2)\b",
    re.IGNORECASE,
)

_ENTRY_TITLE_PATTERN = re.compile(
    r"\b(?:software engineer i|swe i|engineer i|sde i|developer i|"
    r"software engineer 1|swe 1|engineer 1|sde 1|developer 1|"
    r"software development engineer i|software development engineer 1|"
    r"applied scientist i|applied scientist 1|data engineer i|data engineer 1|"
    r"entry level|entry-level|junior|jr|jr\.|"
    r"associate software engineer|associate engineer|associate developer)\b",
    re.IGNORECASE,
)

_NEW_GRAD_TITLE_PATTERN = re.compile(
    r"\b(?:new grad(?:uate)?|university grad(?:uate)?|campus hire|college graduate|recent graduate|"
    r"(?:early career|university|campus|new grad)\s+graduate program)\b",
    re.IGNORECASE,
)

_NEW_GRAD_BODY_PATTERN = re.compile(
    r"\b(?:new grad(?:uate)?\s+(?:role|position|program|engineer|developer|hire|opportunity|cohort)|"
    r"open to new grads?|recent (?:college|university) graduates?|"
    r"target(?:ing)?\s+(?:new|recent)\s+graduates?|"
    r"graduating between|class of 2026|class of 2027)\b",
    re.IGNORECASE,
)

# Retain backward-compatible alias
_NEW_GRAD_PATTERN = _NEW_GRAD_TITLE_PATTERN

_INTERN_TITLE_PATTERN = re.compile(
    r"\b(?:intern(?:ship)?|co-?op|student (?:intern|placement|trainee))\b",
    re.IGNORECASE,
)

_US_CITIZENSHIP_PATTERN = re.compile(
    r"(?:(?:\bus\b|u\.s\.|united states)\s+citizen(?:ship)?\s+(?:only|required|mandatory|must be)|"
    r"must be an?\s+(?:\bus\b|u\.s\.|united states)\s+citizen|"
    r"requires?(?:\s+active)?\s+(?:\bus\b|u\.s\.|united states)\s+citizen(?:ship)?|"
    r"only\s+(?:\bus\b|u\.s\.|united states)\s+citizens?\s+(?:may|can)\s+apply|"
    r"due to government contracts?,?\s+(?:candidates must be|must be an?)\s+(?:\bus\b|u\.s\.|united states)\s+citizen)",
    re.IGNORECASE,
)

_SECURITY_CLEARANCE_PATTERN = re.compile(
    r"(?:active\s+(?:security\s+)?clearance\s+(?:required|mandatory)|"
    r"must\s+(?:currently\s+)?hold\s+(?:an?\s+)?active\s+(?:security\s+)?clearance|"
    r"top\s+secret(?:\/sci)?\s+clearance\s+required|"
    r"secret\s+clearance\s+required|"
    r"active\s+ts\/sci\s+clearance|"
    r"requires?\s+an?\s+active\s+security\s+clearance)",
    re.IGNORECASE,
)

_PHD_REQUIRED_PATTERN = re.compile(
    r"(?:(?:must have|requires?|requiring|minimum of a|mandatory)[^.\n]*?\b(?:ph\.?d|doctorate)\b|"
    r"\b(?:ph\.?d|doctorate)\b[^.\n]*?\b(?:is required|required for this role|mandatory)\b)",
    re.IGNORECASE,
)

_PHD_PREFERRED_PATTERN = re.compile(
    r"\b(?:ph\.?d|doctorate)\b[^.\n]*?\b(?:preferred|plus|desired|nice to have)\b|"
    r"\b(?:preferred|plus|desired)\b[^.\n]*?\b(?:ph\.?d|doctorate)\b",
    re.IGNORECASE,
)

_MASTERS_REQUIRED_PATTERN = re.compile(
    r"(?:(?:must have|requires?|requiring|minimum of a|mandatory)[^.\n]*?\b(?:master'?s|ms|m\.s\.)\s+degree\b|"
    r"\b(?:master'?s|ms|m\.s\.)\s+degree\s+(?:is\s+)?required\b)",
    re.IGNORECASE,
)

_MASTERS_PREFERRED_PATTERN = re.compile(
    r"\b(?:master'?s|ms|m\.s\.)\s+degree\b[^.\n]*?\b(?:preferred|plus|desired|nice to have)\b|"
    r"\b(?:preferred|plus|desired)\b[^.\n]*?\b(?:master'?s|ms|m\.s\.)\s+degree\b",
    re.IGNORECASE,
)

_YEARS_EXP_PATTERN = re.compile(
    r"(?:(?:minimum|at least|require[ds]?)\s+)?(\d+)(?:\+|-(\d+))?\s*(?:to\s*(\d+)\s*)?years?(?:\s+of)?(?:\s+(?:professional|relevant|industry|software|engineering|programming|coding|work|hands-on|\w+)){0,3}\s+experience",
    re.IGNORECASE,
)


def _extract_sentences(text: str) -> list[str]:
    """Split text into sentences/lines for evidence extraction."""
    raw_lines = re.split(r"[\n\r]+|[.!?]\s+", text)
    return [line.strip() for line in raw_lines if line.strip()]


def _find_evidence(sentences: list[str], pattern: re.Pattern | str) -> str | None:
    """Return the first matching sentence snippet."""
    if isinstance(pattern, str):
        pat = re.compile(re.escape(pattern), re.IGNORECASE)
    else:
        pat = pattern
    for s in sentences:
        if pat.search(s):
            return s[:160]
    return None


def _check_tech_role(title: str, dept: str | None, cat: str | None) -> tuple[bool, bool, str | None]:
    """
    Check if the role is a technical engineering role vs non-tech role.
    Returns: (is_tech, is_explicit_nontech, evidence_span)
    """
    title_lower = title.lower()
    combined = f"{title_lower} {(dept or '').lower()} {(cat or '').lower()}"

    # First check if title has explicit tech role
    for pat in _TECH_TITLE_PATTERNS:
        m = re.search(pat, title_lower)
        if m:
            return True, False, f"Title tech role: {m.group(0)}"

    # Check non-tech role patterns in title
    for pat in _NON_TECH_ROLE_TITLES:
        m = re.search(pat, title_lower)
        if m:
            return False, True, f"Non-tech title: {m.group(0)}"

    # Check if combined has tech role
    for pat in _TECH_TITLE_PATTERNS:
        m = re.search(pat, combined)
        if m:
            return True, False, f"Department/category tech role: {m.group(0)}"

    # Check if combined has non-tech role
    for pat in _NON_TECH_ROLE_TITLES:
        m = re.search(pat, combined)
        if m:
            return False, True, f"Non-tech role: {m.group(0)}"

    return False, False, None


def _is_us_location(location: str, raw_text: str) -> tuple[bool, bool, bool, str | None]:
    """
    Check US vs non-US locations.
    Returns: (has_us, non_us_only, is_generic_remote, evidence)
    """
    from src.filtering import NON_US_SIGNALS, _check_single_location

    loc_str = location or ""
    sub_locations = [s.strip() for s in re.split(r"[;\n|]", loc_str) if s.strip()]
    if not sub_locations:
        sub_locations = [loc_str] if loc_str else []

    us_found = False
    non_us_found = False
    evidence = None

    for sub in sub_locations:
        is_us, reason = _check_single_location(sub)
        if is_us is True:
            us_found = True
            evidence = f"US location: {sub} ({reason})"
            break
        elif is_us is False:
            non_us_found = True
            if not evidence:
                evidence = f"Non-US location: {sub} ({reason})"

    # If sublocations had confirmed US location, then US is available
    if us_found:
        return True, False, False, evidence

    # If sublocations are present and only non-US found:
    if non_us_found and not us_found:
        return False, True, False, evidence

    # Check for generic Remote without US confirmation
    loc_lower = loc_str.lower()
    raw_lower = raw_text.lower() if raw_text else ""
    if "remote" in loc_lower or "remote" in raw_lower:
        # Check if US is specified in raw_text or remote text
        if re.search(r"\b(?:us remote|remote - us|remote \(us\)|remote, united states|remote, us|united states remote|us only)\b", raw_lower) or re.search(r"\b(?:us remote|remote - us|remote \(us\)|remote, united states|remote, us|united states remote|us only)\b", loc_lower):
            return True, False, False, "US Remote in description/location"
        if any(marker in raw_lower for marker in ["united states", "usa", "u.s."]):
            return True, False, False, "US confirmed in text"
        return False, False, True, "Generic Remote with no US scope"

    # Check non-US signals in raw text if location is missing/unclear
    for signal in NON_US_SIGNALS:
        if re.search(r"(?<![a-z])" + re.escape(signal) + r"(?![a-z])", loc_lower):
            return False, True, False, f"Non-US signal in location: {signal}"

    return False, False, False, "Location unconfirmed"


def classify_eligibility(job: Job, filters: dict | None = None) -> EligibilityVerdict:
    """
    Deterministic evaluation of job eligibility for a December 2026 CS graduate
    seeking full-time US software engineering roles starting January 2027 onward.
    """
    title = job.title or ""
    title_lower = title.lower()
    raw = job.raw_text or ""
    raw_lower = raw.lower()
    sentences = _extract_sentences(raw)

    reasons: list[str] = []
    evidence_spans: list[str] = []
    unknowns: list[str] = []

    # 1. Employment Type Classification
    # Priority: Title / structured field > incidental raw text
    is_internship = False
    is_co_op = False
    is_contract = False
    is_part_time = False

    if _INTERN_TITLE_PATTERN.search(title_lower) or job.role_type == "internship":
        if re.search(r"\bco-?op\b", title_lower):
            is_co_op = True
            employment_type = "co_op"
            reasons.append(REASON_CO_OP_ROLE)
        else:
            is_internship = True
            employment_type = "internship"
            reasons.append(REASON_INTERNSHIP_ROLE)
        evidence_spans.append(f"Title intern/co-op: {title}")
    elif re.search(r"\b(?:contract(?:or)?|temp(?:orary)?)\b", title_lower):
        is_contract = True
        employment_type = "contract"
        reasons.append(REASON_CONTRACT_ROLE)
        evidence_spans.append(f"Contract role: {title}")
    elif re.search(r"\bpart[\s-]?time\b", title_lower):
        is_part_time = True
        employment_type = "part_time"
        reasons.append(REASON_PART_TIME_ROLE)
        evidence_spans.append(f"Part-time role: {title}")
    else:
        # Check description context: only classify as internship if the position itself is an internship
        # Avoid false positives like "mentors interns" or "previous internship experience preferred"
        intern_desc_match = re.search(
            r"\b(?:this\s+(?:summer\s+)?internship|as\s+an?\s+intern|during\s+your\s+internship|internship\s+program|intern\s+responsibilities)\b",
            raw_lower,
        )
        if intern_desc_match:
            is_internship = True
            employment_type = "internship"
            reasons.append(REASON_INTERNSHIP_ROLE)
            evidence_spans.append(f"Internship description: {intern_desc_match.group(0)}")
        else:
            # Check for explicit full-time mentions
            if re.search(r"\bfull[\s-]?time\b", raw_lower) or re.search(r"\bpermanent\b", raw_lower):
                employment_type = "full_time"
            else:
                # Default to full-time if title/text indicates early career engineering role
                is_early_ind = (
                    _ENTRY_TITLE_PATTERN.search(title_lower)
                    or _NEW_GRAD_PATTERN.search(title_lower)
                    or bool(re.search(r"\b0[-–]2\s*years?\b", raw_lower))
                )
                employment_type = "full_time" if is_early_ind else "unknown"
                if employment_type == "unknown":
                    unknowns.append("employment_type")

    # 2. Tech Role Classification
    is_tech, is_explicit_nontech, tech_evidence = _check_tech_role(title, job.department, job.category)
    if is_explicit_nontech and not is_tech:
        reasons.append(REASON_NON_TECH_ROLE)
        if tech_evidence:
            evidence_spans.append(tech_evidence)
    elif is_tech:
        reasons.append(REASON_TECH_ROLE_CONFIRMED)
        if tech_evidence:
            evidence_spans.append(tech_evidence)
    else:
        # Unknown tech role
        reasons.append(REASON_NON_TECH_ROLE)
        evidence_spans.append(f"Non-engineering title: {title}")

    # 3. Location Classification
    has_us, non_us_only, is_generic_remote, loc_evidence = _is_us_location(job.location, raw)
    if non_us_only:
        reasons.append(REASON_NON_US_ONLY)
        if loc_evidence:
            evidence_spans.append(loc_evidence)
    elif is_generic_remote:
        reasons.append(REASON_LOCATION_UNKNOWN)
        if loc_evidence:
            evidence_spans.append(loc_evidence)
        unknowns.append("location")
    elif has_us:
        reasons.append(REASON_US_LOCATION_CONFIRMED)
        if loc_evidence:
            evidence_spans.append(loc_evidence)
    else:
        reasons.append(REASON_LOCATION_UNKNOWN)
        unknowns.append("location")

    # 4. Citizenship / Security Clearance Check
    cit_match = _US_CITIZENSHIP_PATTERN.search(raw_lower)
    if cit_match:
        ev = _find_evidence(sentences, _US_CITIZENSHIP_PATTERN) or cit_match.group(0)
        reasons.append(REASON_US_CITIZEN_REQUIRED)
        evidence_spans.append(f"US citizenship required: {ev}")

    clearance_match = _SECURITY_CLEARANCE_PATTERN.search(raw_lower)
    if clearance_match:
        ev = _find_evidence(sentences, _SECURITY_CLEARANCE_PATTERN) or clearance_match.group(0)
        reasons.append(REASON_SECURITY_CLEARANCE_REQUIRED)
        evidence_spans.append(f"Security clearance required: {ev}")

    # 5. Degree Requirements Check
    phd_req_match = _PHD_REQUIRED_PATTERN.search(raw_lower)
    if phd_req_match:
        # Verify it's not actually preferred
        ev = _find_evidence(sentences, _PHD_REQUIRED_PATTERN) or phd_req_match.group(0)
        if not _PHD_PREFERRED_PATTERN.search(ev):
            reasons.append(REASON_PHD_REQUIRED)
            reasons.append(REASON_DEGREE_MISMATCH)
            evidence_spans.append(f"PhD required: {ev}")

    masters_req_match = _MASTERS_REQUIRED_PATTERN.search(raw_lower)
    if masters_req_match:
        ev = _find_evidence(sentences, _MASTERS_REQUIRED_PATTERN) or masters_req_match.group(0)
        if not _MASTERS_PREFERRED_PATTERN.search(ev):
            reasons.append(REASON_MASTERS_REQUIRED)
            reasons.append(REASON_DEGREE_MISMATCH)
            evidence_spans.append(f"Master's required: {ev}")

    # 6. Career Level & Experience Check
    career_level = "unknown"
    is_senior = False
    is_ambiguous_mid = False
    is_new_grad = False
    is_entry = False

    # Check title first
    if _SENIOR_TITLE_PATTERN.search(title_lower):
        is_senior = True
        career_level = "senior"
        reasons.append(REASON_SENIOR_LEVEL)
        evidence_spans.append(f"Senior title: {title}")
    elif _MID_AMBIGUOUS_TITLE_PATTERN.search(title_lower):
        is_ambiguous_mid = True
        career_level = "mid"
        reasons.append(REASON_AMBIGUOUS_LEVEL)
        evidence_spans.append(f"Mid/Ambiguous level title: {title}")
    elif _NEW_GRAD_TITLE_PATTERN.search(title_lower) or _NEW_GRAD_BODY_PATTERN.search(raw_lower):
        is_new_grad = True
        career_level = "new_grad"
        reasons.append(REASON_CONFIRMED_NEW_GRAD)
        evidence_spans.append(f"New grad role: {title}")
    elif _ENTRY_TITLE_PATTERN.search(title_lower):
        is_entry = True
        career_level = "entry_level"
        reasons.append(REASON_ENTRY_LEVEL_TITLE)
        evidence_spans.append(f"Entry level title: {title}")

    # Check years of experience in requirements
    exp_matches = _YEARS_EXP_PATTERN.findall(raw_lower)
    max_years_req = None
    min_years_req = None
    if exp_matches:
        for match in exp_matches:
            # match is (min_str, range_end_str, range_to_str)
            y_min = int(match[0]) if match[0] else 0
            if min_years_req is None or y_min < min_years_req:
                min_years_req = y_min
            if max_years_req is None or y_min > max_years_req:
                max_years_req = y_min

        # If min years >= 4, it's senior / exceeds range
        if min_years_req is not None and min_years_req >= 4:
            is_senior = True
            career_level = "senior"
            reasons.append(REASON_EXPERIENCE_EXCEEDS_RANGE)
            ev = _find_evidence(sentences, _YEARS_EXP_PATTERN) or f"{min_years_req}+ years required"
            evidence_spans.append(f"Experience required >= 4 yrs: {ev}")
        elif min_years_req == 3:
            reasons.append(REASON_EXPERIENCE_EXCEEDS_RANGE)
            ev = _find_evidence(sentences, _YEARS_EXP_PATTERN) or "3 years required"
            evidence_spans.append(f"3 years experience: {ev}")
        elif min_years_req is not None and min_years_req <= 2:
            reasons.append(REASON_ZERO_TO_TWO_YEARS)
            ev = _find_evidence(sentences, _YEARS_EXP_PATTERN) or f"{min_years_req} years required"
            evidence_spans.append(f"0-2 years experience: {ev}")

    # 7. Graduation Window / 2027 Cohort Check
    # Check if 2027 is mentioned
    cohort_2027_match = re.search(r"\b(?:2027\s+(?:cohort|graduate|grads?)|class\s+of\s+2027)\b", raw_lower) or re.search(r"\b2027\b", title_lower)
    if cohort_2027_match:
        # Check if December 2026 / Dec 2026 is mentioned in eligibility window
        dec_2026_match = re.search(
            r"\b(?:dec(?:ember)?\s+2026|winter\s+2026|fall\s+2026|2026\s*[-–]\s*2027|between\s+(?:december|dec|winter)\s+2026)\b",
            raw_lower,
        )
        if dec_2026_match:
            is_new_grad = True
            career_level = "new_grad"
            reasons.append(REASON_CONFIRMED_NEW_GRAD)
            evidence_spans.append("2027 cohort explicitly allows December 2026 graduates")
        else:
            # 2027 cohort without explicit date window -> needs_review
            reasons.append(REASON_COHORT_2027_UNSPECIFIED)
            evidence_spans.append(f"2027 cohort without explicit graduation window: {cohort_2027_match.group(0)}")

    # Check for graduation outside window (e.g. 2028+ or 2025 or earlier)
    grad_outside_match = re.search(
        r"\b(?:graduat(?:ing|ed|ion)\s+(?:in|by)\s+(?:2024|2025|spring\s+2026|summer\s+2026|2028|2029))\b",
        raw_lower,
    )
    if grad_outside_match and not re.search(r"\b(?:dec(?:ember)?\s+2026|winter\s+2026)\b", raw_lower):
        reasons.append(REASON_GRADUATION_OUTSIDE_WINDOW)
        evidence_spans.append(f"Graduation window mismatch: {grad_outside_match.group(0)}")

    # 8. Check for unspecified career level on bare general SWE
    if career_level == "unknown" and is_tech:
        if not exp_matches and not is_new_grad and not is_entry:
            reasons.append(REASON_EXPERIENCE_UNSPECIFIED)
            reasons.append(REASON_FULL_TIME_UNSPECIFIED)
            unknowns.append("career_level")
            unknowns.append("years_experience")

    # -----------------------------------------------------------------------
    # Decision Matrix: Determine Final Eligibility Status
    # -----------------------------------------------------------------------

    # Disqualification / Exclude criteria (100% hard gates)
    exclude_triggers = [
        REASON_INTERNSHIP_ROLE,
        REASON_CO_OP_ROLE,
        REASON_CONTRACT_ROLE,
        REASON_PART_TIME_ROLE,
        REASON_SENIOR_LEVEL,
        REASON_NON_TECH_ROLE,
        REASON_PHD_REQUIRED,
        REASON_MASTERS_REQUIRED,
        REASON_US_CITIZEN_REQUIRED,
        REASON_SECURITY_CLEARANCE_REQUIRED,
        REASON_NON_US_ONLY,
        REASON_GRADUATION_OUTSIDE_WINDOW,
    ]
    # Check if experience exceeds range >= 4 years
    if min_years_req is not None and min_years_req >= 4:
        exclude_triggers.append(REASON_EXPERIENCE_EXCEEDS_RANGE)

    is_excluded = any(t in reasons for t in exclude_triggers)

    if is_excluded:
        status = "excluded"
    else:
        # Check review triggers
        review_triggers = [
            REASON_COHORT_2027_UNSPECIFIED,
            REASON_AMBIGUOUS_LEVEL,
            REASON_EXPERIENCE_UNSPECIFIED,
            REASON_LOCATION_UNKNOWN,
            REASON_WORK_AUTH_UNKNOWN,
        ]
        # 3 years experience is a stretch review
        if min_years_req == 3:
            review_triggers.append(REASON_EXPERIENCE_EXCEEDS_RANGE)

        is_review = any(t in reasons for t in review_triggers)

        # Clear positive evidence for eligibility:
        # Must be tech role AND US location confirmed AND (new grad OR entry level OR 0-2 years)
        has_positive_early_career = (
            REASON_CONFIRMED_NEW_GRAD in reasons
            or REASON_ENTRY_LEVEL_TITLE in reasons
            or REASON_ZERO_TO_TWO_YEARS in reasons
        )
        has_positive_tech = REASON_TECH_ROLE_CONFIRMED in reasons
        has_positive_loc = REASON_US_LOCATION_CONFIRMED in reasons

        if has_positive_tech and has_positive_loc and has_positive_early_career and not is_review:
            status = "eligible"
        else:
            status = "needs_review"

    # Deduplicate reasons while preserving order
    unique_reasons = tuple(dict.fromkeys(reasons))
    unique_evidence = tuple(dict.fromkeys(evidence_spans))
    unique_unknowns = tuple(dict.fromkeys(unknowns))

    return EligibilityVerdict(
        job_id=job.id,
        policy_version=POLICY_VERSION,
        status=status,
        employment_type=employment_type,
        career_level=career_level,
        reasons=unique_reasons,
        evidence_spans=unique_evidence,
        unknowns=unique_unknowns,
    )
