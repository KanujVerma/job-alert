# Filter Precision Improvements — Design Spec

**Date:** 2026-05-10  
**Status:** Approved  
**Files affected:** `src/filtering.py`, `companies.yaml`, `tests/test_filtering.py`

---

## Problem

Two classes of false positives are letting junk jobs through to Discord:

1. **Word-boundary bug in `filter_exclude`** — `_phrase_in_text` (substring match) lets `"hr"` match `"chrome"`, `"legal"` match `"paralegal"`, `"retail"` match `"retailer"` etc. Short keywords in exclude lists behave unpredictably.

2. **Weak tech signal from raw_text** — `filter_tech_role` matches against `raw_text`, which is the full corpus including job description. A "Sales Program Manager" with a description mentioning cloud infrastructure passes the tech filter. Ambiguous keywords like `"data"`, `"program manager"`, `"analytics"` need to appear in the job title/category/department to be meaningful.

Goal: improve precision (fewer junk alerts) without sacrificing recall for clear internship/new-grad technical roles.

---

## Design

### 1. Word-boundary fix in `filter_exclude`

**Current:** both `exclude_keywords` and `exclude_unless_intern` loops use `_phrase_in_text` (substring match).  
**Change:** replace with `_word_in_text` (regex word-boundary match) for both loops.

`_word_in_text` already exists in `filtering.py` and handles both single words and multi-word phrases correctly.

```
"hr" in "chrome"           → False  (was True — bug)
"legal" in "paralegal"     → False  (was True — bug)
"retail" in "retailer"     → False  (was True — bug)
"hr" in "human resources hr manager" → True  (correct)
"legal" in "legal intern"  → True   (correct)
```

### 2. Two-tier tech keyword matching in `filter_tech_role`

**Current:** one tier — `technical_role_keywords` matched against `raw_text`.  
**New:** two tiers:

| Tier | Config key | Matched against | Use case |
|---|---|---|---|
| Strong | `technical_role_keywords` | `raw_text` (title + dept + description) | High-confidence terms that mean something even in a description |
| Title-required | `title_tech_keywords` | `job.title + job.category + job.department` only | Ambiguous terms that only signal relevance when they name the role itself |

Both tiers use `_word_in_text` (word-boundary matching).

A job passes `filter_tech_role` if either tier matches. Verbose output names the tier and the matched keyword.

**Example outcomes:**

| Job title | Strong match | Title match | Result |
|---|---|---|---|
| "Software Engineer Intern" | "software engineer" in raw_text ✓ | — | PASS |
| "Data Scientist New Grad" | "data scientist" in raw_text ✓ | — | PASS |
| "Technical Program Manager Intern" | — | "technical program manager" in title ✓ | PASS |
| "Product Manager Intern" | — | "product manager" in title ✓ | PASS |
| "Sales Program Manager" | — | "program manager" in title but "sales" excluded | REJECT (exclude step) |
| "Program Manager — Operations" (no intern signal) | — | "program manager" in title ✓, but early_career fails | REJECT (step 3) |
| "Data Center Operations Technician" | — | "operations" in title ✓, but "technician" conditionally excluded | REJECT (exclude_unless_intern) |
| random job with "cloud" in description only | — | "cloud" not in title/cat/dept | REJECT (no tech signal) |

### 3. Verbose reason improvements

`filter_exclude` verbose message distinguishes:
- `"hard exclude: {keyword}"`
- `"conditional exclude (not intern+tech): {keyword}"`

`filter_tech_role` verbose message:
- `"strong tech keyword in raw_text: {keyword}"`  
- `"title tech keyword in title/category/dept: {keyword}"`

---

## Config changes — `companies.yaml`

### `technical_role_keywords` (strong tier — match in raw_text)

Replace current list with:

```yaml
technical_role_keywords:
  - software
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

Terms removed from here (moved to `title_tech_keywords`): `data`, `analytics`, `business intelligence`, `bi engineer`, `cloud`, `infrastructure`, `platform`, `systems`, `security`, `product manager`, `product management`, `program manager`, `program management`, `technical program manager`, `technical program management`, `tpm`, `tpm intern`, `pm intern`, `solutions architect`, `hardware engineering`.

### New `title_tech_keywords` (title-required tier — match in title/category/dept)

```yaml
title_tech_keywords:
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

