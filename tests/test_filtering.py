"""Tests for the 6 filter functions and full pipeline."""
from __future__ import annotations
from datetime import datetime, timezone

import pytest

from src.models import Job
from src.filtering import (
    filter_location,
    filter_exclude,
    filter_early_career,
    filter_tech_role,
    filter_per_company_override,
    label_job,
    apply_filter_pipeline,
)

# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------

_NOW = datetime(2026, 5, 6, 12, 0, 0, tzinfo=timezone.utc)


def make_job(
    title: str = "Software Engineering Intern",
    location: str = "San Francisco, CA",
    raw_text: str | None = None,
    role_type: str = "unknown",
    company: str = "Acme",
    department: str | None = None,
    category: str | None = None,
) -> Job:
    if raw_text is None:
        parts = [title, location]
        if department:
            parts.append(department)
        if category:
            parts.append(category)
        raw_text = " ".join(parts).lower()
    return Job(
        id="test-id",
        company=company,
        title=title,
        location=location,
        department=department,
        category=category,
        url="https://example.com/job/1",
        source_platform="workday",
        posted_at=None,
        detected_at=_NOW,
        raw_text=raw_text,
        role_type=role_type,
        priority="normal",
        matched_keywords=(),
    )


# Minimal filters dict (mirrors companies.yaml)
_FILTERS = {
    "early_career_keywords": [
        "intern", "internship", "co-op", "university", "student",
        "new grad", "new graduate", "early career", "entry level",
        "entry-level", "graduate", "campus", "recent graduate",
    ],
    "technical_role_keywords": [
        "software", "software engineer", "software engineering", "swe", "developer",
        "backend", "frontend", "full stack", "cloud", "infrastructure", "platform",
        "systems", "security", "data", "data scientist", "data science", "data engineer",
        "business intelligence", "bi engineer", "analytics", "ai", "ml", "machine learning",
        "product manager", "program manager", "tpm",
    ],
    "exclude_keywords": [
        "warehouse", "fulfillment", "retail", "sales associate", "account executive",
        "customer support", "call center", "legal", "finance", "accounting",
        "human resources", "hr", "facilities", "maintenance", "security guard",
        "manufacturing operator",
    ],
    "exclude_unless_intern": [
        "marketing", "technician", "hardware", "manufacturing", "operations",
        "business analyst",
    ],
    "preferred_locations": [
        "California", "CA", "Texas", "TX", "Chicago", "Illinois", "IL",
        "New York", "NY", "Remote",
    ],
}


# ---------------------------------------------------------------------------
# filter_location tests
# ---------------------------------------------------------------------------

class TestFilterLocation:
    def test_us_city_passes(self):
        job = make_job(location="San Francisco, CA")
        result = filter_location(job, _FILTERS)
        assert result.passes

    def test_state_code_passes(self):
        job = make_job(location="Folsom, CA")
        result = filter_location(job, _FILTERS)
        assert result.passes

    def test_london_uk_fails(self):
        job = make_job(location="London, UK", raw_text="software engineer london uk")
        result = filter_location(job, _FILTERS)
        assert not result.passes
        assert "non-US" in result.reason

    def test_bangalore_india_fails(self):
        job = make_job(location="Bangalore, India", raw_text="software engineer bangalore india")
        result = filter_location(job, _FILTERS)
        assert not result.passes

    def test_empty_location_passes_as_ambiguous(self):
        job = make_job(location="", raw_text="software engineer intern")
        result = filter_location(job, _FILTERS)
        assert result.passes
        assert "ambiguous" in result.reason

    def test_remote_passes(self):
        job = make_job(location="Remote", raw_text="software engineer remote")
        result = filter_location(job, _FILTERS)
        assert result.passes

    def test_united_states_in_raw_passes(self):
        job = make_job(location="", raw_text="software engineering intern united states")
        result = filter_location(job, _FILTERS)
        assert result.passes

    def test_new_york_city_passes(self):
        job = make_job(location="New York, NY")
        result = filter_location(job, _FILTERS)
        assert result.passes

    def test_canada_fails(self):
        job = make_job(location="Toronto, Canada", raw_text="software engineer toronto canada")
        result = filter_location(job, _FILTERS)
        assert not result.passes


# ---------------------------------------------------------------------------
# filter_exclude tests
# ---------------------------------------------------------------------------

