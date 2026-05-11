# Job Alert v3 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix Snowflake's Playwright auth via XHR interception + page.evaluate fallback, eliminate short-keyword false-positives via word-boundary matching, and add per-job `first_seen` state tracking so re-listed stale jobs never produce alerts.

**Architecture:** Seven tasks across three independent workstreams. Workstream 2 (keyword fix) is two one-line changes. Workstream 3 (state tracking) rewrites `src/storage.py` with v1→v2 migration and updates `main.py`. Workstream 1 (Snowflake) extends `src/browser.py` with XHR interception + `evaluate_fetch`, then rewrites `eightfold_playwright.py` to use a two-tier auth strategy.

**Tech Stack:** Python 3.12, Playwright sync API, requests, pytest, `src/storage.py` (atomic JSON state via `tempfile` + `os.replace`).

---

## Orientation — Read These Before Writing Any Code

| File | What it does | Why you care |
|---|---|---|
| `src/filtering.py` | Filter pipeline | Change `_phrase_in_text` → `_word_in_text` in two functions |
| `src/storage.py` | State load/save/dedup | Full rewrite of the dedup layer; v1→v2 migration |
| `src/browser.py` | Playwright wrapper | Add XHR interception, `evaluate_fetch`, keep page alive |
| `src/adapters/eightfold_playwright.py` | Snowflake adapter | Replace cookie-based auth with two-tier strategy |
| `main.py:1-30` | Imports | Update storage imports, add `datetime` |
| `main.py:129-197` | Company loop | Replace `get_new_jobs`/`mark_seen` with new storage calls |
| `companies.yaml` | Config | Add `first_seen_ttl_days: 180` |
| `tests/test_storage.py` | Storage tests | The `make_job` helper is reusable |
| `tests/test_browser.py` | Browser tests | Shows how `_make_mock_pw()` is structured |
| `tests/test_eightfold_playwright_adapter.py` | Adapter tests | `_SESSION`, `_make_adapter`, `_mock_response` helpers |

### Current State Schema (v1)

```json
{
  "version": 1,
  "first_run_completed_at": null,
  "companies": {
    "Amazon": {
      "last_checked_at": "2026-05-08T10:00:00Z",
      "seen_ids": ["amazon::amazon_jobs::123"]
    }
  }
}
```

### Target State Schema (v2)

```json
{
  "version": 2,
  "first_run_completed_at": null,
  "companies": {
    "Amazon": {
      "last_checked_at": "2026-05-08T10:00:00Z",
      "seen_jobs": {
        "amazon::amazon_jobs::123": {
          "first_seen": "2026-05-08T10:00:00Z",
          "last_seen": "2026-05-08T10:00:00Z",
          "alerted": true
        },
        "amazon::amazon_jobs::new001": {
          "first_seen": "2026-05-08T10:00:00Z",
          "last_seen": "2026-05-08T10:00:00Z",
          "alerted": false,
          "stale_suppressed": true
        }
      }
    }
  }
}
```

---

## Task 1: Keyword Word-Boundary Fix

**Workstream 2 — Two one-line changes in `src/filtering.py`.**

`filter_tech_role` and `filter_early_career` use `_phrase_in_text` (plain substring). Short tokens like `ml`, `pm`, `swe`, `tpm` match inside unrelated words ("html", "company", "elsewhere"). `intern` matches "international". Switch both functions to `_word_in_text`, which adds word-boundary regex — already uses `re.escape` internally.

**Files:**
- Modify: `src/filtering.py:179-181` (filter_early_career) and `src/filtering.py:191-194` (filter_tech_role)
- Test: `tests/test_filtering.py`

- [ ] **Step 1: Write failing tests in `tests/test_filtering.py`**

Add at the bottom of the file (after existing tests). The `make_job` helper already exists in the file — use it directly:

```python
# ---------------------------------------------------------------------------
# Word-boundary tests — Task 1 (v3)
# ---------------------------------------------------------------------------

class TestWordBoundaryFiltering:
    """Short keywords must not match inside longer words."""

    TECH_KWS = ["ml", "pm", "swe", "tpm", "software engineer"]
    EARLY_KWS = ["intern", "internship"]

    @pytest.mark.parametrize("raw_text,kw", [
        ("developer with html and xml skills", "ml"),   # ml inside html/xml
        ("company-wide product initiative", "pm"),       # pm inside company
        ("go elsewhere to apply", "swe"),                # swe inside elsewhere
        ("template-driven architecture", "tpm"),         # tpm inside template
        ("international business program", "intern"),    # intern inside international
    ])
    def test_no_false_positives(self, raw_text, kw):
        job = make_job(raw_text=raw_text)
        tech_result = filter_tech_role(job, {"technical_role_keywords": [kw]})
        early_result = filter_early_career(job, {"early_career_keywords": [kw]})
        # At most one should match (depending on which list the keyword is in)
        # Neither should match due to word-boundary violation
        assert not tech_result.passes or kw not in ["ml", "pm", "swe", "tpm"]
        assert not early_result.passes or kw not in ["intern"]

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
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_filtering.py::TestWordBoundaryFiltering -v
```

Expected: Several `test_no_false_positives` cases FAIL (ml matches html, pm matches company, etc.).

- [ ] **Step 3: Change `_phrase_in_text` to `_word_in_text` in `filter_early_career`**

In `src/filtering.py`, inside `filter_early_career` (around line 179):

```python
# Before
for kw in filters.get("early_career_keywords", []):
    if _phrase_in_text(kw.lower(), raw):
        return FilterResult(True, f"early-career keyword: {kw}")

# After
for kw in filters.get("early_career_keywords", []):
    if _word_in_text(kw.lower(), raw):
        return FilterResult(True, f"early-career keyword: {kw}")
```

- [ ] **Step 4: Change `_phrase_in_text` to `_word_in_text` in `filter_tech_role`**

In `src/filtering.py`, inside `filter_tech_role` (around line 191):

```python
# Before
for kw in filters.get("technical_role_keywords", []):
    if _phrase_in_text(kw.lower(), raw):
        return FilterResult(True, f"tech keyword: {kw}")

# After
for kw in filters.get("technical_role_keywords", []):
    if _word_in_text(kw.lower(), raw):
        return FilterResult(True, f"tech keyword: {kw}")
```

- [ ] **Step 5: Run tests**

```
pytest tests/test_filtering.py -v
```

Expected: All pass, including the new `TestWordBoundaryFiltering` tests.

- [ ] **Step 6: Run full suite**

```
pytest -x -q
```

Expected: All existing tests pass. No regressions.

- [ ] **Step 7: Commit**

```bash
git add src/filtering.py tests/test_filtering.py
git commit -m "fix: word-boundary matching for filter_tech_role and filter_early_career"
```

---

## Task 2: State Schema v2 + Migration

**Workstream 3 — Migrate `seen_ids` lists to `seen_jobs` dicts in `src/storage.py`.**

Add `_migrate_v1_to_v2()` and update `load_state()` to detect v1 state and migrate+save atomically. `_empty_state()` returns v2 format. Existing `get_new_jobs` and `mark_seen` are kept — they'll be removed in Task 5.

**Files:**
- Modify: `src/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing migration tests in `tests/test_storage.py`**

Add after the existing tests (keep all existing imports and tests):

```python
import json as _json  # avoid shadowing local json var

# ---------------------------------------------------------------------------
# v1 → v2 migration tests — Task 2 (v3)
# ---------------------------------------------------------------------------

