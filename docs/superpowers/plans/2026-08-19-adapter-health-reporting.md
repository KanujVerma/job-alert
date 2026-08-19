# Adapter Health Reporting Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Notify Discord once when a company stops returning any job postings for 24 hours, so a permanently dead adapter stops being invisible.

**Architecture:** A new pure module `src/health.py` owns all the state-transition logic and returns a string verdict; `main.py` calls it once per company inside the existing scrape loop and sends the corresponding Discord summary. Health data is stored additively under each company in `state/seen_jobs.json` with no schema version bump.

**Tech Stack:** Python 3.12, pytest, stdlib `datetime`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-19-adapter-health-reporting-design.md`

## Global Constraints

- Health is measured on `fetched` (pre-filter count), never `matched`. A healthy adapter routinely returns postings that all fail the filters; that must stay silent.
- All timestamps are timezone-aware UTC ISO8601 strings. Existing storage helpers raise `ValueError` on naive datetimes; follow that convention.
- `state/seen_jobs.json` stays at `"version": 2`. Health fields are additive via `setdefault`.
- `update_health` must not send anything, read the clock, or touch the network. `now` is always a parameter.
- Health notices use `Notifier.send_summary(title, description) -> bool`, never `send_job_alert`, so they cannot consume the `max_alerts_per_run` budget.
- Default threshold: `adapter_stale_after_hours: 24`.
- Run tests with `./.venv/bin/python -m pytest`. Baseline before this plan: **397 passed**.

---

## File map

| File | Change |
|---|---|
| `src/health.py` | Create. `update_health()` and the `HEALTH_*` constants. |
| `tests/test_health.py` | Create. Pure unit tests for every transition. |
| `main.py` | Modify `do_run`: call `update_health` after fetch, send notice on verdict. |
| `tests/test_main_exit_code.py` | Extend with health-notification integration tests. |
| `companies.yaml` | Add `defaults.adapter_stale_after_hours: 24`. |

---

## Task 1: `update_health` core transitions

**Files:**
- Create: `src/health.py`
- Test: `tests/test_health.py`

**Interfaces:**
- Consumes: nothing from earlier tasks.
- Produces: `update_health(company_state: dict, fetched_count: int, now: datetime, stale_after_hours: float) -> str | None`, returning `"stale"`, `"recovered"`, or `None`. Also `HEALTH_STALE = "stale"` and `HEALTH_RECOVERED = "recovered"`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_health.py`:

```python
"""Tests for adapter health transitions in src/health.py.

Time is a parameter, never a mock: every case pins an exact instant so the
threshold boundary is testable without sleeping or patching the clock.
"""
from __future__ import annotations
from datetime import datetime, timedelta, timezone

from src.health import update_health, HEALTH_STALE, HEALTH_RECOVERED

_T0 = datetime(2026, 8, 19, 12, 0, 0, tzinfo=timezone.utc)
_STALE_AFTER = 24.0


def at(hours: float) -> datetime:
    return _T0 + timedelta(hours=hours)


class TestFirstSighting:
    def test_first_call_stamps_first_tracked_at(self):
        cs = {}
        assert update_health(cs, 0, _T0, _STALE_AFTER) is None
        assert cs["health"]["first_tracked_at"] == _T0.isoformat()

    def test_nonempty_fetch_stamps_last_nonempty_at(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert cs["health"]["last_nonempty_at"] == _T0.isoformat()


class TestGoingStale:
    def test_no_verdict_before_threshold(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(23), _STALE_AFTER) is None

    def test_stale_once_threshold_crossed(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE

    def test_stale_is_edge_triggered_not_repeated(self):
        """The whole point of alerted: a company broken for a week pings once."""
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE
        assert update_health(cs, 0, at(26), _STALE_AFTER) is None
        assert update_health(cs, 0, at(200), _STALE_AFTER) is None

    def test_never_nonempty_goes_stale_against_first_tracked_at(self):
        """microsoft_research has no healthy baseline; without this it never flags."""
        cs = {}
        update_health(cs, 0, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(25), _STALE_AFTER) == HEALTH_STALE


class TestRecovery:
    def test_recovered_when_flagged_company_returns_postings(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        update_health(cs, 0, at(25), _STALE_AFTER)
        assert update_health(cs, 3, at(26), _STALE_AFTER) == HEALTH_RECOVERED
        assert cs["health"]["alerted"] is False

    def test_no_recovery_verdict_if_never_flagged(self):
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 3, at(1), _STALE_AFTER) is None


class TestBoundary:
    def test_exactly_at_threshold_is_not_yet_stale(self):
        """Strictly greater-than, so the boundary is unambiguous."""
        cs = {}
        update_health(cs, 5, _T0, _STALE_AFTER)
        assert update_health(cs, 0, at(24), _STALE_AFTER) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_health.py -v`
