"""Conservative experience requirements for a December 2026 bachelor's graduate.

This parser does NOT infer a candidate's skills. It only identifies whether
the posting has a supported bachelor's-degree experience *pathway*.
Where an alternative pathway or minimum cannot be mapped reliably, abstain.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

_DEGREE = re.compile(
    r"\b(?P<bachelor>bachelor(?:'?s|s)?|b\.?s\.?|undergraduate)"
    r"|\b(?P<master>master(?:'?s|s)?|m\.?s\.?)"
    r"|\b(?P<phd>ph\.?d\.?|doctorate)\b",
    re.IGNORECASE,
)
_YEAR = re.compile(
    r"(?<!\w)(?P<low>\d+(?:\.\d+)?)"
    r"(?:\s*(?:-|–|—|to)\s*\d+(?:\.\d+)?)?\s*\+?\s*"
    r"(?P<unit>years?|yrs?|months?|mos?)\b",
    re.IGNORECASE,
)
_MIN_HEADER = re.compile(
    r"\b(?:minimum|basic|required)\s+(?:qualifications?|requirements?)\s*:?\s*",
    re.IGNORECASE,
)
_PREFERRED_HEADER = re.compile(
    r"\b(?:preferred|desired)\s+(?:qualifications?|requirements?)\s*:?\s*",
    re.IGNORECASE,
)
_GENERAL_AFTER = re.compile(
    r"\bexperience\s+(?:with|in|using)\s+(?!"
    r"(?:the\s+)?(?:software\s+(?:engineering|development)|engineering|"
    r"industry|related\s+field|professional|product\s+development)\b)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class ExperienceAssessment:
    minimum_years: float | None
    ambiguous: bool
    evidence: str | None
    has_bachelors_alternative: bool = False


def _required_section(text: str) -> str:
    normalized = (text or "").replace("\u2019", "'").replace("\xa0", " ")
    minimum = _MIN_HEADER.search(normalized)
    if minimum:
        normalized = normalized[minimum.end():]
    preferred = _PREFERRED_HEADER.search(normalized)
    if preferred:
        normalized = normalized[:preferred.start()]
    return normalized


def _mentions(span: str, *, degree_context: bool) -> list[tuple[float, str, bool]]:
    """(lower-bound years, evidence snippet, skill-specific) in a required span."""
    found: list[tuple[float, str, bool]] = []
    for match in _YEAR.finditer(span):
        after = span[match.end(): match.end() + 100]
        before = span[max(0, match.start() - 65): match.start()]
        context = f"{before} {after}".lower()
        # Ignore ages, company-history numbers and other unrelated quantities.
        if not degree_context and not any(
            word in context for word in ("experience", "industry", "professional", "hands-on")
        ):
            continue
        quantity = float(match.group("low"))
        if quantity > 40:  # likely a malformed field rather than career tenure
            continue
        if match.group("unit").lower().startswith(("month", "mo")):
            quantity /= 12
        evidence = span[max(0, match.start() - 90): match.end() + 95].strip()
        skill_specific = bool(_GENERAL_AFTER.search(after[:85]))
        # "programming experience in Python" is general programming tenure,
        # unlike "experience using Kubernetes" as an individual tool.
        if re.search(
            r"\b(?:programming|software\s+(?:engineering|development)|"
            r"professional|industry|engineering)\s+experience\s+(?:in|with|using)\b",
            after[:85],
            re.IGNORECASE,
        ):
            skill_specific = False
        found.append((quantity, evidence[:240], skill_specific))
    return found


def assess_experience_requirements(raw_text: str) -> ExperienceAssessment:
    """Return the bachelor's pathway minimum or abstain when it cannot be known.

    Never substitute a master's/PhD minimum, or a smaller individual skill
    requirement, for a bachelor's overall minimum. Prefer a minimum-
    qualifications section to unrelated preferred/marketing content.
    """
    required = _required_section(raw_text)
    degrees = list(_DEGREE.finditer(required))
    bachelors = [(i, m) for i, m in enumerate(degrees) if m.group("bachelor")]
    other_degrees = [m for m in degrees if m.group("master") or m.group("phd")]
    has_alternative = False
    if bachelors and other_degrees:
        for _, b in bachelors:
            for other in other_degrees:
                lo, hi = sorted((b.end(), other.start()))
                if re.search(r"\bor\b|/", required[lo:hi]):
                    has_alternative = True
                    break
            if has_alternative:
                break

    if bachelors:
        # A degree mentioned without any numerical experience condition is
        # not an ambiguous experience pathway by itself.
        if not _mentions(required, degree_context=True):
            return ExperienceAssessment(None, False, None, has_alternative)
        # Each bachelor's clause ends at the next degree alternative.
        candidates: list[tuple[float, str]] = []
        incomplete = False
        for index, bachelor in bachelors:
            next_degree = degrees[index + 1].start() if index + 1 < len(degrees) else len(required)
            fragment = required[bachelor.end():next_degree]
            numbers = _mentions(fragment, degree_context=True)
            if not numbers:
                incomplete = True
            else:
                # Multiple requirements in the same pathway are conjunctive.
                strongest = max(numbers, key=lambda value: value[0])
                candidates.append((strongest[0], strongest[1]))
        if incomplete or not candidates or len({v for v, _ in candidates}) > 1:
            return ExperienceAssessment(
                None, True, "Bachelor's experience requirement could not be uniquely established",
                has_alternative,
            )
        years, evidence = candidates[0]
        return ExperienceAssessment(years, False, evidence, has_alternative)

    # If all stated pathways are graduate degrees, never treat their smaller
    # tenure requirement as qualifying this bachelor's-degree candidate.
    if other_degrees:
        return ExperienceAssessment(
            None, True, "Only graduate-degree experience pathways were identifiable",
        )

    numbers = _mentions(required, degree_context=False)
    if not numbers:
        return ExperienceAssessment(None, False, None)
    general = [n for n in numbers if not n[2]]
    specific = [n for n in numbers if n[2]]
    if not general:
        return ExperienceAssessment(
            None, True, "Only technology-specific experience requirements were found",
        )
    strongest = max(general, key=lambda value: value[0])
    # An additional high-tenure specific skill must not make a role appear
    # unconditionally suitable just because overall experience is low.
    if any(n[0] > strongest[0] for n in specific):
        return ExperienceAssessment(
            strongest[0], True, "Conflicting skill-specific experience requirement",
        )
    return ExperienceAssessment(strongest[0], False, strongest[1])