from src.storage import _migrate_v1_to_v2  # will be added in step 3


class TestMigrateV1ToV2:
    def test_converts_seen_ids_to_seen_jobs(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": "2026-01-01T00:00:00+00:00",
            "companies": {
                "Micron": {
                    "last_checked_at": "2026-05-08T10:00:00+00:00",
                    "seen_ids": ["micron::workday::ABC", "micron::workday::XYZ"],
                }
            },
        }
        result = _migrate_v1_to_v2(v1)

        assert result["version"] == 2
        assert result["first_run_completed_at"] == "2026-01-01T00:00:00+00:00"
        company = result["companies"]["Micron"]
        assert "seen_ids" not in company
        assert company["last_checked_at"] == "2026-05-08T10:00:00+00:00"
        seen_jobs = company["seen_jobs"]
        assert "micron::workday::ABC" in seen_jobs
        assert "micron::workday::XYZ" in seen_jobs
        entry = seen_jobs["micron::workday::ABC"]
        assert entry["alerted"] is True
        assert entry["first_seen"] is not None
        assert entry["last_seen"] == entry["first_seen"]

    def test_empty_seen_ids_becomes_empty_seen_jobs(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "Amazon": {"last_checked_at": None, "seen_ids": []}
            },
        }
        result = _migrate_v1_to_v2(v1)
        assert result["companies"]["Amazon"]["seen_jobs"] == {}
        assert "seen_ids" not in result["companies"]["Amazon"]

    def test_multiple_companies_migrated_independently(self):
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "A": {"last_checked_at": None, "seen_ids": ["a::p::1"]},
                "B": {"last_checked_at": None, "seen_ids": ["b::p::2"]},
            },
        }
        result = _migrate_v1_to_v2(v1)
        assert "a::p::1" in result["companies"]["A"]["seen_jobs"]
        assert "b::p::2" in result["companies"]["B"]["seen_jobs"]


class TestLoadStateMigration:
    def test_v1_file_migrated_and_saved(self, tmp_path):
        state_file = tmp_path / "seen_jobs.json"
        v1 = {
            "version": 1,
            "first_run_completed_at": None,
            "companies": {
                "Salesforce": {
                    "last_checked_at": None,
                    "seen_ids": ["sf::workday::001"],
                }
            },
        }
        state_file.write_text(_json.dumps(v1))

        state = load_state(str(state_file))

        assert state["version"] == 2
        assert "seen_jobs" in state["companies"]["Salesforce"]
        # Verify migration was persisted to disk
        reloaded = _json.loads(state_file.read_text())
        assert reloaded["version"] == 2
        assert "seen_jobs" in reloaded["companies"]["Salesforce"]

    def test_v2_file_loaded_without_migration(self, tmp_path):
        state_file = tmp_path / "seen_jobs.json"
        v2 = {
            "version": 2,
            "first_run_completed_at": None,
            "companies": {},
        }
        state_file.write_text(_json.dumps(v2))
        original_mtime = state_file.stat().st_mtime

        state = load_state(str(state_file))

        assert state["version"] == 2
        # File should not have been rewritten (no migration needed)
        assert state_file.stat().st_mtime == original_mtime

    def test_empty_state_returns_v2(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        state = load_state(path)
        assert state["version"] == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_storage.py::TestMigrateV1ToV2 tests/test_storage.py::TestLoadStateMigration -v
```

Expected: FAIL with `ImportError: cannot import name '_migrate_v1_to_v2'`.

- [ ] **Step 3: Implement `_migrate_v1_to_v2` and update `_empty_state` and `load_state` in `src/storage.py`**

At top of `src/storage.py`, the `_MAX_SEEN_IDS` constant stays for now (removed in Task 5). Add migration below `_empty_state`:

```python
def _empty_state() -> dict:
    return {"version": 2, "first_run_completed_at": None, "companies": {}}


def _migrate_v1_to_v2(state: dict) -> dict:
    """Convert v1 state (seen_ids lists) to v2 (seen_jobs dicts). Mutates and returns state."""
    migration_ts = datetime.now(timezone.utc).isoformat()
    for company_state in state.get("companies", {}).values():
        seen_ids = company_state.pop("seen_ids", [])
        company_state["seen_jobs"] = {
            jid: {
                "first_seen": migration_ts,
                "last_seen": migration_ts,
                "alerted": True,
            }
            for jid in seen_ids
        }
    state["version"] = 2
    return state
```

Update `load_state` to call migration and save:

```python
def load_state(path: str) -> dict:
    """Load JSON state; return empty v2 state if file missing or corrupt.

    Automatically migrates v1 state (seen_ids lists) to v2 (seen_jobs dicts)
    on first load and persists the result atomically.
    """
    if not os.path.exists(path):
        return _empty_state()
    try:
        with open(path, "r") as f:
            data = json.load(f)
        data.setdefault("version", 1)
        data.setdefault("first_run_completed_at", None)
        data.setdefault("companies", {})

        if data["version"] == 1:
            logger.info("Migrating state from v1 to v2...")
            data = _migrate_v1_to_v2(data)
            save_state(data, path)
            logger.info("State migration complete.")

        return data
    except (json.JSONDecodeError, OSError) as e:
        logger.error("Failed to load state from %s: %s. Starting fresh.", path, e)
        return _empty_state()
```

- [ ] **Step 4: Run migration tests**

```
pytest tests/test_storage.py::TestMigrateV1ToV2 tests/test_storage.py::TestLoadStateMigration -v
```

Expected: All pass.

- [ ] **Step 5: Run full storage test suite**

```
pytest tests/test_storage.py -v
```

Expected: All existing tests pass. (The `TestLoadState.test_no_file_returns_empty_state` test checks `version == 1` — update it to check `version == 2` since `_empty_state` now returns v2.)

If `test_no_file_returns_empty_state` fails because it asserts `version == 1`, fix the assertion:

```python
def test_no_file_returns_empty_state(self, tmp_path):
    path = str(tmp_path / "nonexistent.json")
    state = load_state(path)
    assert state["version"] == 2  # changed from 1
    assert state["first_run_completed_at"] is None
    assert state["companies"] == {}
```

- [ ] **Step 6: Run full suite**

```
pytest -x -q
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat: state schema v2 with automatic v1 migration"
```

---

## Task 3: `classify_jobs`, `mark_alerted`, `mark_cap_suppressed`

**Workstream 3 — Core first_seen gate and dedup replacement in `src/storage.py`.**

These three functions replace the old `get_new_jobs` + `mark_seen` pair. They are added alongside the existing functions — `get_new_jobs` and `mark_seen` stay until Task 5.

**Files:**
- Modify: `src/storage.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_storage.py`:

```python
from datetime import timedelta
from src.storage import classify_jobs, mark_alerted, mark_cap_suppressed

_NOW_V3 = datetime(2026, 5, 8, 12, 0, 0, tzinfo=timezone.utc)
_FRESHNESS = 48.0  # hours


def _make_v2_state(company: str = "TestCo", seen_jobs: dict | None = None) -> dict:
    return {
        "version": 2,
        "first_run_completed_at": None,
        "companies": {
            company: {
                "last_checked_at": None,
                "seen_jobs": seen_jobs or {},
            }
        },
    }


def _jid(n: int = 1) -> str:
    return f"testco::platform::{n:03d}"


class TestClassifyJobs:
    def test_new_job_is_alert_candidate(self):
        job = make_job(_jid(1))
        state = _make_v2_state()
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job in result
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry["alerted"] is False
        assert entry["first_seen"] == _NOW_V3.isoformat()

    def test_alerted_job_skipped(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job not in result

    def test_stale_unalerted_job_suppressed(self):
        job = make_job(_jid(1))
        old = (_NOW_V3 - timedelta(hours=72)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": old, "last_seen": old, "alerted": False}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job not in result
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry.get("stale_suppressed") is True

    def test_fresh_unalerted_job_is_candidate(self):
        job = make_job(_jid(1))
        recent = (_NOW_V3 - timedelta(hours=24)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": recent, "last_seen": recent, "alerted": False}
        })
        result = classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert job in result

    def test_last_seen_always_updated(self):
        job = make_job(_jid(1))
        old = (_NOW_V3 - timedelta(hours=1)).isoformat()
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": old, "last_seen": old, "alerted": True}
        })
        classify_jobs([job], "TestCo", state, _FRESHNESS, _NOW_V3)
        assert state["companies"]["TestCo"]["seen_jobs"][_jid(1)]["last_seen"] == _NOW_V3.isoformat()

    def test_missing_company_created(self):
        job = make_job(_jid(1))
        state = {"version": 2, "first_run_completed_at": None, "companies": {}}
        result = classify_jobs([job], "NewCo", state, _FRESHNESS, _NOW_V3)
        assert job in result
        assert "NewCo" in state["companies"]