Expected: collection error — `ModuleNotFoundError: No module named 'src.health'`.

- [ ] **Step 3: Write the minimal implementation**

Create `src/health.py`:

```python
"""Per-company adapter health, so a permanently dead adapter stops being invisible.

Pure and clock-free: `now` is always a parameter and nothing here sends, logs, or
persists. main.py owns the side effects.
"""
from __future__ import annotations
from datetime import datetime, timedelta

HEALTH_STALE = "stale"
HEALTH_RECOVERED = "recovered"


def update_health(
    company_state: dict,
    fetched_count: int,
    now: datetime,
    stale_after_hours: float,
) -> str | None:
    """Record this run's fetch outcome and report any health transition.

    Returns "stale" the first run a company crosses the silence threshold,
    "recovered" the first run it produces postings again after being flagged,
    and None otherwise. Mutates company_state["health"] in place.

    fetched_count is the PRE-FILTER count. A healthy adapter routinely returns
    postings that all fail the filters; only an empty fetch means the site gave
    us nothing.
    """
    if now.tzinfo is None:
        raise ValueError("update_health: 'now' must be tz-aware")

    health = company_state.setdefault(
        "health",
        {"first_tracked_at": now.isoformat(), "last_nonempty_at": None, "alerted": False},
    )
    health.setdefault("first_tracked_at", now.isoformat())
    health.setdefault("last_nonempty_at", None)
    health.setdefault("alerted", False)

    if fetched_count > 0:
        health["last_nonempty_at"] = now.isoformat()
        if health["alerted"]:
            health["alerted"] = False
            return HEALTH_RECOVERED
        return None

    if health["alerted"]:
        return None

    # A company that has never been seen non-empty has no healthy baseline to
    # have fallen from, so measure from when we started watching it instead.
    reference = health["last_nonempty_at"] or health["first_tracked_at"]
    if now - datetime.fromisoformat(reference) > timedelta(hours=stale_after_hours):
        health["alerted"] = True
        return HEALTH_STALE

    return None
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_health.py -v`
Expected: 9 passed.

- [ ] **Step 5: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: 406 passed (397 baseline + 9 new).

- [ ] **Step 6: Commit**

```bash
git add src/health.py tests/test_health.py
git commit -m "feat(health): track per-company adapter staleness

Pure transition logic for detecting a company that has stopped returning
postings. Measures fetched (pre-filter) count, because a healthy adapter
routinely returns postings that all fail the filters.

Companies never seen non-empty fall back to first_tracked_at, which is the
case that matters: microsoft_research has no healthy baseline to have fallen
from, so a design keyed only on last_nonempty_at would never flag it."
```

---

## Task 2: Wire health notices into the run

**Files:**
- Modify: `main.py` (imports; inside the company loop after the fetch block at `main.py:152-158`; config read near `main.py:120`)
- Modify: `tests/test_main_exit_code.py`
- Modify: `companies.yaml` (`defaults` block, after `first_seen_ttl_days`)

