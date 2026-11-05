"""
Tests for Phase 1 deterministic eligibility classifier (src/eligibility.py)
and its integration into the filter pipeline (src/filtering.py).
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.models import Job
from src.eligibility import (
    POLICY_VERSION,
    classify_eligibility,
    EligibilityVerdict,
    REASON_INTERNSHIP_ROLE,
    REASON_CO_OP_ROLE,
    REASON_SENIOR_LEVEL,
    REASON_NON_TECH_ROLE,
    REASON_PHD_REQUIRED,
    REASON_MASTERS_REQUIRED,
    REASON_US_CITIZEN_REQUIRED,
    REASON_SECURITY_CLEARANCE_REQUIRED,
    REASON_NON_US_ONLY,
    REASON_CONFIRMED_NEW_GRAD,
    REASON_ENTRY_LEVEL_TITLE,
    REASON_ZERO_TO_TWO_YEARS,
    REASON_COHORT_2027_UNSPECIFIED,
    REASON_AMBIGUOUS_LEVEL,
    REASON_EXPERIENCE_UNSPECIFIED,
    REASON_LOCATION_UNKNOWN,
)
from src.filtering import apply_filter_pipeline, filter_location

FIXTURES_DIR = Path(__file__).parent / "fixtures"
_NOW = datetime(2026, 11, 4, 12, 0, 0, tzinfo=timezone.utc)


def _load_fixtures() -> list[dict]:
    with open(FIXTURES_DIR / "eligibility_matrix.json", "r") as f:
        return json.load(f)


def _job_from_fixture(item: dict) -> Job:
    return Job(
        id=item["id"],
        company=item["company"],
        title=item["title"],
        location=item["location"],
        department=item.get("department"),
        category=item.get("category"),
        url=item["url"],
        source_platform=item["source_platform"],
        posted_at=None,
        detected_at=_NOW,
        raw_text=item["raw_text"],
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )


class TestEligibilityMatrix:
    """Table-driven evaluation of all 30 critical fixture scenarios from EVALS.md."""

    @pytest.mark.parametrize("fixture", _load_fixtures(), ids=lambda f: f["id"])
    def test_fixture_verdict_status(self, fixture: dict):
        job = _job_from_fixture(fixture)
        verdict = classify_eligibility(job)

        assert verdict.policy_version == POLICY_VERSION
        assert verdict.status == fixture["expected_status"], (
            f"Expected {fixture['expected_status']} for {fixture['id']}, got {verdict.status}. "
            f"Reasons: {verdict.reasons}, Evidence: {verdict.evidence_spans}"
        )

        for expected_reason in fixture.get("expected_reasons", []):
            assert expected_reason in verdict.reasons, (
                f"Missing expected reason {expected_reason} in {verdict.reasons} for {fixture['id']}"
            )

        if "expected_career_level" in fixture:
            assert verdict.career_level == fixture["expected_career_level"]

        if "expected_employment_type" in fixture:
            assert verdict.employment_type == fixture["expected_employment_type"]


class TestSpecificAdversarialCases:
    """Focused unit tests for specific semantic nuances and edge cases."""

    def test_internship_in_team_description_is_not_internship_role(self):
        job = Job(
            id="test-team-intern-mention",
            company="Micron",
            title="Software Engineer I",
            location="San Jose, CA",
            department="Engineering",
            category="Software",
            url="https://example.com/job/1",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer I. We mentor interns each summer and value collaborative leadership. 0-2 years experience required. San Jose, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_INTERNSHIP_ROLE not in verdict.reasons
        assert REASON_ENTRY_LEVEL_TITLE in verdict.reasons

    def test_previous_internship_experience_preferred_is_not_intern_role(self):
        job = Job(
            id="test-prior-internship",
            company="CrowdStrike",
            title="Junior Software Engineer",
            location="Austin, TX",
            department="Engineering",
            category="Software",
            url="https://example.com/job/2",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Junior Software Engineer. Prior internship experience preferred. 0-1 years industry experience. Austin, TX.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_INTERNSHIP_ROLE not in verdict.reasons

    def test_phd_preferred_passes(self):
        job = Job(
            id="test-phd-preferred",
            company="Salesforce",
            title="Applied AI Engineer, New Grad",
            location="San Francisco, CA",
            department="AI",
            category="Engineering",
            url="https://example.com/job/3",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Applied AI Engineer, New Grad. BS in Computer Science required. PhD preferred. Graduating December 2026. San Francisco, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_PHD_REQUIRED not in verdict.reasons

    def test_phd_required_fails(self):
        job = Job(
            id="test-phd-required",
            company="Microsoft Research",
            title="Research Scientist",
            location="Redmond, WA",
            department="Research",
            category="Research",
            url="https://example.com/job/4",
            source_platform="microsoft_research",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Research Scientist. Minimum requirement: PhD in Computer Science or related field required for this position. Redmond, WA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "excluded"
        assert REASON_PHD_REQUIRED in verdict.reasons

    def test_security_engineer_does_not_trigger_citizenship_exclude(self):
        job = Job(
            id="test-security-engineer",
            company="Plaid",
            title="Security Engineer, New Grad",
            location="San Francisco, CA",
            department="Security",
            category="Engineering",
            url="https://example.com/job/5",
            source_platform="lever",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Security Engineer, New Grad. Experience with cloud security protocols and web vulnerability mitigation. Graduating Dec 2026. San Francisco, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_US_CITIZEN_REQUIRED not in verdict.reasons
        assert REASON_SECURITY_CLEARANCE_REQUIRED not in verdict.reasons

    def test_citizenship_only_excludes(self):
        job = Job(
            id="test-cit-only",
            company="Oracle",
            title="Systems Engineer, New Grad",
            location="Reston, VA",
            department="Government",
            category="Engineering",
            url="https://example.com/job/6",
            source_platform="oracle_careers",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Systems Engineer, New Grad. US citizenship required due to federal compliance. Reston, VA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "excluded"
        assert REASON_US_CITIZEN_REQUIRED in verdict.reasons

    def test_mixed_san_jose_and_toronto_location_filter(self):
        job = Job(
            id="test-mixed-loc",
            company="Western Digital",
            title="Software Engineer, New Grad",
            location="San Jose, CA; Toronto, Canada",
            department="Engineering",
            category="Storage",
            url="https://example.com/job/7",
            source_platform="smartrecruiters",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer, New Grad. Positions available in San Jose, CA or Toronto, Canada. December 2026 graduates welcome.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        loc_res = filter_location(job, filters={})
        assert loc_res.passes
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_NON_US_ONLY not in verdict.reasons

    def test_parenthesized_level_code_e3_excludes_senior(self):
        job = Job(
            id="test-level-e3",
            company="Applied Materials",
            title="Software Engineer (E3)",
            location="Santa Clara, CA",
            department="Engineering",
            category="Software",
            url="https://example.com/job/e3",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer (E3). 0-2 years experience. Santa Clara, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "excluded"
        assert REASON_SENIOR_LEVEL in verdict.reasons

    def test_parenthesized_level_code_l4_excludes_senior(self):
        job = Job(
            id="test-level-l4",
            company="Google",
            title="Software Engineer (L4)",
            location="Mountain View, CA",
            department="Engineering",
            category="Software",
            url="https://example.com/job/l4",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer (L4). Mountain View, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "excluded"
        assert REASON_SENIOR_LEVEL in verdict.reasons

    def test_lowercase_state_code_ca_is_eligible(self):
        job = Job(
            id="test-swe1-ca",
            company="Apple",
            title="Software Engineer I",
            location="Cupertino, ca",
            department="Engineering",
            category="Software",
            url="https://example.com/job/ca1",
            source_platform="apple_jobs",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer I. 0-2 years experience. Full-time.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "eligible"
        assert REASON_NON_US_ONLY not in verdict.reasons

    def test_tbilisi_georgia_is_excluded(self):
        job = Job(
            id="test-swe1-tbilisi",
            company="GlobalTech",
            title="Software Engineer I",
            location="Tbilisi, Georgia",
            department="Engineering",
            category="Software",
            url="https://example.com/job/ge1",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer I. 0-2 years experience. Full-time.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        assert verdict.status == "excluded"
        assert REASON_NON_US_ONLY in verdict.reasons

    def test_unresolved_georgia_alone_is_needs_review(self):
        job = Job(
            id="test-swe1-georgia",
            company="GenericCorp",
            title="Software Engineer I",
            location="Georgia",
            department="Engineering",
            category="Software",
            url="https://example.com/job/ge2",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer I. 0-2 years experience. Full-time.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        verdict = classify_eligibility(job)
        # Without US context, unresolved Georgia cannot be confirmed US and must not be marked eligible
        assert verdict.status == "needs_review"


class TestPipelineNewGradMode:
    """Test full filter pipeline in new_grad_full_time mode vs legacy mode."""

    def test_pipeline_new_grad_mode_includes_eligible(self):
        filters = {"mode": "new_grad_full_time"}
        job = Job(
            id="test-p1-eligible",
            company="Salesforce",
            title="Software Engineer, New Grad",
            location="San Francisco, CA",
            department="Engineering",
            category="Core",
            url="https://example.com/job/ng1",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer, New Grad. December 2026 graduation. San Francisco, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        result_job, reasons = apply_filter_pipeline(job, filters, source_config={})
        assert result_job is not None
        assert result_job.role_type == "new-grad"
        assert result_job.verdict is not None
        assert result_job.verdict.status == "eligible"

    def test_pipeline_new_grad_mode_drops_intern(self):
        filters = {"mode": "new_grad_full_time"}
        job = Job(
            id="test-p1-intern",
            company="Amazon",
            title="Software Development Engineer Intern",
            location="Seattle, WA",
            department="AWS",
            category="Software",
            url="https://example.com/job/intern1",
            source_platform="amazon_jobs",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Development Engineer Intern - Summer 2027. Seattle, WA.",
            role_type="internship",
            priority="normal",
            matched_keywords=(),
        )
        result_job, reasons = apply_filter_pipeline(job, filters, source_config={})
        assert result_job is None
        assert any("INTERNSHIP_ROLE" in r for r in reasons)

    def test_pipeline_new_grad_mode_silences_needs_review(self):
        filters = {"mode": "new_grad_full_time"}
        job = Job(
            id="test-p1-review",
            company="Intel",
            title="Software Engineer",
            location="Santa Clara, CA",
            department="Software",
            category="Engineering",
            url="https://example.com/job/swe-unspecified",
            source_platform="workday",
            posted_at=None,
            detected_at=_NOW,
            raw_text="Software Engineer. Core engineering team. Santa Clara, CA.",
            role_type="unknown",
            priority="normal",
            matched_keywords=(),
        )
        result_job, reasons = apply_filter_pipeline(job, filters, source_config={})
        # Needs review must NOT be returned for individual alerting
        assert result_job is None
        assert any("needs_review" in r for r in reasons)