class TestMarkAlerted:
    def test_sets_alerted_true(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": False}
        })
        mark_alerted([job], "TestCo", state)
        assert state["companies"]["TestCo"]["seen_jobs"][_jid(1)]["alerted"] is True

    def test_clears_cap_suppressed(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {
                "first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(),
                "alerted": False, "cap_suppressed": True,
            }
        })
        mark_alerted([job], "TestCo", state)
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry["alerted"] is True
        assert "cap_suppressed" not in entry

    def test_empty_list_is_noop(self):
        state = _make_v2_state()
        mark_alerted([], "TestCo", state)  # must not raise


class TestMarkCapSuppressed:
    def test_sets_cap_suppressed(self):
        job = make_job(_jid(1))
        state = _make_v2_state(seen_jobs={
            _jid(1): {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": False}
        })
        mark_cap_suppressed([job], "TestCo", state)
        entry = state["companies"]["TestCo"]["seen_jobs"][_jid(1)]
        assert entry.get("cap_suppressed") is True
        assert entry["alerted"] is False  # NOT marked as alerted

    def test_empty_list_is_noop(self):
        state = _make_v2_state()
        mark_cap_suppressed([], "TestCo", state)  # must not raise
```

- [ ] **Step 2: Run tests to verify they fail**

```
pytest tests/test_storage.py::TestClassifyJobs tests/test_storage.py::TestMarkAlerted tests/test_storage.py::TestMarkCapSuppressed -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement the three functions in `src/storage.py`**

Add after the existing `mark_first_run_complete` function. Also add `from datetime import timedelta` to the top imports (alongside the existing `datetime, timezone` import).

```python
# ---------------------------------------------------------------------------
# v2 state functions — replace get_new_jobs / mark_seen
# ---------------------------------------------------------------------------

def classify_jobs(
    jobs: list[Job],
    company: str,
    state: dict,
    freshness_hours: float,
    now: datetime,
    verbose: bool = False,
) -> list[Job]:
    """Classify jobs for alerting. Updates seen_jobs entries in state (in-memory).

    Returns only jobs that should proceed to Discord alerting.
    """
    company_state = state["companies"].setdefault(
        company, {"last_checked_at": None, "seen_jobs": {}}
    )
    seen_jobs = company_state.setdefault("seen_jobs", {})

    candidates = []
    for job in jobs:
        entry = seen_jobs.get(job.id)

        if entry is None:
            seen_jobs[job.id] = {
                "first_seen": now.isoformat(),
                "last_seen": now.isoformat(),
                "alerted": False,
            }
            candidates.append(job)
        else:
            entry["last_seen"] = now.isoformat()

            if entry.get("alerted"):
                if verbose:
                    logger.debug("%s job %s suppressed: already alerted", company, job.id)
            else:
                first_seen_dt = datetime.fromisoformat(entry["first_seen"])
                age_hours = (now - first_seen_dt).total_seconds() / 3600
                if age_hours > freshness_hours:
                    entry["stale_suppressed"] = True
                    if verbose:
                        logger.debug(
                            "%s job %s suppressed: stale_suppressed "
                            "(first_seen %.0fh ago, limit %.0fh)",
                            company, job.id, age_hours, freshness_hours,
                        )
                else:
                    candidates.append(job)

    return candidates


def mark_alerted(jobs: list[Job], company: str, state: dict) -> None:
    """Set alerted=True for jobs successfully sent to Discord."""
    seen_jobs = state["companies"].get(company, {}).get("seen_jobs", {})
    for job in jobs:
        if job.id in seen_jobs:
            seen_jobs[job.id]["alerted"] = True
            seen_jobs[job.id].pop("cap_suppressed", None)


def mark_cap_suppressed(jobs: list[Job], company: str, state: dict) -> None:
    """Mark jobs silenced by max_alerts_per_run cap. They will retry next run."""
    seen_jobs = state["companies"].get(company, {}).get("seen_jobs", {})
    for job in jobs:
        if job.id in seen_jobs:
            seen_jobs[job.id]["cap_suppressed"] = True
```

Add `timedelta` to the existing import at the top of `src/storage.py`:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 4: Run new tests**

```
pytest tests/test_storage.py::TestClassifyJobs tests/test_storage.py::TestMarkAlerted tests/test_storage.py::TestMarkCapSuppressed -v
```

Expected: All pass.

- [ ] **Step 5: Run full storage suite**

```
pytest tests/test_storage.py -v
```

Expected: All pass.

- [ ] **Step 6: Commit**

```bash
git add src/storage.py tests/test_storage.py
git commit -m "feat: classify_jobs, mark_alerted, mark_cap_suppressed for v2 state"
```

---

## Task 4: `update_last_checked`, `prune_seen_jobs`, and Config

**Workstream 3 — Final storage helpers and `companies.yaml` config key.**

**Files:**
- Modify: `src/storage.py`
- Modify: `companies.yaml`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write failing tests**

Add to `tests/test_storage.py`:

```python
from src.storage import update_last_checked, prune_seen_jobs


class TestUpdateLastChecked:
    def test_updates_existing_company(self):
        state = _make_v2_state()
        update_last_checked("TestCo", state, _NOW_V3)
        assert state["companies"]["TestCo"]["last_checked_at"] == _NOW_V3.isoformat()

    def test_creates_missing_company(self):
        state = {"version": 2, "first_run_completed_at": None, "companies": {}}
        update_last_checked("NewCo", state, _NOW_V3)
        assert "NewCo" in state["companies"]
        assert state["companies"]["NewCo"]["last_checked_at"] == _NOW_V3.isoformat()
        assert "seen_jobs" in state["companies"]["NewCo"]

    def test_preserves_seen_jobs(self):
        state = _make_v2_state(seen_jobs={_jid(1): {
            "first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True
        }})
        update_last_checked("TestCo", state, _NOW_V3)
        assert _jid(1) in state["companies"]["TestCo"]["seen_jobs"]


class TestPruneSeenJobs:
    def test_removes_stale_entries(self):
        old = (_NOW_V3 - timedelta(days=200)).isoformat()
        state = _make_v2_state(seen_jobs={
            "old_job": {"first_seen": old, "last_seen": old, "alerted": True},
            "new_job": {"first_seen": _NOW_V3.isoformat(), "last_seen": _NOW_V3.isoformat(), "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "old_job" not in state["companies"]["TestCo"]["seen_jobs"]
        assert "new_job" in state["companies"]["TestCo"]["seen_jobs"]

    def test_keeps_recent_entries(self):
        recent = (_NOW_V3 - timedelta(days=30)).isoformat()
        state = _make_v2_state(seen_jobs={
            "recent_job": {"first_seen": recent, "last_seen": recent, "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "recent_job" in state["companies"]["TestCo"]["seen_jobs"]

    def test_boundary_exactly_at_ttl(self):
        # Entry at exactly TTL days old should be removed (< not <=)
        cutoff = (_NOW_V3 - timedelta(days=180, seconds=1)).isoformat()
        state = _make_v2_state(seen_jobs={
            "boundary_job": {"first_seen": cutoff, "last_seen": cutoff, "alerted": True},
        })
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)
        assert "boundary_job" not in state["companies"]["TestCo"]["seen_jobs"]

    def test_empty_seen_jobs_no_error(self):
        state = _make_v2_state()
        prune_seen_jobs(state, ttl_days=180, now=_NOW_V3)  # must not raise
```

- [ ] **Step 2: Run to verify they fail**

```
pytest tests/test_storage.py::TestUpdateLastChecked tests/test_storage.py::TestPruneSeenJobs -v
```

Expected: FAIL with `ImportError`.

- [ ] **Step 3: Implement in `src/storage.py`**

Add after `mark_cap_suppressed`:

```python
def update_last_checked(company: str, state: dict, now: datetime) -> None:
    """Update last_checked_at for company. Creates the company entry if missing."""
    company_state = state["companies"].setdefault(
        company, {"last_checked_at": None, "seen_jobs": {}}
    )
    company_state.setdefault("seen_jobs", {})
    company_state["last_checked_at"] = now.isoformat()


def prune_seen_jobs(state: dict, ttl_days: int, now: datetime) -> None:
    """Evict seen_jobs entries where last_seen is older than ttl_days."""
    cutoff = now - timedelta(days=ttl_days)
    for company_state in state.get("companies", {}).values():
        seen_jobs = company_state.get("seen_jobs", {})
        to_remove = [
            jid for jid, entry in seen_jobs.items()
            if datetime.fromisoformat(entry["last_seen"]) < cutoff
        ]
        for jid in to_remove:
            del seen_jobs[jid]
```

- [ ] **Step 4: Add `first_seen_ttl_days` to `companies.yaml`**

In `companies.yaml`, under `defaults:`:

```yaml
defaults:
  schedule_minutes: 15
  request_delay_seconds: [2, 4]
  user_agent_base: "job-alert-bot/0.1"
  state_path: state/seen_jobs.json
  timezone: America/Los_Angeles
  max_alerts_per_run: 25
  first_seen_ttl_days: 180
```

(Keep `freshness_hours: 48` if it exists; if missing, it's read from `filters` section which already has it.)

- [ ] **Step 5: Run new tests**

```
pytest tests/test_storage.py::TestUpdateLastChecked tests/test_storage.py::TestPruneSeenJobs -v
```

Expected: All pass.

- [ ] **Step 6: Run full suite**

```
pytest -x -q
```

Expected: All pass.

- [ ] **Step 7: Commit**

```bash
git add src/storage.py tests/test_storage.py companies.yaml
git commit -m "feat: update_last_checked, prune_seen_jobs, first_seen_ttl_days config"
```

---

## Task 5: `main.py` Integration

**Workstream 3 — Wire new storage functions into the company loop. Remove old `get_new_jobs` and `mark_seen`.**

**Files:**
- Modify: `main.py`
- Modify: `src/storage.py` (remove `get_new_jobs`, `mark_seen`, `_MAX_SEEN_IDS`)
- Test: `tests/test_storage.py` (remove tests for deleted functions)

- [ ] **Step 1: Update imports in `main.py`**

Replace the existing storage import block:

```python
# Before
from src.storage import (
    load_state,
    save_state,
    get_new_jobs,
    mark_seen,
    is_first_run,
    mark_first_run_complete,
)

# After
from datetime import datetime, timezone

from src.storage import (
    load_state,
    save_state,
    is_first_run,
    mark_first_run_complete,
    classify_jobs,
    mark_alerted,
    mark_cap_suppressed,
    update_last_checked,
    prune_seen_jobs,
)
```

- [ ] **Step 2: Add pruning call before the company loop in `main.py`**

After `state = load_state(state_path)` and before the `for company_cfg in companies:` loop, add:

```python
ttl_days = int(config.defaults.get("first_seen_ttl_days", 180))
prune_seen_jobs(state, ttl_days, datetime.now(timezone.utc))
```

- [ ] **Step 3: Replace the dedup/alert/mark block inside the company loop**

The current block in the loop (around lines 161–184 in `main.py`):

```python
# Diff against state
new_jobs = get_new_jobs(matched, cname, state)

alerted = 0
for job in new_jobs:
    if notify and not getattr(args, "dry_run", False):
        if not cap_hit:
            if alert_count >= max_alerts:
                cap_hit = True
                if notifier:
                    notifier.send_summary(
                        title="⚠️ Alert Cap Reached",
                        description=f"Max alerts per run ({max_alerts}) reached. Remaining jobs silenced.",
                    )
            else:
                if notifier:
                    notifier.send_job_alert(job)
                alert_count += 1
                alerted += 1
        elif summary_mode:
            summary_jobs.append(job)

# Mark seen (even in dry-run)
mark_seen(new_jobs, cname, state)
```

Replace with:

```python
# Classify against first_seen state (also updates last_seen in-memory)
freshness_hours = float(config.filters.get("freshness_hours", 48))
now = datetime.now(timezone.utc)
alert_candidates = classify_jobs(
    matched, cname, state, freshness_hours, now,
    verbose=getattr(args, "verbose", False),
)

actually_alerted: list = []
cap_suppressed_jobs: list = []
alerted = 0

for job in alert_candidates:
    if notify and not getattr(args, "dry_run", False):
        if not cap_hit:
            if alert_count >= max_alerts:
                cap_hit = True
                cap_suppressed_jobs.append(job)
                if notifier:
                    notifier.send_summary(
                        title="⚠️ Alert Cap Reached",
                        description=f"Max alerts per run ({max_alerts}) reached. Remaining jobs silenced.",
                    )
            else:
                if notifier:
                    notifier.send_job_alert(job)
                alert_count += 1
                alerted += 1
                actually_alerted.append(job)
        else:
            cap_suppressed_jobs.append(job)
    elif summary_mode:
        summary_jobs.append(job)

# Persist first_seen state (always) and alert status (only when not dry-run)
mark_alerted(actually_alerted, cname, state)
mark_cap_suppressed(cap_suppressed_jobs, cname, state)
update_last_checked(cname, state, now)
```

- [ ] **Step 4: Update the verbose print to use `alert_candidates`**

The existing verbose print (after the loop):

```python
if getattr(args, "verbose", False):
    print(
        f"{cname}: fetched={len(fetched)} matched={len(matched)} "
        f"new={len(new_jobs)} alerted={alerted}"
    )
```

Change `new={len(new_jobs)}` to `candidates={len(alert_candidates)}`:

```python
if getattr(args, "verbose", False):
    print(
        f"{cname}: fetched={len(fetched)} matched={len(matched)} "
        f"candidates={len(alert_candidates)} alerted={alerted}"
    )
```

- [ ] **Step 5: Remove `get_new_jobs`, `mark_seen`, `_MAX_SEEN_IDS` from `src/storage.py`**

Delete these three items from `src/storage.py` (read the file first to locate exact line numbers):

- `_MAX_SEEN_IDS = 5000` constant
- `def get_new_jobs(...)` function
- `def mark_seen(...)` function

- [ ] **Step 6: Remove old tests in `tests/test_storage.py`**

Delete the test classes or methods that test `get_new_jobs` and `mark_seen` (they import those functions which no longer exist). Also remove them from the import line at the top of the test file.

- [ ] **Step 7: Run full suite**

```
pytest -x -q
```

Expected: All pass. The old storage tests for `get_new_jobs`/`mark_seen` are gone; everything else passes.

- [ ] **Step 8: Verify dry-run works**

```
python main.py run --dry-run --verbose 2>&1 | head -40
```

Expected: No errors. Shows `candidates=N alerted=0` per company.

- [ ] **Step 9: Commit**

```bash
git add main.py src/storage.py tests/test_storage.py
git commit -m "feat: wire first_seen state tracking into main.py company loop"
```

---

## Task 6: `BrowserClient` — XHR Interception + `evaluate_fetch`

**Workstream 1 — Three changes to `src/browser.py`: (1) `BrowserSessionContext` gains two new optional fields, (2) `bootstrap_session` intercepts XHR request headers and keeps the page alive, (3) new `evaluate_fetch` method.**

**Files:**
- Modify: `src/browser.py`
- Test: `tests/test_browser.py`

- [ ] **Step 1: Read `src/browser.py` in full before editing**

The key methods: `_ensure_started`, `bootstrap_session` (lines 73–148), `close` (154–163), `_save_artifacts` (169–198).

Note: `bootstrap_session` currently closes the page in `finally: page.close()`. **This must change** — the page must stay open for `evaluate_fetch`.

- [ ] **Step 2: Write failing tests in `tests/test_browser.py`**

Add after the existing tests:

```python
# ---------------------------------------------------------------------------
# Task 6 (v3): XHR interception + evaluate_fetch
# ---------------------------------------------------------------------------

from unittest.mock import call


class TestBrowserSessionContextV3:
    def test_new_fields_have_defaults(self):
        """Existing 4-arg construction still works — new fields are optional."""
        ctx = BrowserSessionContext(
            cookies={"sid": "abc"},
            headers={"Origin": "https://example.com"},
            final_url="https://example.com/jobs",
            captured_urls=(),
        )
        assert ctx.captured_request_headers == {}
        assert ctx.captured_first_response is None

    def test_new_fields_can_be_set(self):
        ctx = BrowserSessionContext(
            cookies={},
            headers={},
            final_url="https://example.com",
            captured_urls=(),
            captured_request_headers={"Authorization": "Bearer token"},
            captured_first_response='{"data": {"positions": []}}',
        )
        assert ctx.captured_request_headers == {"Authorization": "Bearer token"}
        assert ctx.captured_first_response == '{"data": {"positions": []}}'


def _make_mock_browser_for_intercept():
    """Build a BrowserClient with a mocked Playwright stack for intercept tests."""
    mock_page = MagicMock()
    mock_page.url = "https://careers.snowflake.com/us/en/jobs"
    mock_page.evaluate.return_value = "Mozilla/5.0 Test"

    mock_context = MagicMock()
    mock_context.new_page.return_value = mock_page
    mock_context.cookies.return_value = [{"name": "PHPSESSID", "value": "sess123"}]

    mock_browser_obj = MagicMock()
    mock_pw = MagicMock()
    mock_pw.chromium.launch.return_value = mock_browser_obj
    mock_browser_obj.new_context.return_value = mock_context

    with patch("src.browser._sync_playwright") as mock_sync_pw:
        mock_sync_pw.return_value.__enter__ = MagicMock(return_value=mock_pw)
        mock_sync_pw.return_value.__exit__ = MagicMock(return_value=False)
        mock_sync_pw.return_value.start.return_value = mock_pw

        client = BrowserClient()
        client._pw = mock_pw
        client._browser = mock_browser_obj
        client._context = mock_context

    return client, mock_page


class TestBootstrapSessionXHRInterception:
    def test_captures_request_headers_on_matching_response(self):
        client, mock_page = _make_mock_browser_for_intercept()

        # Simulate a response event for the matching URL
        captured_handler = None

        def fake_on(event, handler):
            nonlocal captured_handler
            if event == "response":
                captured_handler = handler

        mock_page.on.side_effect = fake_on

        # After goto, fire a fake matching response
        def fake_goto(*args, **kwargs):
            if captured_handler:
                mock_resp = MagicMock()
                mock_resp.url = "https://careers.snowflake.com/api/apply/v2/jobs?limit=20"
                mock_resp.request.headers = {
                    "Authorization": "Bearer tok",
                    "sec-fetch-site": "same-origin",  # should be filtered
                    ":method": "GET",                  # should be filtered
                }
                mock_resp.text.return_value = '{"data": {"positions": [], "count": 0}}'
                captured_handler(mock_resp)

        mock_page.goto.side_effect = fake_goto
        mock_page.wait_for_load_state = MagicMock()

        session = client.bootstrap_session(
            "https://careers.snowflake.com",
            wait_for_response_url="**/api/apply/v2/jobs**",
        )

        assert "Authorization" in session.captured_request_headers
        assert "sec-fetch-site" not in session.captured_request_headers
        assert ":method" not in session.captured_request_headers
        assert session.captured_first_response is not None

    def test_page_stays_open_after_bootstrap(self):
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.wait_for_load_state = MagicMock()

        client.bootstrap_session("https://careers.snowflake.com")

        mock_page.close.assert_not_called()
        assert client._page is mock_page

    def test_page_closed_on_bootstrap_failure(self):
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.goto.side_effect = RuntimeError("timeout")

        with pytest.raises(RuntimeError):
            client.bootstrap_session("https://careers.snowflake.com", company="Snowflake")

        mock_page.close.assert_called_once()
        assert client._page is None

    def test_close_closes_page(self):
        client, mock_page = _make_mock_browser_for_intercept()
        mock_page.wait_for_load_state = MagicMock()
        client.bootstrap_session("https://careers.snowflake.com")

        client.close()

        mock_page.close.assert_called_once()
        assert client._page is None


class TestEvaluateFetch:
    def test_raises_without_active_page(self):
        client = BrowserClient()
        with pytest.raises(RuntimeError, match="bootstrap_session must be called"):
            client.evaluate_fetch("https://example.com/api", {})

    def test_calls_page_evaluate_with_correct_args(self):
        client, mock_page = _make_mock_browser_for_intercept()
        client._page = mock_page
        mock_page.evaluate.return_value = {"data": {"positions": [], "count": 0}}

        result = client.evaluate_fetch(
            "https://careers.snowflake.com/api/apply/v2/jobs",
            {"limit": 20, "offset": 0},
        )

        assert result == {"data": {"positions": [], "count": 0}}
        mock_page.evaluate.assert_called_once()
        call_args = mock_page.evaluate.call_args
        assert "fetch" in call_args[0][0]  # JS code contains fetch
        assert call_args[0][1]["url"] == "https://careers.snowflake.com/api/apply/v2/jobs"
        assert call_args[0][1]["params"]["limit"] == "20"


class TestHeaderFiltering:
    def test_pseudo_headers_filtered(self):
        from src.browser import _filter_request_headers
        headers = {
            ":method": "GET",
            ":authority": "careers.snowflake.com",
            "Authorization": "Bearer tok",
            "sec-fetch-site": "same-origin",
            "sec-fetch-mode": "cors",
            "Accept": "application/json",
        }
        result = _filter_request_headers(headers)
        assert ":method" not in result
        assert ":authority" not in result
        assert "sec-fetch-site" not in result
        assert "Authorization" in result
        assert "Accept" in result
```

- [ ] **Step 3: Run tests to verify they fail**

```
pytest tests/test_browser.py::TestBrowserSessionContextV3 tests/test_browser.py::TestBootstrapSessionXHRInterception tests/test_browser.py::TestEvaluateFetch tests/test_browser.py::TestHeaderFiltering -v
```

Expected: FAIL — `_filter_request_headers` not found, `captured_request_headers` missing, etc.

- [ ] **Step 4: Add `_filter_request_headers` to `src/browser.py`**

Add as a module-level helper before the `BrowserSessionContext` class:

```python
_HEADER_BLOCK_PREFIXES = ("sec-fetch-", "sec-ch-", ":", "x-playwright-")
_HEADER_BLOCK_EXACT = frozenset({"host", "connection", "content-length", "transfer-encoding"})


def _filter_request_headers(headers: dict[str, str]) -> dict[str, str]:
    """Drop browser-internal and pseudo-headers; keep forwarding-safe ones."""
    result = {}
    for k, v in headers.items():
        k_lower = k.lower()
        if any(k_lower.startswith(p) for p in _HEADER_BLOCK_PREFIXES):
            continue
        if k_lower in _HEADER_BLOCK_EXACT:
            continue
        result[k] = v
    return result
```

- [ ] **Step 5: Update `BrowserSessionContext` to add two optional fields**

Update the `dataclass` import at top of `src/browser.py`:

```python
from dataclasses import dataclass, field
```

Update the dataclass:

```python
@dataclass(frozen=True)
class BrowserSessionContext:
    cookies: dict[str, str]
    headers: dict[str, str]
    final_url: str
    captured_urls: tuple[str, ...]
    captured_request_headers: dict[str, str] = field(default_factory=dict)
    captured_first_response: str | None = None
```

- [ ] **Step 6: Add `self._page = None` to `BrowserClient.__init__`**

```python
def __init__(self) -> None:
    self.available: bool = True
    self._pw = None
    self._browser = None
    self._context = None
    self._page = None
```

- [ ] **Step 7: Update `bootstrap_session` — intercept headers, keep page alive**

Replace the entire `bootstrap_session` method (lines 73–148) with:

```python
def bootstrap_session(
    self,
    url: str,
    *,
    company: str = "unknown",
    wait_for_selector: str | None = None,
    wait_for_response_url: str | None = None,
    timeout_seconds: int = 30,
) -> BrowserSessionContext:
    """Navigate to url, wait for SPA to settle, return session context.

    If wait_for_response_url is provided, intercepts the first matching XHR
    and captures its request headers + response body.
    The page stays open after return — call close() when done.
    On any exception: saves debug artifacts then re-raises.
    """
    self._ensure_started()
    timeout_ms = timeout_seconds * 1000
    captured_urls: list[str] = []
    captured_request_headers: dict[str, str] = {}
    captured_first_response: str | None = None

    page = self._context.new_page()
    try:
        if wait_for_response_url:
            needle = wait_for_response_url.replace("**", "")

            def handle_response(resp) -> None:
                nonlocal captured_request_headers, captured_first_response
                if needle in resp.url:
                    captured_urls.append(resp.url)
                    if not captured_request_headers:  # first match only
                        captured_request_headers = _filter_request_headers(
                            dict(resp.request.headers)
                        )
                        try:
                            captured_first_response = resp.text()
                        except Exception:
                            pass

            page.on("response", handle_response)

        page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

        if wait_for_selector:
            try:
                page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            except Exception:
                page.wait_for_load_state("networkidle", timeout=timeout_ms)
        else:
            page.wait_for_load_state("networkidle", timeout=timeout_ms)

        final_url = page.url
        raw_cookies = self._context.cookies()
        cookies = {c["name"]: c["value"] for c in raw_cookies}

        parsed = urlparse(url)
        origin = f"{parsed.scheme}://{parsed.netloc}"
        headers: dict[str, str] = {
            "Origin": origin,
            "Referer": final_url,
        }
        try:
            ua = page.evaluate("navigator.userAgent")
            if ua:
                headers["User-Agent"] = str(ua)
        except Exception:
            pass

        self._page = page  # keep alive for evaluate_fetch fallback
        return BrowserSessionContext(
            cookies=cookies,
            headers=headers,
            final_url=final_url,
            captured_urls=tuple(captured_urls),
            captured_request_headers=captured_request_headers,
            captured_first_response=captured_first_response,
        )

    except Exception as exc:
        self._save_artifacts(page, company, exc)
        page.close()  # close only on failure
        raise
    # No finally: page.close() — success path keeps the page alive
```

- [ ] **Step 8: Add `evaluate_fetch` method to `BrowserClient`**

Add after `bootstrap_session`:

```python
def evaluate_fetch(self, url: str, params: dict) -> dict:
    """Run a fetch() call inside the live Playwright page. Returns parsed JSON.

    Requires bootstrap_session to have been called first.
    Uses credentials: 'include' so localStorage/sessionStorage tokens apply.
    """
    if self._page is None:
        raise RuntimeError(
            "No active page — bootstrap_session must be called before evaluate_fetch"
        )
    js = """
    async (args) => {
        const p = new URLSearchParams(args.params);
        const resp = await fetch(args.url + '?' + p.toString(), {credentials: 'include'});
        if (!resp.ok) {
            throw new Error('fetch failed: ' + resp.status + ' ' + resp.statusText);
        }
        return resp.json();
    }
    """
    return self._page.evaluate(
        js, {"url": url, "params": {k: str(v) for k, v in params.items()}}
    )
```

- [ ] **Step 9: Update `close()` to close the page first**

Replace the `close` method:

```python
def close(self) -> None:
    """Idempotent teardown. Call in do_run() finally block."""
    if self._page is not None:
        try:
            self._page.close()
        except Exception:
            pass
        self._page = None
    for attr, method in [("_context", "close"), ("_browser", "close"), ("_pw", "stop")]:
        obj = getattr(self, attr, None)
        if obj is not None:
            try:
                getattr(obj, method)()
            except Exception:
                pass
            setattr(self, attr, None)
```

- [ ] **Step 10: Run new browser tests**

```
pytest tests/test_browser.py -v
```

Expected: All pass, including the new Task 6 tests.

- [ ] **Step 11: Run full suite**

```
pytest -x -q
```

Expected: All pass.

- [ ] **Step 12: Commit**

```bash
git add src/browser.py tests/test_browser.py
git commit -m "feat: browser XHR interception, evaluate_fetch, page lifecycle for v3"
```

---

## Task 7: `EightfoldPlaywrightAdapter` — Two-Tier Auth Strategy

**Workstream 1 — Rewrite `src/adapters/eightfold_playwright.py` to use intercepted XHR headers first, fall back to `page.evaluate` on auth failure.**

The current adapter uses `session.cookies` as the auth gate and passes cookies to HTTPClient. The new strategy:
1. Try intercepted request headers via HTTPClient (fast, reuses existing code).
2. Detect auth failure: HTTP 401/403 or JSON body with `status==failure` / `errorMsg`.
3. Fall back to `browser.evaluate_fetch()` for all remaining pages.
4. Use `captured_first_response` as page 1 if available (skip redundant first call).

**Files:**
- Modify: `src/adapters/eightfold_playwright.py`
- Test: `tests/test_eightfold_playwright_adapter.py`

- [ ] **Step 1: Read `src/adapters/eightfold_playwright.py` and `tests/test_eightfold_playwright_adapter.py` in full**

Understand the existing test helpers: `_SESSION`, `_make_adapter`, `_mock_response`. You will update `_SESSION` to include `captured_request_headers`.

- [ ] **Step 2: Write new failing tests**

Add after the existing tests in `tests/test_eightfold_playwright_adapter.py`. First, create an updated session fixture with `captured_request_headers`:

```python
import json as _json_mod
from pathlib import Path

_FIXTURE = Path(__file__).parent / "fixtures" / "eightfold_snowflake.json"

_SESSION_V3 = BrowserSessionContext(
    cookies={"PHPSESSID": "test-session"},
    headers={
        "Origin": "https://careers.snowflake.com",
        "Referer": "https://careers.snowflake.com/us/en/jobs",
        "User-Agent": "Mozilla/5.0",
    },
    final_url="https://careers.snowflake.com/us/en/jobs",
    captured_urls=("https://careers.snowflake.com/api/apply/v2/jobs?limit=20",),
    captured_request_headers={
        "Authorization": "Bearer tenant-token-xyz",
        "Accept": "application/json",
    },
    captured_first_response=None,
)


def _make_adapter_v3(session=None, browser_available=True):
    http = MagicMock(spec=HTTPClient)
    browser = MagicMock(spec=BrowserClient)
    browser.available = browser_available
    browser.bootstrap_session.return_value = session or _SESSION_V3
    return EightfoldPlaywrightAdapter(
        company="Snowflake",
        config=_CONFIG,
        http=http,
        browser=browser,
    )


class TestTwoTierAuth:
    def test_httpClient_relay_success_uses_captured_headers(self):
        """If intercepted headers work, HTTPClient is used for all pages."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())
        adapter.http.get.return_value = _mock_response(payload)

        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        call_kwargs = adapter.http.get.call_args[1]
        # Should use captured_request_headers, not cookies
        assert call_kwargs.get("headers") == _SESSION_V3.captured_request_headers

    def test_httpClient_401_switches_to_evaluate_fetch(self):
        """HTTP 401 triggers fallback to page.evaluate_fetch."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        # First call returns 401, evaluate_fetch returns good data
        adapter.http.get.return_value = _mock_response({}, status=401)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_httpClient_403_switches_to_evaluate_fetch(self):
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        adapter.http.get.return_value = _mock_response({}, status=403)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_errormsg_in_response_switches_to_evaluate_fetch(self):
        """JSON errorMsg triggers fallback."""
        adapter = _make_adapter_v3()
        payload = _json_mod.loads(_FIXTURE.read_text())

        auth_error = {"status": "failure", "errorMsg": "Tenant not identified"}
        adapter.http.get.return_value = _mock_response(auth_error)
        adapter.browser.evaluate_fetch.return_value = payload

        jobs = list(adapter.fetch())

        adapter.browser.evaluate_fetch.assert_called()
        assert len(jobs) > 0

    def test_captured_first_response_skips_first_httpClient_call(self):
        """Page-1 from captured_first_response — HTTPClient starts at offset=_LIMIT."""
        from src.adapters.eightfold import _LIMIT
        fixture_data = _json_mod.loads(_FIXTURE.read_text())
        # Single-page response (offset 0 is the only page)
        first_resp_json = _json_mod.dumps(fixture_data)

        session_with_capture = BrowserSessionContext(
            cookies=_SESSION_V3.cookies,
            headers=_SESSION_V3.headers,
            final_url=_SESSION_V3.final_url,
            captured_urls=_SESSION_V3.captured_urls,
            captured_request_headers=_SESSION_V3.captured_request_headers,
            captured_first_response=first_resp_json,
        )
        adapter = _make_adapter_v3(session=session_with_capture)
        # If page-1 is used from captured_first_response, HTTP should not be called
        # (count == len(positions) so no page 2 needed)
        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        adapter.http.get.assert_not_called()  # all data from captured response

    def test_evaluate_fetch_failure_returns_empty(self):
        """evaluate_fetch exception → capture_debug_artifacts + return []."""
        adapter = _make_adapter_v3()
        adapter.http.get.return_value = _mock_response({}, status=401)
        adapter.browser.evaluate_fetch.side_effect = RuntimeError("page closed")

        jobs = list(adapter.fetch())

        assert jobs == []
        adapter.browser.capture_debug_artifacts.assert_called_once()

    def test_no_captured_headers_falls_through_to_session_headers(self):
        """If captured_request_headers is empty, fall back to session.headers."""
        session_no_capture = BrowserSessionContext(
            cookies=_SESSION_V3.cookies,
            headers=_SESSION_V3.headers,
            final_url=_SESSION_V3.final_url,
            captured_urls=(),
            captured_request_headers={},  # empty
            captured_first_response=None,
        )
        adapter = _make_adapter_v3(session=session_no_capture)
        payload = _json_mod.loads(_FIXTURE.read_text())
        adapter.http.get.return_value = _mock_response(payload)

        jobs = list(adapter.fetch())

        assert len(jobs) > 0
        call_kwargs = adapter.http.get.call_args[1]
        # Should use session.headers when captured_request_headers is empty
        assert call_kwargs.get("headers") == _SESSION_V3.headers
```

- [ ] **Step 3: Run to verify tests fail**

```
pytest tests/test_eightfold_playwright_adapter.py::TestTwoTierAuth -v
```

Expected: FAIL — new assertions don't match current adapter behavior.

- [ ] **Step 4: Rewrite `src/adapters/eightfold_playwright.py`**

Replace the entire file content:

```python
# src/adapters/eightfold_playwright.py
"""Eightfold adapter with Playwright browser bootstrap for JS-rendered SPA auth.

Two-tier auth strategy:
1. Intercept XHR request headers during SPA boot → relay via HTTPClient (fast).
2. If relay returns 401/403 or auth error JSON → fall back to browser.evaluate_fetch().

Pilot adapter for Snowflake (careers.snowflake.com).
Config keys: base_url, api_path, location_country, use_playwright, browser_timeout_seconds.
"""
from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from datetime import datetime, timezone

import requests

from src.adapters.base import BaseAdapter
from src.adapters.eightfold import _strip_html, _parse_iso, _DESCRIPTION_MAX, _LIMIT
from src.filtering import make_job_id
from src.models import Job

logger = logging.getLogger(__name__)


def _is_auth_failure(payload: dict) -> bool:
    """Return True if the JSON payload indicates an authentication/tenant failure."""
    return payload.get("status") == "failure" or bool(payload.get("errorMsg"))


class EightfoldPlaywrightAdapter(BaseAdapter):
    """Eightfold adapter that bootstraps the SPA via Playwright to obtain auth."""

    source_platform = "eightfold_playwright"

    def fetch(self) -> Iterator[Job]:
        if self.browser is None or not self.browser.available:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: no BrowserClient available — skipping",
                self.company,
            )
            return

        base_url = self.config["base_url"].rstrip("/")
        api_path = self.config.get("api_path", "/api/apply/v2/jobs")
        location_country = self.config.get("location_country", "United States")
        domain = self.config.get("domain") or base_url.split("//", 1)[-1].split("/")[0]
        timeout_seconds = int(self.config.get("browser_timeout_seconds", 30))

        # Step 1: Boot SPA, intercept XHR request headers
        try:
            session = self.browser.bootstrap_session(
                base_url,
                company=self.company,
                wait_for_response_url="**/api/apply/v2/jobs**",
                timeout_seconds=timeout_seconds,
            )
        except Exception as exc:
            logger.warning(
                "EightfoldPlaywrightAdapter[%s]: browser bootstrap failed: %s",
                self.company, exc,
            )
            return

        api_url = f"{base_url}{api_path}"
        detected_at = datetime.now(tz=timezone.utc)
        offset = 0
        total: int | None = None
        use_fallback = False

        # Prefer captured request headers; fall back to session headers if empty
        relay_headers = session.captured_request_headers or session.headers

        # Step 2: Page-1 optimisation — use captured response if available
        if session.captured_first_response:
            try:
                payload = json.loads(session.captured_first_response)
                data = payload.get("data") or payload
                positions = data.get("positions", [])
                page_total = data.get("count", len(positions))
                if total is None:
                    total = page_total
                for pos in positions:
                    try:
                        job = _parse_position(
                            pos, self.company, self.source_platform, detected_at
                        )
                        if job is not None:
                            yield job
                    except Exception as exc:
                        logger.warning(
                            "EightfoldPlaywrightAdapter[%s]: skipping position %s: %s",
                            self.company, pos.get("id"), exc,
                        )
                offset += len(positions)
                if total is not None and offset >= total:
                    return
                self.http.polite_delay(1.0, 2.0)
            except (ValueError, KeyError) as exc:
                logger.warning(
                    "EightfoldPlaywrightAdapter[%s]: bad captured_first_response, "
                    "continuing from offset 0: %s",
                    self.company, exc,
                )
                offset = 0  # reset and start from scratch

        # Step 3: Paginate remaining pages
        while True:
            params: dict = {
                "domain": domain,
                "limit": _LIMIT,
                "offset": offset,
                "json": "true",
            }
            if location_country:
                params["location_country"] = location_country

            if use_fallback:
                try:
                    payload = self.browser.evaluate_fetch(api_url, params)
                except Exception as exc:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: evaluate_fetch failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    self.browser.capture_debug_artifacts(self.company, exc)
                    return
            else:
                try:
                    resp = self.http.get(
                        api_url,
                        params=params,
                        cookies=session.cookies,
                        headers=relay_headers,
                    )
                except requests.RequestException as exc:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: request failed at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    return

                if resp.status_code in (401, 403):
                    logger.info(
                        "EightfoldPlaywrightAdapter[%s]: HTTP %d — switching to page.evaluate fallback",
                        self.company, resp.status_code,
                    )
                    use_fallback = True
                    continue  # retry this offset with fallback

                if not resp.ok:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: HTTP %d at offset=%d",
                        self.company, resp.status_code, offset,
                    )
                    return

                try:
                    payload = resp.json()
                except ValueError as exc:
                    logger.error(
                        "EightfoldPlaywrightAdapter[%s]: JSON parse error at offset=%d: %s",
                        self.company, offset, exc,
                    )
                    return

                if _is_auth_failure(payload):
                    logger.info(
                        "EightfoldPlaywrightAdapter[%s]: auth error ('%s') — switching to page.evaluate fallback",
                        self.company, payload.get("errorMsg", "unknown"),
                    )
                    use_fallback = True
                    continue  # retry this offset with fallback

            data = payload.get("data") or payload
            positions = data.get("positions", [])
            count = data.get("count", len(positions))

            if total is None:
                total = count

            if not positions:
                break

            for pos in positions:
                try:
                    job = _parse_position(
                        pos, self.company, self.source_platform, detected_at
                    )
                    if job is not None:
                        yield job
                except Exception as exc:
                    logger.warning(
                        "EightfoldPlaywrightAdapter[%s]: skipping position %s: %s",
                        self.company, pos.get("id"), exc,
                    )

            offset += len(positions)
            if total is not None and offset >= total:
                break

            self.http.polite_delay(1.0, 2.0)


def _parse_position(
    pos: dict,
    company: str,
    source_platform: str,
    detected_at: datetime,
) -> Job | None:
    """Parse one Eightfold position dict into a Job. Returns None if title is missing."""
    official_id = str(pos.get("id") or "").strip()
    title = (pos.get("name") or "").strip()
    if not title:
        return None

    location = (pos.get("location") or "Not specified").strip()
    department = (pos.get("department") or "").strip() or None
    job_url = (pos.get("canonicalPositionUrl") or "").strip()
    posted_at = _parse_iso(pos.get("t_create"))
    raw_desc = _strip_html(pos.get("description") or "")[:_DESCRIPTION_MAX]
    raw_text = " ".join(filter(None, [title, location, department, raw_desc])).lower()

    job_id = make_job_id(
        company=company,
        source_platform=source_platform,
        title=title,
        location=location,
        official_id=official_id if official_id else None,
    )

    return Job(
        id=job_id,
        company=company,
        title=title,
        location=location,
        department=department,
        category=None,
        url=job_url,
        source_platform=source_platform,
        posted_at=posted_at,
        detected_at=detected_at,
        raw_text=raw_text,
        role_type="unknown",
        priority="normal",
        matched_keywords=(),
    )
```

- [ ] **Step 5: Run new tests**

```
pytest tests/test_eightfold_playwright_adapter.py::TestTwoTierAuth -v
```

Expected: All pass.

- [ ] **Step 6: Run full adapter test suite**

```
pytest tests/test_eightfold_playwright_adapter.py -v
```

Expected: All pass, including existing tests. (Old `_SESSION` has empty `captured_request_headers` by default — adapter falls back to `session.headers`, which the existing happy-path test provides.)

- [ ] **Step 7: Run full suite**

```
pytest -x -q
```

Expected: All pass. Count should be ≥ original + all new tests.

- [ ] **Step 8: Commit**

```bash
git add src/adapters/eightfold_playwright.py tests/test_eightfold_playwright_adapter.py
git commit -m "feat: Snowflake two-tier auth — XHR intercept relay + page.evaluate fallback"
```

---

## Self-Review Checklist (for the implementer)

Before marking the branch ready:

- [ ] `pytest -x -q` passes with no failures or warnings about removed functions
- [ ] `python main.py run --dry-run --verbose` runs without errors; output shows `candidates=N` per company
- [ ] State file at `state/seen_jobs.json` has `"version": 2` and `"seen_jobs"` per company after one run
- [ ] `python main.py run --company Snowflake --verbose` shows either HTTPClient success or fallback to evaluate_fetch (check log lines)
- [ ] No import of `playwright` in any file except `src/browser.py` and `src/adapters/eightfold_playwright.py`: `grep -r "from playwright" src/ | grep -v browser.py | grep -v eightfold_playwright.py` → no output
- [ ] `filter_early_career` and `filter_tech_role` both call `_word_in_text` (not `_phrase_in_text`): `grep "_phrase_in_text" src/filtering.py` → no output in those two functions
- [ ] `get_new_jobs` and `mark_seen` are gone: `grep -r "get_new_jobs\|mark_seen" src/ main.py` → no output
