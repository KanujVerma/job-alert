# Filter Precision Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix false positives letting junk jobs through Discord by (1) switching `filter_exclude` to word-boundary matching, (2) splitting `filter_tech_role` into two keyword tiers so ambiguous terms only count when in the job title/category/department, and (3) expanding exclude lists in config.

**Architecture:** Three-change sequence: code fix in `filter_exclude` → new two-tier logic in `filter_tech_role` + `filter_exclude` has-tech check → config expansion in `companies.yaml`. Tests written before each code change. All changes are backward-compatible (new `title_tech_keywords` key gracefully absent → empty list).

**Tech Stack:** Python 3.12, pytest, `re` (stdlib). No new dependencies.

---

## File map

| File | Change |
|---|---|
| `src/filtering.py` | Fix `filter_exclude` (word-boundary); rewrite `filter_tech_role` (two tiers); update `filter_exclude` has-tech inner check |
| `tests/test_filtering.py` | Add `TestFilterExcludeWordBoundary`; update `_FILTERS` to include `title_tech_keywords`; add `TestFilterTechRoleTwoTier`; add `TestFilterPrecisionPipeline` |
| `companies.yaml` | Restructure `technical_role_keywords`, add `title_tech_keywords`, expand `exclude_keywords`, update `exclude_unless_intern` |

---

## Task 1: Fix `filter_exclude` word-boundary bug

**Files:**
- Modify: `src/filtering.py` (`filter_exclude` function, lines ~152–172)
- Test: `tests/test_filtering.py` (add `TestFilterExcludeWordBoundary` class)

- [ ] **Step 1: Write the failing tests**

  Open `tests/test_filtering.py`. After the existing `TestFilterExclude` class, add:

  ```python
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
          job = make_job(title="Retailer Operations Intern",
                         raw_text="retailer operations intern")
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
  ```

- [ ] **Step 2: Run the new tests to confirm they fail**

  ```bash
  pytest tests/test_filtering.py::TestFilterExcludeWordBoundary -v
  ```

  Expected: most pass already (substring match happens to be correct for these), but `test_hr_does_not_match_chrome` and `test_hr_does_not_match_threshold` will FAIL (current code uses `_phrase_in_text` which matches "hr" inside other words), and the reason-format tests will FAIL (old format is `"excluded keyword: …"`).

- [ ] **Step 3: Fix `filter_exclude` in `src/filtering.py`**

  Replace the entire `filter_exclude` function body:

  ```python
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

      for kw in filters.get("exclude_unless_intern", []):
          if _word_in_text(kw.lower(), raw):
              has_early = any(_phrase_in_text(ek, raw) for ek in early_career_kws)
              has_tech = any(_phrase_in_text(tk, raw) for tk in strong_kws)
              if not (has_early and has_tech):
                  return FilterResult(False, f"conditional exclude (not intern+tech): {kw}")

      return FilterResult(True, "no excluded keywords")
  ```

  Note: `title_tech_keywords` is not checked in `has_tech` yet — that is added in Task 2.

- [ ] **Step 4: Run the full test suite**

  ```bash
  pytest tests/test_filtering.py -v
  ```

  Expected: all pass. If any existing test asserts exact reason-string format (e.g., `"excluded keyword:"` or `"excluded unless intern:"`), update that assertion to match the new format (`"hard exclude:"` / `"conditional exclude"`).

- [ ] **Step 5: Commit**

  ```bash
  git add src/filtering.py tests/test_filtering.py
  git commit -m "fix: filter_exclude uses word-boundary matching, update reason strings"
  ```

---

## Task 2: Two-tier tech keyword logic in `filter_tech_role`

**Files:**
- Modify: `src/filtering.py` (`filter_tech_role` rewrite; `filter_exclude` has-tech check update)
- Modify: `tests/test_filtering.py` (update `_FILTERS`; add `TestFilterTechRoleTwoTier`)

- [ ] **Step 1: Update `_FILTERS` in `tests/test_filtering.py`**

  Find the `_FILTERS` dict near the top of the test file and replace it with this expanded version. The changes are: remove standalone `"software"` and other ambiguous terms from `technical_role_keywords`; add `"title_tech_keywords"`; add new hard/conditional excludes.

  ```python
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
          "data science", "data scientist", "data engineer", "data engineering",
          "applied scientist", "research scientist",
          "cloud engineer", "platform engineer", "infrastructure engineer",
          "security engineer", "systems engineer", "hardware engineer",
      ],
      "title_tech_keywords": [
          "software", "data", "analytics", "business intelligence", "bi", "bi engineer",
          "program manager", "program management",
          "product manager", "product management",
          "technical program manager", "technical program management",
          "technical product manager", "tpm", "tpm intern", "pm intern",
          "solutions architect", "hardware", "hardware engineering",
          "cloud", "platform", "infrastructure", "systems", "security", "operations",
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
  ```

