# Adapter Health Reporting — Design Spec

**Date:** 2026-08-19
**Status:** Approved
**Files affected:** `src/health.py` (new), `main.py`, `companies.yaml`, `tests/test_health.py` (new)

---

## Problem

A single adapter can die permanently without anything reporting it.

`microsoft_research` has returned zero jobs on **every** run for as far back as the
available logs go: the Eightfold API answers 403, the HTML fallback lands on a
JS-rendered SPA with no static job data, and the adapter returns `[]`. Its own
docstring states the design intent outright — *"The adapter logs a warning and
returns []. It NEVER raises."* Because it never raises, every layer above it sees
a successful company.

The `2026-08-19` exit-code backstop (`main.py`, "fail the run when no company could
be scraped") does not catch this and was never meant to: it fires only when *nothing*
worked. One dead adapter among twelve healthy ones is invisible to it — a boundary
pinned deliberately by `test_adapter_returning_empty_still_counts_as_success`.

So the gap is real and currently live: a company can silently stop producing alerts
and the only symptom is alerts you never receive, which is precisely the symptom
nobody notices.

## Why this reports to Discord and not to CI

The workflow runs every 15 minutes — 96 runs a day. Turning the run red on a dead
adapter means 96 failure emails a day from one broken site. That gets muted inside a
week, and once muted the CI signal is worth nothing, including for the total-outage
case the exit-code backstop covers.

Discord is the channel that is already read, already rate-limit-aware
(`src/notifier.py` handles 429 with `Retry-After` and a token bucket), and already
where every other thing this bot wants to tell you arrives.

---

## Design

### 1. Signal: baseline-relative, per company

A fixed "zero jobs means broken" rule does not work, because query breadth varies by
adapter:

| Adapter | Query | Zero fetched means |
|---|---|---|
| `workday` | `searchText: ""`, no facets — all tenant postings | unambiguously broken |
| `microsoft_research` | `q=research+intern` | possibly legitimate |

The robust signal is comparative rather than absolute: **this company used to return
postings and has stopped.** That self-calibrates per adapter regardless of how narrow
its query is.

Health lives per company inside `state/seen_jobs.json`, beside the existing
`last_checked_at` and `seen_jobs`:

```json
"Microsoft Research": {
  "last_checked_at": "...",
  "seen_jobs": { },
  "health": {
    "first_tracked_at": "2026-08-19T20:00:00+00:00",
    "last_nonempty_at": null,
    "alerted": false
  }
}
```

**Count `fetched`, not `matched`.** `fetched` is the pre-filter count — what the site
actually returned. A healthy adapter routinely returns 50 postings of which 0 survive
the internship/tech filters; that is normal and must stay silent. Only `fetched == 0`
indicates the site gave us nothing.

**One signal covers both failure modes.** When an adapter raises, `main.py` leaves
`fetched = []`. So a crashing adapter and a silently-empty one produce the same
observable, and no separate error-streak tracking is needed.

### 2. Reference point, including the no-baseline case

Staleness is measured against `last_nonempty_at`. A company that has **never** been
seen non-empty has no such baseline, and falls back to `first_tracked_at`.

This case is not hypothetical — it is the one that matters. `microsoft_research` has
no healthy history to have fallen from, so a design keyed only on `last_nonempty_at`
would never flag it. With the fallback it flags one day after this ships.

### 3. Trigger: edge, not level

When `now - reference > adapter_stale_after_hours` and `alerted` is false: send one
Discord notice and set `alerted = true`. It does not repeat while the company stays
broken.

`alerted` is set **only if the Discord send succeeded**. A failed post retries on the
next run rather than silently consuming the single notice.

Recovery: a non-empty fetch while `alerted` is true sends a short "recovered" notice
and clears the flag.

Health notices go through `Notifier.send_summary`, which is separate from
`send_job_alert` and does not touch `alert_count`, so they cannot consume the
`max_alerts_per_run` job budget.

### 4. Threshold: 24 hours, configurable

`defaults.adapter_stale_after_hours: 24` in `companies.yaml`.

24h is ~96 consecutive empty runs before a company is called dead. This is a patience
window, not a schedule — the cron cadence is unchanged at 15 minutes. The window
exists because any single empty fetch has boring explanations (site maintenance, a
blipped request, a narrow query with nothing to return today); requiring the emptiness
to persist is what separates "quiet" from "broken."

24h was chosen over 6h deliberately. The cost of the longer window is up to a day's
delay learning an adapter died; given the current dead adapter has gone unnoticed for
weeks, a day is cheap, and the false-alarm risk at 6h is real for narrow-query
adapters like `microsoft_research`.

### 5. Schema: additive, no version bump

Health fields are introduced with `setdefault`; absent means unknown. The existing
v1→v2 migration exists because that change was breaking (`seen_ids` list →
`seen_jobs` dict). This one is not, so `version` stays at 2 and old state files
remain readable.

### 6. Structure

Pure logic goes in a new `src/health.py`, keeping `main.py`'s already-long `do_run`
thin and making the logic testable without network, clock, or Discord:

```python
def update_health(
    company_state: dict, fetched_count: int, now: datetime, stale_after_hours: float
) -> str | None:
    """Returns "stale", "recovered", or None. Mutates company_state["health"]."""
```

`do_run` calls it and sends the corresponding notice. `update_health` never sends
anything itself.

---

## Testing

New `tests/test_health.py`, pure and time-injected (no mocks of the clock, `now` is a
parameter):

- first sighting stamps `first_tracked_at`
- non-empty fetch stamps `last_nonempty_at`
- no transition before the threshold
- `"stale"` once the threshold is crossed
- edge-trigger: a second stale run returns `None`, not `"stale"` again
- never-non-empty company goes stale against `first_tracked_at`
- `"recovered"` when a flagged company returns postings, and `alerted` clears
- exactly-at-threshold boundary

Plus, in `main.py`'s existing test surface: a dead company triggers exactly one
`send_summary`, and `alerted` is not set when the send fails.

## Out of scope

Fixing `microsoft_research` itself. It is a separate question — the repo already has
an `eightfold_playwright` adapter built for the SPA case, so it may be a config
change rather than new code. Deliberately sequenced after this work so that there is
a way to tell whether a fix worked.