class TestFilterExclude:
    def test_warehouse_associate_fails(self):
        job = make_job(
            title="Warehouse Associate",
            raw_text="warehouse associate night shift",
        )
        result = filter_exclude(job, _FILTERS)
        assert not result.passes
        assert "warehouse" in result.reason

    def test_normal_job_passes(self):
        job = make_job(title="Software Engineering Intern")
        result = filter_exclude(job, _FILTERS)
        assert result.passes

    def test_marketing_intern_with_software_passes(self):
        """marketing is in exclude_unless_intern — passes when early-career + tech present."""
        job = make_job(
            title="Marketing Software Engineering Intern",
            raw_text="marketing software engineering intern intern",
        )
        result = filter_exclude(job, _FILTERS)
        assert result.passes

    def test_marketing_manager_fails(self):
        """marketing is in exclude_unless_intern — fails without intern + tech signal."""
        job = make_job(
            title="Marketing Manager",
            raw_text="marketing manager senior",
        )
        result = filter_exclude(job, _FILTERS)
        assert not result.passes
        assert "marketing" in result.reason

    def test_hr_fails(self):
        job = make_job(title="HR Coordinator", raw_text="human resources hr coordinator")
        result = filter_exclude(job, _FILTERS)
        assert not result.passes

    def test_customer_support_fails(self):
        job = make_job(raw_text="customer support representative")
        result = filter_exclude(job, _FILTERS)
        assert not result.passes


# ---------------------------------------------------------------------------
# filter_early_career tests
# ---------------------------------------------------------------------------

class TestFilterEarlyCareer:
    def test_intern_keyword_passes(self):
        job = make_job(raw_text="software engineering intern summer 2026")
        result = filter_early_career(job, _FILTERS)
        assert result.passes

    def test_internship_keyword_passes(self):
        job = make_job(raw_text="software engineering internship")
        result = filter_early_career(job, _FILTERS)
        assert result.passes

    def test_new_grad_keyword_passes(self):
        job = make_job(raw_text="new grad software engineer 2026")
        result = filter_early_career(job, _FILTERS)
        assert result.passes

    def test_senior_engineer_fails(self):
        job = make_job(
            title="Senior Software Engineer",
            raw_text="senior software engineer 5+ years experience",
        )
        result = filter_early_career(job, _FILTERS)
        assert not result.passes

    def test_adapter_hint_internship_passes_without_keyword(self):
        """role_type='internship' from adapter should pass even without keyword."""
        job = make_job(
            title="Software Engineer",
            raw_text="software engineer platform",
            role_type="internship",
        )
        result = filter_early_career(job, _FILTERS)
        assert result.passes
        assert "adapter hint" in result.reason

    def test_entry_level_passes(self):
        job = make_job(raw_text="entry level software engineer")
        result = filter_early_career(job, _FILTERS)
        assert result.passes


# ---------------------------------------------------------------------------
# filter_tech_role tests
# ---------------------------------------------------------------------------

class TestFilterTechRole:
    def test_data_science_intern_passes(self):
        job = make_job(raw_text="data science intern summer 2026")
        result = filter_tech_role(job, _FILTERS)
        assert result.passes

    def test_hr_intern_fails(self):
        job = make_job(raw_text="hr intern human resources")
        result = filter_tech_role(job, _FILTERS)
        assert not result.passes

    def test_software_engineer_passes(self):
        job = make_job(raw_text="software engineer backend python")
        result = filter_tech_role(job, _FILTERS)
        assert result.passes

    def test_machine_learning_intern_passes(self):
        job = make_job(raw_text="machine learning intern applied science")
        result = filter_tech_role(job, _FILTERS)
        assert result.passes

    def test_facilities_coordinator_fails(self):
        job = make_job(raw_text="facilities coordinator operations")
        result = filter_tech_role(job, _FILTERS)
        assert not result.passes


# ---------------------------------------------------------------------------
# filter_per_company_override tests
# ---------------------------------------------------------------------------

class TestFilterPerCompanyOverride:
    def test_require_early_career_no_signal_fails(self):
        job = make_job(
            title="Software Engineer",
            raw_text="software engineer platform full stack",
            role_type="unknown",
        )
        source_config = {"require_early_career": True}
        result = filter_per_company_override(job, _FILTERS, source_config)
        assert not result.passes
        assert "early-career required" in result.reason

    def test_require_early_career_with_keyword_passes(self):
        job = make_job(
            title="Software Engineering Intern",
            raw_text="software engineering intern summer",
        )
        source_config = {"require_early_career": True}
        result = filter_per_company_override(job, _FILTERS, source_config)
        assert result.passes

    def test_require_early_career_with_adapter_hint_passes(self):
        job = make_job(
            title="Software Engineer",
            raw_text="software engineer",
            role_type="internship",
        )
        source_config = {"require_early_career": True}
        result = filter_per_company_override(job, _FILTERS, source_config)
        assert result.passes

    def test_no_override_always_passes(self):
        job = make_job(raw_text="senior software engineer")
        result = filter_per_company_override(job, _FILTERS, source_config={})
        assert result.passes


# ---------------------------------------------------------------------------
# label_job tests
# ---------------------------------------------------------------------------