- [ ] **Step 2: Write the failing tests for two-tier behavior**

  After `TestFilterExcludeWordBoundary`, add:

  ```python
  class TestFilterTechRoleTwoTier:
      """Tier 1 (strong) matches raw_text; Tier 2 (title) matches title/category/dept only."""

      _F = _FILTERS  # uses the updated _FILTERS above

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
              title="Software Engineering Intern",
              raw_text="software engineering intern",
          )
          result = filter_tech_role(job, self._F)
          assert result.passes

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
  ```

- [ ] **Step 3: Run the new tests to confirm they fail**

  ```bash
  pytest tests/test_filtering.py::TestFilterTechRoleTwoTier -v
  ```

  Expected: tests relying on title-tier behavior (e.g., `test_program_manager_in_raw_only_fails`, `test_data_in_raw_only_fails`, `test_software_in_raw_only_fails`) will FAIL because current code treats all keywords as raw_text.

- [ ] **Step 4: Rewrite `filter_tech_role` in `src/filtering.py`**

  Replace the entire `filter_tech_role` function:

  ```python
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
  ```

- [ ] **Step 5: Update `filter_exclude` has-tech check to include title tier**

  In `filter_exclude`, inside the `exclude_unless_intern` loop, the `has_tech` check must also consult `title_tech_keywords`. Replace the `has_tech` line:

  ```python
  # Before (in Task 1 version):
  strong_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]
  has_tech = any(_phrase_in_text(tk, raw) for tk in strong_kws)

  # After — also check title_tech_keywords against title/category/dept:
  strong_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]
  title_kws = [k.lower() for k in filters.get("title_tech_keywords", [])]
  title_corpus = " ".join(filter(None, [job.title, job.category, job.department])).lower()
  has_tech = (
      any(_word_in_text(tk, raw) for tk in strong_kws)
      or any(_word_in_text(tk, title_corpus) for tk in title_kws)
  )
  ```

  Full updated `filter_exclude` after both Task 1 and Task 2 changes:

  ```python
  def filter_exclude(job: Job, filters: dict) -> FilterResult:
      """Step 2: Exclude filter."""
      raw = job.raw_text.lower() if job.raw_text else ""

      # Hard excludes — word-boundary match
      for kw in filters.get("exclude_keywords", []):
          if _word_in_text(kw.lower(), raw):
              return FilterResult(False, f"hard exclude: {kw}")

      # Exclude-unless-intern — word-boundary match on trigger keyword
      early_career_kws = [k.lower() for k in filters.get("early_career_keywords", [])]
      strong_kws = [k.lower() for k in filters.get("technical_role_keywords", [])]
      title_kws = [k.lower() for k in filters.get("title_tech_keywords", [])]

      for kw in filters.get("exclude_unless_intern", []):
          if _word_in_text(kw.lower(), raw):
              has_early = any(_phrase_in_text(ek, raw) for ek in early_career_kws)
              title_corpus = " ".join(
                  filter(None, [job.title, job.category, job.department])
              ).lower()
              has_tech = (
                  any(_word_in_text(tk, raw) for tk in strong_kws)
                  or any(_word_in_text(tk, title_corpus) for tk in title_kws)
              )
              if not (has_early and has_tech):
                  return FilterResult(False, f"conditional exclude (not intern+tech): {kw}")

      return FilterResult(True, "no excluded keywords")
  ```

- [ ] **Step 6: Run the full test suite**

  ```bash
  pytest tests/test_filtering.py -v
  ```

  Expected: all pass. If `test_marketing_intern_with_software_passes` or similar existing tests fail, investigate — they should pass because "software engineering" (strong keyword) is still in `technical_role_keywords` and appears in the raw_text of those tests.

- [ ] **Step 7: Commit**

  ```bash
  git add src/filtering.py tests/test_filtering.py
  git commit -m "feat: two-tier tech keyword filter — title-required tier for ambiguous terms"
  ```

---

## Task 3: Update `companies.yaml` config

**Files:**
- Modify: `companies.yaml` (filters section only)

- [ ] **Step 1: Replace the `technical_role_keywords` list**

  In `companies.yaml`, find `technical_role_keywords:` under `filters:` and replace the entire list:

  ```yaml
    technical_role_keywords:
      - software engineer
      - software engineering
      - swe
      - developer
      - backend
      - frontend
      - full stack
      - machine learning
      - ml
      - artificial intelligence
      - ai
      - data science
      - data scientist
      - data engineer
      - data engineering
      - applied scientist
      - research scientist
      - cloud engineer
      - platform engineer
      - infrastructure engineer
      - security engineer
      - systems engineer
      - hardware engineer
  ```

- [ ] **Step 2: Add `title_tech_keywords` immediately after `technical_role_keywords`**

  ```yaml
    title_tech_keywords:
      - software
      - data
      - analytics
      - business intelligence
      - bi
      - bi engineer
      - program manager
      - program management
      - product manager
      - product management
      - technical program manager
      - technical program management
      - technical product manager
      - tpm
      - tpm intern
      - pm intern
      - solutions architect
      - hardware
      - hardware engineering
      - cloud
      - platform
      - infrastructure
      - systems
      - security
      - operations
  ```