**Interfaces:**
- Consumes: `update_health`, `HEALTH_STALE`, `HEALTH_RECOVERED` from `src/health.py` (Task 1).
- Produces: nothing later tasks depend on.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_main_exit_code.py`:

```python
class TestHealthNotifications:
    """A dead adapter must announce itself exactly once, on the channel that is read."""

    def _run_with_notifier(self, config, registry, notifier, state):
        args = types.SimpleNamespace(
            config="unused.yaml", company=None, dry_run=False,
            verbose=False, firehose_first_run=False, summary_first_run=False,
        )
        with patch.object(m, "load_config", return_value=config), \
             patch.dict(m.ADAPTER_REGISTRY, registry, clear=True), \
             patch.object(m, "Notifier", return_value=notifier), \
             patch.object(m, "load_state", return_value=state), \
             patch.object(m, "save_state"), \
             patch.dict(m.os.environ, {"DISCORD_WEBHOOK_URL": "https://example.com/hook"}):
            return m.do_run(args)

    def _stale_state(self):
        """A company last seen non-empty two days ago — well past the 24h threshold."""
        long_ago = (datetime.now(timezone.utc) - timedelta(days=2)).isoformat()
        return {
            "version": 2,
            "first_run_completed_at": long_ago,
            "companies": {
                "Acme": {
                    "last_checked_at": long_ago,
                    "seen_jobs": {},
                    "health": {
                        "first_tracked_at": long_ago,
                        "last_nonempty_at": long_ago,
                        "alerted": False,
                    },
                }
            },
        }

    def test_dead_company_sends_one_health_notice(self):
        notifier = MagicMock()
        notifier.send_summary.return_value = True
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": EmptyAdapter}, notifier, state
        )

        assert notifier.send_summary.call_count == 1
        assert state["companies"]["Acme"]["health"]["alerted"] is True

    def test_alerted_not_set_when_discord_send_fails(self):
        """Otherwise a failed post silently burns the single notice you get."""
        notifier = MagicMock()
        notifier.send_summary.return_value = False
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": EmptyAdapter}, notifier, state
        )

        assert state["companies"]["Acme"]["health"]["alerted"] is False

    def test_healthy_company_sends_no_health_notice(self):
        notifier = MagicMock()
        notifier.send_summary.return_value = True
        state = self._stale_state()

        self._run_with_notifier(
            make_config("Acme"), {"stub": HealthyAdapter}, notifier, state
        )

        assert notifier.send_summary.call_count == 0
```

Add to the imports at the top of `tests/test_main_exit_code.py`:

```python
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch
```

Add this adapter beside the existing `EmptyAdapter`:

```python
class HealthyAdapter:
    """Returns postings, so health stays green. Filters may still drop them all."""

    def __init__(self, name, cfg, http, browser=None):
        self.name = name

    def fetch(self):
        return [_make_job()]
```

**This job is deliberately filtered out.** Verified against the real pipeline: with
the sparse `filters={"freshness_hours": 48}` in `make_config`, `apply_filter_pipeline`
rejects it with `tech_role: no technical role signal`, so `matched` is empty while
`fetched` is 1. `test_healthy_company_sends_no_health_notice` therefore proves the
property the whole design rests on — health tracks `fetched`, not `matched`.

Do **not** "fix" this by adding `technical_role_keywords` to `make_config`. That
would make the test pass for the wrong reason and stop it catching a regression to
the `matched` count.

And a job factory, since `do_run` will run these through the filter pipeline:

```python
from src.models import Job


def _make_job() -> Job:
    now = datetime.now(timezone.utc)
    return Job(
        id="health-test-1", company="Acme", title="Software Engineering Intern",
        location="Remote", department="Engineering", category="Software",
        url="https://example.com/1", source_platform="stub", posted_at=None,
        detected_at=now, raw_text="software engineering intern",
        role_type="internship", priority="preferred",
        matched_keywords=("intern",),
    )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `./.venv/bin/python -m pytest tests/test_main_exit_code.py -v -k Health`
Expected: FAIL — `assert 0 == 1` on `send_summary.call_count`, because `do_run` does not yet consult health.

- [ ] **Step 3: Add the config default**

In `companies.yaml`, under `defaults:`, directly after `first_seen_ttl_days: 180`:

```yaml
  # How long a company may return zero postings before the bot reports it as dead.
  # A patience window, not a schedule — the cron cadence is unchanged. Any single
  # empty fetch has boring explanations; requiring it to persist is what separates
  # "quiet" from "broken".
  adapter_stale_after_hours: 24
```

- [ ] **Step 4: Write the minimal implementation**

In `main.py`, add to the imports beside the other `src` imports:

```python
from src.health import update_health, HEALTH_STALE, HEALTH_RECOVERED
```

Near the other config reads (beside `max_alerts = config.defaults.get(...)`, around `main.py:120`):

```python
stale_after_hours = float(config.defaults.get("adapter_stale_after_hours", 24))
```

Then in the company loop, immediately after the `try/except` fetch block (after the
`logger.error(f"{cname}: fetch failed: ...")` line, around `main.py:158`):