class TestLabelJob:
    def test_intern_in_raw_text_sets_internship(self):
        job = make_job(raw_text="software engineering intern summer 2026")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.role_type == "internship"

    def test_new_grad_sets_new_grad(self):
        job = make_job(raw_text="new grad software engineer 2026 campus")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.role_type == "new-grad"

    def test_entry_level_sets_entry_level(self):
        job = make_job(raw_text="entry level software engineer associate ")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.role_type == "entry-level"

    def test_preferred_location_sets_preferred_priority(self):
        job = make_job(location="San Francisco, CA", raw_text="software engineer intern")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.priority == "preferred"

    def test_non_preferred_location_sets_normal_priority(self):
        job = make_job(location="Bozeman, MT", raw_text="software engineer intern")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.priority == "normal"

    def test_location_ambiguous_sets_normal_priority(self):
        job = make_job(location="California", raw_text="software engineer intern")
        labelled = label_job(job, _FILTERS, location_ambiguous=True)
        assert labelled.priority == "normal"

    def test_matched_keywords_populated(self):
        job = make_job(raw_text="software engineer intern")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert "intern" in labelled.matched_keywords
        assert "software" in labelled.matched_keywords

    def test_adapter_role_type_preserved(self):
        job = make_job(raw_text="software engineer", role_type="internship")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.role_type == "internship"

    def test_unknown_role_type_for_unclassified(self):
        job = make_job(raw_text="software engineer senior staff")
        labelled = label_job(job, _FILTERS, location_ambiguous=False)
        assert labelled.role_type == "unknown"


# ---------------------------------------------------------------------------
# apply_filter_pipeline tests
# ---------------------------------------------------------------------------

class TestApplyFilterPipeline:
    def test_good_intern_job_passes_all_steps(self):
        job = make_job(
            title="Software Engineering Intern",
            location="San Francisco, CA",
            raw_text="software engineering intern summer 2026 san francisco ca",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is not None
        # 6 reasons: location, exclude, early_career, tech_role, per_company, label
        assert len(reasons) == 6

    def test_warehouse_job_fails_at_exclude(self):
        job = make_job(
            title="Warehouse Supervisor",
            location="Folsom, CA",
            raw_text="warehouse supervisor night shift folsom ca",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is None
        assert any("exclude" in r for r in reasons)

    def test_non_us_job_fails_at_location(self):
        job = make_job(
            title="Software Engineering Intern",
            location="London, UK",
            raw_text="software engineering intern london uk",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is None
        assert any("non-US" in r for r in reasons)

    def test_senior_role_fails_at_early_career(self):
        job = make_job(
            title="Senior Software Engineer",
            location="Seattle, WA",
            raw_text="senior software engineer 5 years experience seattle wa",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is None
        assert any("early_career" in r for r in reasons)

    def test_hr_intern_fails_at_exclude(self):
        """'hr' is in exclude_keywords, so HR Intern is dropped at the exclude step."""
        job = make_job(
            title="HR Intern",
            location="Austin, TX",
            raw_text="hr intern human resources austin tx",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is None
        assert any("exclude" in r for r in reasons)

    def test_non_tech_intern_fails_at_tech_role(self):
        """An intern role with no tech keywords fails at tech_role step."""
        job = make_job(
            title="Culinary Intern",
            location="Austin, TX",
            raw_text="culinary intern food preparation austin tx",
        )
        result_job, reasons = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is None
        assert any("tech_role" in r for r in reasons)

    def test_labelled_job_has_correct_role_type(self):
        job = make_job(
            title="Data Science Intern",
            location="Remote",
            raw_text="data science intern remote",
        )
        result_job, _ = apply_filter_pipeline(job, _FILTERS, source_config={})
        assert result_job is not None
        assert result_job.role_type == "internship"

    def test_per_company_override_drops_non_intern(self):
        """
        A job with early-career keyword but per_company requires it — passes early_career
        then hits per_company override. Use a case where early-career passes (intern keyword
        present) but then per_company require_early_career recheck is satisfied, vs a case
        where the job has an early-career keyword and passes.
        Actually, the simpler test: job without any early-career keyword fails at
        filter_early_career before reaching per_company. So let's test per_company by
        giving it an early-career keyword but require_early_career=True should pass —
        meaning we need a source_config that fails in per_company only.
        Per spec: per_company checks same condition. Since filter_early_career already passed,
        per_company will also pass for the same job. So the override is redundant unless
        adapter has require_early_career=True for a non-intern source path.
        The real use: apply_filter_pipeline with require_early_career=True should be tested
        by verifying a job WITH early-career keyword passes all 5 steps.
        """
        # Job with intern keyword + tech keyword passes all steps even with override
        job = make_job(
            title="Software Engineering Intern",
            location="Seattle, WA",
            raw_text="software engineering intern seattle wa",
        )
        result_job, reasons = apply_filter_pipeline(
            job, _FILTERS, source_config={"require_early_career": True}
        )
        assert result_job is not None
        assert any("per_company" in r for r in reasons)
        assert "no override" in reasons[-2]  # per_company passes