- [ ] **Step 3: Replace `exclude_keywords` list**

  ```yaml
    exclude_keywords:
      - warehouse
      - fulfillment
      - retail
      - sales associate
      - sales
      - sales development
      - account executive
      - business development
      - customer support
      - call center
      - legal
      - finance
      - accounting
      - human resources
      - hr
      - facilities
      - maintenance
      - security guard
      - manufacturing operator
      - economics
      - economist
      - support specialist
      - recruiter
      - recruiting
      - talent acquisition
  ```

- [ ] **Step 4: Replace `exclude_unless_intern` list**

  ```yaml
    exclude_unless_intern:
      - marketing
      - technician
      - hardware
      - manufacturing
      - operations
      - business analyst
      - solutions consultant
      - customer success
      - support engineer
  ```

- [ ] **Step 5: Run the full test suite**

  ```bash
  pytest -v
  ```

  Expected: all tests pass. The YAML changes only affect the runtime config (`companies.yaml`), not the test `_FILTERS` dict (which was already updated in Task 2). All 300+ tests should pass.

- [ ] **Step 6: Commit**

  ```bash
  git add companies.yaml
  git commit -m "config: two-tier keyword lists, expanded excludes (filter precision)"
  ```

---

## Task 4: End-to-end pipeline tests

**Files:**
- Modify: `tests/test_filtering.py` (add `TestFilterPrecisionPipeline` class)

- [ ] **Step 1: Write the end-to-end tests**

  Add at the end of `tests/test_filtering.py`:

  ```python
  # ---------------------------------------------------------------------------
  # End-to-end pipeline precision tests
  # ---------------------------------------------------------------------------

  class TestFilterPrecisionPipeline:
      """Full apply_filter_pipeline tests for the key pass/fail cases."""

      # Filters match the updated companies.yaml exactly
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
          # 'operations' is conditional exclude; even if intern, tech signal is weak
          # 'program manager' only in raw_text → no title-tier match
          assert job is None

      def test_data_in_category_new_grad_passes(self):
          """'data' in category qualifies as title-tier tech signal."""
          job, _ = self._run(
              title="New Grad Analyst",
              raw_text="new grad analyst new graduate",
              category="Data Engineering",
          )
          assert job is not None
  ```

- [ ] **Step 2: Run the new tests**

  ```bash
  pytest tests/test_filtering.py::TestFilterPrecisionPipeline -v
  ```

  Expected: all 11 tests pass. If any fail, diagnose via `--verbose` output and fix.

  To debug a specific failure, run:
  ```bash
  pytest tests/test_filtering.py::TestFilterPrecisionPipeline::test_program_manager_in_description_only_rejected -v -s
  ```
  and add a `print(reasons)` to the test body temporarily.

- [ ] **Step 3: Run the complete test suite**

  ```bash
  pytest -v
  ```

  Expected: all tests pass. Count should be at least 313 (current 302 + ~11 new pipeline tests).

- [ ] **Step 4: Commit**

  ```bash
  git add tests/test_filtering.py
  git commit -m "test: end-to-end precision tests for two-tier filter pipeline"
  ```

---

## Self-review

**Spec coverage:**
- ✅ Word-boundary fix in `filter_exclude` → Task 1
- ✅ `filter_exclude` reason strings updated → Task 1 step 3
- ✅ Two-tier `filter_tech_role` → Task 2 step 4
- ✅ `filter_exclude` has-tech check updated for title tier → Task 2 step 5
- ✅ Verbose reasons name tier → Task 2 step 4 (reason strings in return statements)
- ✅ `technical_role_keywords` updated (software removed) → Task 3 step 1
- ✅ `title_tech_keywords` added → Task 3 step 2
- ✅ `exclude_keywords` expanded → Task 3 step 3
- ✅ `exclude_unless_intern` updated → Task 3 step 4
- ✅ Word-boundary tests for exclude → Task 1 step 1
- ✅ Two-tier tech tests → Task 2 step 2
- ✅ Pipeline tests (TPM intern, sales PM, customer success, etc.) → Task 4 step 1

**Placeholder check:** No TBDs. All code blocks are complete and self-contained.

**Type consistency:** `filter_tech_role(job, filters)` signature unchanged. `filter_exclude(job, filters)` signature unchanged. `apply_filter_pipeline` signature unchanged. `_FILTERS` dict in tests updated in Task 2 and used by all subsequent tasks — consistent.

**One potential breakage to watch:** The existing test `test_marketing_intern_with_software_passes` passes a job with `title="Marketing Software Engineering Intern"` and `raw_text="marketing software engineering intern intern"`. After Task 2, `"software engineering"` (strong keyword) is in `technical_role_keywords` and appears in `raw_text` → `has_tech=True` via strong tier → test passes. No fix needed.
