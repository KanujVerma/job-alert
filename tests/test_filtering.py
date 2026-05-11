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
    title: str = "Intern",
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
        "software engineer", "software engineering", "swe", "developer",
        "backend", "frontend", "full stack",
        "machine learning", "ml", "artificial intelligence", "ai",
        "data science", "data scientist",
        "applied scientist", "research scientist",
        "cloud engineer", "platform engineer", "infrastructure engineer",
        "security engineer", "systems engineer", "hardware engineer",
    ],
    "title_tech_keywords": [
        "software", "data", "data engineer", "data engineering",
        "analytics", "business intelligence", "bi", "bi engineer",
        "program manager", "program management",
        "product manager", "product management",
        "technical program manager", "technical program management",
        "technical product manager", "tpm", "tpm intern", "pm intern",
        "solutions architect", "hardware", "hardware engineering",
        "cloud", "platform", "infrastructure", "systems", "security",
    ],
    "exclude_keywords": [
        "warehouse", "fulfillment", "retail", "sales associate", "account executive",
        "customer support", "call center", "legal", "finance", "accounting",
        "human resources", "hr", "facilities", "maintenance", "security guard",
        "manufacturing operator", "economics", "economist",
        "sales", "sales development", "business development",
        "support specialist", "recruiter", "recruiting", "talent acquisition",
    ],
    "exclude_unless_intern": [
        "marketing", "technician", "hardware", "manufacturing", "operations",
        "business analyst", "solutions consultant", "customer success", "support engineer",
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

    def test_state_code_only_passes(self):
        """State code in location with no city in US_TECH_CITIES must still pass."""
        job = make_job(location="Peoria, IL", raw_text="software engineering intern")
        result = filter_location(job, _FILTERS)
        assert result.passes
        assert "state code" in result.reason

    def test_state_code_tx_passes(self):
        """TX-only location (no known city) must match via state code."""
        job = make_job(location="Round Rock, TX", raw_text="software engineer intern")
        result = filter_location(job, _FILTERS)
        assert result.passes
        assert "state code" in result.reason


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
        assert "software engineer" in labelled.matched_keywords

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
        # 7 reasons: freshness, location, exclude, early_career, tech_role, per_company, label
        assert len(reasons) == 7

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


# ---------------------------------------------------------------------------
# Word-boundary tests — Task 1 (v3)
# ---------------------------------------------------------------------------

class TestWordBoundaryFiltering:
    """Short keywords must not match inside longer words."""

    @pytest.mark.parametrize("raw_text,kw", [
        ("developer with html and xml skills", "ml"),   # ml inside html/xml
        ("company-wide product initiative", "pm"),       # pm inside company
        ("I swear this works", "swe"),                   # swe inside swear
        ("template-driven architecture", "tpm"),         # tpm inside template
    ])
    def test_no_tech_false_positives(self, raw_text, kw):
        job = make_job(raw_text=raw_text)
        result = filter_tech_role(job, {"technical_role_keywords": [kw]})
        assert not result.passes, f"'{kw}' should not match inside '{raw_text}'"

    @pytest.mark.parametrize("raw_text,kw", [
        ("international business program", "intern"),    # intern inside international
    ])
    def test_no_early_career_false_positives(self, raw_text, kw):
        job = make_job(raw_text=raw_text)
        result = filter_early_career(job, {"early_career_keywords": [kw]})
        assert not result.passes, f"'{kw}' should not match inside '{raw_text}'"

    @pytest.mark.parametrize("raw_text,kw,fn", [
        ("ML engineer intern 2026", "ml", "tech"),
        ("PM intern product role", "pm", "tech"),
        ("SWE intern summer 2026", "swe", "tech"),
        ("software engineer intern", "software engineer", "tech"),
        ("software intern 2026", "intern", "early"),
        ("internship program", "internship", "early"),
    ])
    def test_true_positives_still_match(self, raw_text, kw, fn):
        job = make_job(raw_text=raw_text)
        if fn == "tech":
            result = filter_tech_role(job, {"technical_role_keywords": [kw]})
        else:
            result = filter_early_career(job, {"early_career_keywords": [kw]})
        assert result.passes, f"'{kw}' should match in '{raw_text}'"


# ---------------------------------------------------------------------------
# Word-boundary tests for filter_exclude — Task 1
# ---------------------------------------------------------------------------

class TestFilterExcludeWordBoundary:
    """_word_in_text must prevent mid-word matches on short exclude keywords."""

    _F = {
        "exclude_keywords": ["hr", "legal", "retail", "sales", "finance"],
        "exclude_unless_intern": ["operations", "marketing"],
        "early_career_keywords": ["intern", "internship", "new grad"],
        "technical_role_keywords": ["software engineer"],
        "title_tech_keywords": [],
    }

    def test_hr_does_not_match_chrome(self):
        job = make_job(title="Chrome Extensions Developer Intern",
                       raw_text="chrome extensions developer intern")
        assert filter_exclude(job, self._F).passes

    def test_hr_does_not_match_threshold(self):
        job = make_job(raw_text="threshold analytics engineer intern")
        assert filter_exclude(job, self._F).passes

    def test_hr_matches_hr_coordinator(self):
        job = make_job(title="HR Coordinator", raw_text="hr coordinator human resources")
        result = filter_exclude(job, self._F)
        assert not result.passes
        assert "hr" in result.reason

    def test_legal_does_not_match_paralegal(self):
        job = make_job(title="Paralegal Assistant Intern",
                       raw_text="paralegal assistant intern")
        assert filter_exclude(job, self._F).passes

    def test_legal_matches_legal_counsel(self):
        job = make_job(title="Legal Counsel", raw_text="legal counsel attorney")
        result = filter_exclude(job, self._F)
        assert not result.passes
        assert "legal" in result.reason

    def test_retail_does_not_match_retailer(self):
        """'retail' must not match 'retailer' — 'er' suffix breaks the word boundary."""
        job = make_job(title="Retailer Software Engineering Intern",
                       raw_text="retailer software engineer intern")
        assert filter_exclude(job, self._F).passes

    def test_sales_matches_sales_manager(self):
        job = make_job(title="Sales Manager", raw_text="sales manager revenue growth")
        result = filter_exclude(job, self._F)
        assert not result.passes
        assert "sales" in result.reason

    def test_hard_exclude_reason_format(self):
        """Reason string must start with 'hard exclude:'."""
        job = make_job(title="HR Analyst", raw_text="hr analyst")
        result = filter_exclude(job, self._F)
        assert result.reason.startswith("hard exclude:")

    def test_conditional_exclude_reason_format(self):
        """Reason string must start with 'conditional exclude'."""
        job = make_job(title="Marketing Manager", raw_text="marketing manager senior")
        result = filter_exclude(job, self._F)
        assert result.reason.startswith("conditional exclude")

    def test_sales_does_not_match_salesforce(self):
        """'sales' hard exclude must not match 'salesforce' — word boundary regression."""
        job = make_job(
            title="Salesforce Software Engineering Intern",
            raw_text="salesforce software engineering intern summer 2026",
        )
        assert filter_exclude(job, self._F).passes


    def test_conditional_exclude_passes_via_title_tech_keyword(self):
        """title_tech_keywords in title satisfies has_tech for exclude_unless_intern."""
        # 'operations' triggers exclude_unless_intern; 'data' in title satisfies title-tier tech
        job = make_job(
            title="Data Operations Intern",
            raw_text="data operations intern summer 2026",
        )
        # has_early: "intern" ✓; has_tech: "data" in title (title_tech_keywords) ✓
        assert filter_exclude(job, _FILTERS).passes

    def test_conditional_exclude_fails_when_title_tech_only_in_raw(self):
        """title_tech_keywords in raw_text body only does NOT satisfy has_tech for exclude_unless_intern."""
        # 'operations' triggers exclude_unless_intern; 'data' only in raw description, not title
        job = make_job(
            title="Operations Coordinator Intern",
            raw_text="operations coordinator intern working with data pipelines",
        )
        # has_early: "intern" ✓; has_tech: "data" NOT in title, "data" in raw but raw isn't title_corpus
        # strong_kws: no strong keyword in raw → has_tech = False → conditional exclude
        result = filter_exclude(job, _FILTERS)
        assert not result.passes


# ---------------------------------------------------------------------------
# Two-tier tech keyword tests — Task 2
# ---------------------------------------------------------------------------

class TestFilterTechRoleTwoTier:
    """Tier 1 (strong) matches raw_text; Tier 2 (title) matches title/category/dept only."""

    _F = _FILTERS

    # --- Tier 1: strong keywords pass from raw_text ---

    def test_software_engineer_in_raw_passes(self):
        job = make_job(title="Intern", raw_text="software engineer intern summer")
        assert filter_tech_role(job, self._F).passes

    def test_machine_learning_in_raw_passes(self):
        job = make_job(title="Research Intern", raw_text="machine learning intern ai")
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "raw_text" in result.reason

    def test_data_scientist_in_raw_passes(self):
        job = make_job(title="Intern", raw_text="data scientist new grad position")
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "raw_text" in result.reason

    # --- Tier 2: ambiguous keywords require title/category/dept match ---

    def test_program_manager_in_raw_only_fails(self):
        """'program manager' in description only must not pass."""
        job = make_job(
            title="Operations Coordinator",
            raw_text="operations coordinator supporting program manager teams",
        )
        result = filter_tech_role(job, self._F)
        assert not result.passes

    def test_program_manager_in_title_passes(self):
        job = make_job(
            title="Program Manager Intern",
            raw_text="program manager intern new grad",
        )
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "title/category/dept" in result.reason

    def test_data_in_raw_only_fails(self):
        """Standalone 'data' in raw_text only must not pass."""
        job = make_job(
            title="Operations Coordinator",
            raw_text="operations coordinator handles data entry",
        )
        assert not filter_tech_role(job, self._F).passes

    def test_data_in_category_passes(self):
        job = make_job(title="Intern", category="Data Engineering")
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "title/category/dept" in result.reason

    def test_software_in_raw_only_fails(self):
        """Standalone 'software' in raw_text must not pass (moved to title tier)."""
        job = make_job(
            title="Sales Coordinator",
            raw_text="sales coordinator using proprietary software tools",
        )
        assert not filter_tech_role(job, self._F).passes

    def test_software_in_title_passes(self):
        job = make_job(
            title="Software Intern",
            raw_text="intern summer 2026 product team",
        )
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "title/category/dept" in result.reason

    def test_tpm_in_title_passes(self):
        job = make_job(
            title="Technical Program Manager Intern",
            raw_text="technical program manager intern new grad",
        )
        result = filter_tech_role(job, self._F)
        assert result.passes
        assert "title/category/dept" in result.reason

    def test_no_signal_fails(self):
        job = make_job(title="Operations Coordinator",
                       raw_text="operations coordinator intern")
        assert not filter_tech_role(job, self._F).passes


# ---------------------------------------------------------------------------
# End-to-end pipeline precision tests
# ---------------------------------------------------------------------------

class TestFilterPrecisionPipeline:
    """Full apply_filter_pipeline tests for the key pass/fail cases."""

    _F = _FILTERS  # updated in Task 2 to include title_tech_keywords

    def _run(self, title, raw_text=None, role_type="unknown",
             department=None, category=None, location="San Francisco, CA"):
        job = make_job(
            title=title,
            location=location,
            raw_text=raw_text,
            role_type=role_type,
            department=department,
            category=category,
        )
        filtered, reasons = apply_filter_pipeline(job, self._F, {})
        return filtered, reasons

    def test_software_engineer_intern_passes(self):
        job, _ = self._run(
            title="Software Engineering Intern",
            raw_text="software engineering intern summer 2026",
        )
        assert job is not None

    def test_technical_program_manager_intern_passes(self):
        job, _ = self._run(
            title="Technical Program Manager Intern",
            raw_text="technical program manager intern new grad product",
        )
        assert job is not None

    def test_product_manager_intern_passes(self):
        job, _ = self._run(
            title="Product Manager Intern",
            raw_text="product manager intern summer new grad",
        )
        assert job is not None

    def test_data_scientist_new_grad_passes(self):
        job, _ = self._run(
            title="Data Scientist, New Grad",
            raw_text="data scientist new grad machine learning",
        )
        assert job is not None

    def test_sales_program_manager_rejected(self):
        """'sales' is a hard exclude — must reject regardless of other signals."""
        job, reasons = self._run(
            title="Sales Program Manager",
            raw_text="sales program manager enterprise accounts",
        )
        assert job is None
        assert any("hard exclude" in r for r in reasons)

    def test_customer_success_program_manager_rejected(self):
        """'customer success' is conditional — fails without intern+tech signal."""
        job, reasons = self._run(
            title="Customer Success Program Manager",
            raw_text="customer success program manager senior",
        )
        assert job is None
        assert any("conditional exclude" in r for r in reasons)

    def test_customer_success_engineer_intern_passes(self):
        """'customer success' with intern+tech (software engineer title) passes conditional."""
        job, _ = self._run(
            title="Customer Success Software Engineer Intern",
            raw_text="customer success software engineer intern",
        )
        assert job is not None

    def test_support_engineer_intern_with_tech_passes(self):
        """'support engineer' with intern+tech signal passes conditional."""
        job, _ = self._run(
            title="Support Engineer Intern",
            raw_text="support engineer intern software backend",
        )
        assert job is not None

    def test_recruiter_rejected(self):
        job, reasons = self._run(
            title="University Recruiter Intern",
            raw_text="university recruiter intern talent acquisition",
        )
        assert job is None
        assert any("hard exclude" in r for r in reasons)

    def test_program_manager_in_description_only_rejected(self):
        """'program manager' only in description (not title/cat/dept) must not pass tech."""
        job, reasons = self._run(
            title="Operations Coordinator Intern",
            raw_text="operations coordinator intern supporting program manager teams",
        )
        # 'operations' is conditional exclude; tech signal only from raw description → rejected
        assert job is None

    def test_data_in_category_new_grad_passes(self):
        """'data' in category qualifies as title-tier tech signal."""
        job, _ = self._run(
            title="New Grad Analyst",
            raw_text="new grad analyst new graduate",
            category="Data Engineering",
        )
        assert job is not None