### `exclude_keywords` (hard excludes — always reject)

Add to existing list:

```yaml
  - sales
  - sales development
  - business development
  - support specialist
  - recruiter
  - recruiting
  - talent acquisition
```

Existing entries retained: `warehouse`, `fulfillment`, `retail`, `sales associate`, `account executive`, `customer support`, `call center`, `legal`, `finance`, `accounting`, `human resources`, `hr`, `facilities`, `maintenance`, `security guard`, `manufacturing operator`, `economics`, `economist`.

### `exclude_unless_intern` (conditional excludes — reject unless early_career + tech both present)

Replace current list with:

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

---

## Code changes — `src/filtering.py`

### `filter_exclude` (lines ~152–172)

```python
# Before
if _phrase_in_text(kw.lower(), raw):
    return FilterResult(False, f"excluded keyword: {kw}")
# ...
if _phrase_in_text(kw.lower(), raw):
    ...

# After
if _word_in_text(kw.lower(), raw):
    return FilterResult(False, f"hard exclude: {kw}")
# ...
if _word_in_text(kw.lower(), raw):
    ...
    return FilterResult(False, f"conditional exclude (not intern+tech): {kw}")
```

### `filter_tech_role` (lines ~189–197)

```python
def filter_tech_role(job: Job, filters: dict) -> FilterResult:
    raw = job.raw_text.lower() if job.raw_text else ""

    # Tier 1: strong keywords — match anywhere in raw_text
    for kw in filters.get("technical_role_keywords", []):
        if _word_in_text(kw.lower(), raw):
            return FilterResult(True, f"strong tech keyword in raw_text: {kw}")

    # Tier 2: title-required keywords — match only in title/category/department
    title_corpus = " ".join(filter(None, [
        job.title, job.category, job.department
    ])).lower()
    for kw in filters.get("title_tech_keywords", []):
        if _word_in_text(kw.lower(), title_corpus):
            return FilterResult(True, f"title tech keyword in title/category/dept: {kw}")

    return FilterResult(False, "no technical role signal")
```

---

## Test coverage — `tests/test_filtering.py`

New test cases to add to the existing `TestFilterExclude` and `TestFilterTechRole` classes (or grouped into new subclasses):

### Word-boundary exclude tests
- `"hr"` does not match job with `"chrome"` or `"threshold"` in raw_text
- `"legal"` does not match `"paralegal"` in raw_text
- `"sales"` matches `"sales representative"` but not `"wholesale"` (sales is a word in wholesale? No — "wholesale" doesn't contain "sales" as a word boundary)
- `"hr"` does match `"human resources hr manager"`

### Two-tier tech keyword tests
- `"program manager"` in raw_text only → FAIL tech filter
- `"program manager"` in `job.title` → PASS tech filter
- `"data"` in raw_text only → FAIL tech filter
- `"data"` in `job.category` → PASS tech filter
- `"data scientist"` in raw_text → PASS (strong tier)
- `"machine learning"` in raw_text → PASS (strong tier)

### Exclude list expansion tests
- `"customer success"` job without intern/tech signal → FAIL (conditional exclude)
- `"customer success engineer intern"` with tech signal → PASS (conditional exclude bypassed)
- `"support specialist"` job → FAIL (hard exclude)
- `"recruiter"` job → FAIL (hard exclude)

### End-to-end pipeline tests
- `"Technical Program Manager Intern"` → PASS full pipeline
- `"Sales Program Manager"` → FAIL (exclude: sales)
- `"Customer Success Program Manager"` → FAIL (exclude: customer success without intern+tech)
- `"Customer Success Engineer Intern"` with tech signal → PASS

---

## What does not change

- `filter_freshness` — no changes
- `filter_location` — no changes (lower priority, ambiguous locations pass through)
- `filter_early_career` — no changes
- `filter_per_company_override` — no changes
- `label_job` — no changes
- `storage.py` — no changes (cap-churn deferred to follow-on)
- `internship_only` gate — no changes

---

## Rollout

No migration needed. Config changes are additive (`title_tech_keywords` is a new key; missing key returns empty list so existing behavior is preserved if key is absent). State file is unaffected.

After deploy, run `python main.py run --dry-run --verbose` and scan filter reasons for unexpected drops or passes.