```python
            # Adapter health. Deliberately keyed on the pre-filter count: a healthy
            # adapter routinely returns postings that all fail the filters, and that
            # must stay silent. An adapter that raises leaves fetched empty too, so
            # this one signal covers both a crashing adapter and a silently-empty one.
            company_state = state["companies"].setdefault(
                cname, {"last_checked_at": None, "seen_jobs": {}}
            )
            verdict = update_health(
                company_state, len(fetched), datetime.now(timezone.utc), stale_after_hours
            )
            if verdict and notifier and not getattr(args, "dry_run", False):
                if verdict == HEALTH_STALE:
                    sent = notifier.send_summary(
                        title="🔕 Adapter looks dead",
                        description=(
                            f"**{cname}** has returned no postings for over "
                            f"{stale_after_hours:.0f}h. The adapter is probably broken."
                        ),
                    )
                    # Only keep the flag if the notice actually landed, so a failed
                    # send retries next run instead of burning the single alert.
                    if not sent:
                        company_state["health"]["alerted"] = False
                elif verdict == HEALTH_RECOVERED:
                    notifier.send_summary(
                        title="✅ Adapter recovered",
                        description=f"**{cname}** is returning postings again.",
                    )
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `./.venv/bin/python -m pytest tests/test_main_exit_code.py -v -k Health`
Expected: 3 passed.

- [ ] **Step 6: Run the full suite**

Run: `./.venv/bin/python -m pytest -q`
Expected: 409 passed (406 after Task 1 + 3 new).

- [ ] **Step 7: Verify against the real config**

Run: `./.venv/bin/python main.py run --dry-run --verbose 2>&1 | tail -20`
Expected: exit 0. `Microsoft Research` shows `fetched=0`; every other enabled company
shows `fetched>0`. No Discord posts (dry-run suppresses them).

- [ ] **Step 8: Commit**

```bash
git add main.py tests/test_main_exit_code.py companies.yaml
git commit -m "feat(run): report dead adapters to Discord

A single adapter can die permanently and nothing reports it: the exit-code
backstop fires only when nothing worked, so one dead adapter among twelve
healthy ones stays invisible.

Reports to Discord rather than CI on purpose. The workflow runs 96 times a
day; turning it red on a dead adapter produces 96 failure emails from one
broken site, which gets muted inside a week and takes the total-outage
signal down with it.

Edge-triggered, so a company broken for a week pings once. The flag is only
kept if the send succeeded."
```

---

## Task 3: Confirm the dead adapter is actually reported

**Files:**
- No production changes. This task is verification only.

**Interfaces:**
- Consumes: everything from Tasks 1 and 2.
- Produces: nothing.

This exists as its own task because the feature's entire purpose is catching a case
that unit tests can only simulate. A green suite does not prove the notice fires
against real state and a really-broken adapter.

- [ ] **Step 1: Confirm the state file has no health data yet**

Run: `./.venv/bin/python -c "import json; d=json.load(open('state/seen_jobs.json')); print({k: 'health' in v for k, v in d['companies'].items()})"`
Expected: all `False` before the first real run.

- [ ] **Step 2: Push and let one scheduled run populate health**

```bash
git push origin main
```

Wait for one scheduled run to complete, then:

```bash
git pull --rebase origin main
./.venv/bin/python -c "import json; d=json.load(open('state/seen_jobs.json')); print(json.dumps({k: v.get('health') for k, v in d['companies'].items()}, indent=2))"
```

Expected: every enabled company now has a `health` block. `Microsoft Research` has
`last_nonempty_at: null`; the others have a timestamp. No company is `alerted` yet —
`first_tracked_at` is only minutes old.

- [ ] **Step 3: Confirm the notice fires 24h later**

Roughly 24h after the first run carrying this code, check Discord for a single
"🔕 Adapter looks dead" notice naming Microsoft Research, and confirm it does not
repeat on subsequent runs:

```bash
git pull --rebase origin main
./.venv/bin/python -c "import json; d=json.load(open('state/seen_jobs.json')); print(d['companies']['Microsoft Research']['health'])"
```

Expected: `alerted: True`, and exactly one Discord message.

If the notice does not appear, do not patch symptomatically — the transition logic is
pure and directly testable, so reproduce the failing state in `tests/test_health.py`
first.

---

## Notes for the executor

- **Do not "fix" `microsoft_research` while you are in here.** It is deliberately out
  of scope and sequenced after this work, so that there is a way to tell whether a fix
  worked. The repo already has an `eightfold_playwright` adapter for the SPA case.
- **Do not make health failures fail the run.** The exit-code backstop in `do_run` is
  for total outage only. Widening it re-creates the 96-emails-a-day problem this design
  exists to avoid.
- **Do not switch health to the `matched` count.** It looks more meaningful and is
  wrong: filters legitimately reject every posting a healthy site returns.
