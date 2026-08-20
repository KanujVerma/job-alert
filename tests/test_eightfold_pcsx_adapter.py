"""Tests for EightfoldPCSXAdapter — the Eightfold "PCSX" search API.

Endpoint (verified live 2026-08-20, Microsoft):
    GET https://apply.careers.microsoft.com/api/pcsx/search
        ?domain=microsoft.com&query=&location=United%20States&start=0&sort_by=timestamp

Plain HTTP, no auth, no cookies, any User-Agent. robots.txt at that host is
`Disallow: /` with an explicit `Allow: /api/pcsx`, so this path is permitted.

The fixture is four postings captured verbatim from that endpoint on 2026-08-20.
Only the envelope was trimmed: `data.filterDef` (the bulk of the 21KB response)
and the `metadata`/`debug`/`resultsMetaData` blocks were dropped because the
adapter reads none of them. Every field the adapter DOES read is untouched.
The four were chosen because they differ where it matters:
    - "AI Software Engineering Intern"           — two locations, an internship
    - "Principal Software Engineer - AI Experiences" — two locations, senior
    - "Program Manager"                          — one location
    - "Strategic Operations Director"            — "Multiple Locations" placeholder

The adapter NEVER raises; every failure path yields nothing and logs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import MagicMock

import requests

from src.adapters.eightfold_pcsx import (
    MAX_PAGES,
    PAGE_SIZE,
    EightfoldPCSXAdapter,
)
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "eightfold_pcsx_microsoft.json"


def test_source_platform_constant():
    assert EightfoldPCSXAdapter.source_platform == "eightfold_pcsx"


_CONFIG = {
    "base_url": "https://apply.careers.microsoft.com",
    "domain": "microsoft.com",
    "location": "United States",
}


def _make_adapter(config: dict | None = None) -> EightfoldPCSXAdapter:
    http = MagicMock(spec=HTTPClient)
    return EightfoldPCSXAdapter(
        company="Microsoft",
        config=dict(_CONFIG if config is None else config),
        http=http,
    )


def _mock_response(payload: object) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _positions() -> list[dict]:
    return _fixture()["data"]["positions"]


def _envelope(positions: list, count: int | None = None) -> dict:
    """The real response envelope with a chosen `positions` slice."""
    return {
        "status": 200,
        "error": {"message": "", "body": ""},
        "data": {
            "positions": positions,
            "count": 1140 if count is None else count,
            "sortBy": "timestamp",
        },
    }


def _fetch_one_page() -> list[Job]:
    """One page of the fixture. `count` matches the slice so paging stops."""
    adapter = _make_adapter()
    positions = _positions()
    adapter.http.get.return_value = _mock_response(_envelope(positions, len(positions)))
    return list(adapter.fetch())


def _by_title(jobs: list[Job], fragment: str) -> Job:
    matches = [j for j in jobs if fragment in j.title]
    assert len(matches) == 1, f"expected exactly one job matching {fragment!r}"
    return matches[0]


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_yields_every_position_in_the_payload():
    assert len(_fetch_one_page()) == 4


def test_title_comes_from_name():
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.title == "AI Software Engineering Intern"


def test_relative_position_url_is_made_absolute():
    """`positionUrl` is relative ("/careers/job/..."). Yielding it as-is puts a
    bare path into a Discord embed, which is not a link anyone can open."""
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.url == (
        "https://apply.careers.microsoft.com/careers/job/1970393556962891"
    )


def test_official_id_is_used_for_the_job_id():
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.id == "Microsoft::eightfold_pcsx::1970393556962891"


def test_location_joins_every_entry_with_a_semicolon():
    """`locations` is an array. filter_location judges ";"-separated locations
    independently, so joining that way keeps each address judged on its own."""
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.location == (
        "United States, Washington, Redmond; United States, California, Mountain View"
    )


def test_posted_at_is_parsed_from_epoch_seconds():
    """`postedTs` is Unix epoch SECONDS, not milliseconds and not ISO-8601."""
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.posted_at == datetime(2026, 8, 19, 7, 0, 0, tzinfo=timezone.utc)


def test_posted_at_is_timezone_aware():
    """A naive posted_at would abort the ENTIRE run, not just this adapter.

    filter_freshness subtracts it from an aware now(), raising TypeError, and
    main.py runs the filter pipeline outside any try/except — so one naive
    timestamp kills every company after it and state is never saved.
    """
    for job in _fetch_one_page():
        assert job.posted_at is not None
        assert job.posted_at.tzinfo is not None
        assert job.posted_at.utcoffset() is not None


def test_department_is_carried_through():
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.department == "Software Engineering"


def test_company_and_platform_are_passed_through():
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert job.company == "Microsoft"
    assert job.source_platform == "eightfold_pcsx"


def test_role_type_is_not_guessed():
    """The search response says nothing about role type. base.py asks adapters to
    hint only when the SOURCE knows; here it does not, so the keyword filters
    decide from the title instead of the adapter inventing a label."""
    for job in _fetch_one_page():
        assert job.role_type == "unknown"


# ---------------------------------------------------------------------------
# raw_text — what the filter pipeline actually reads
# ---------------------------------------------------------------------------

def test_raw_text_is_title_location_and_department():
    """The search response carries no description, and the brief is explicit that
    no per-job detail request may be added to get one."""
    job = _by_title(_fetch_one_page(), "AI Software Engineering Intern")
    assert "ai software engineering intern" in job.raw_text
    assert "mountain view" in job.raw_text
    assert "software engineering" in job.raw_text


def test_raw_text_is_lowercased():
    for job in _fetch_one_page():
        assert job.raw_text == job.raw_text.lower()


# ---------------------------------------------------------------------------
# The request itself
# ---------------------------------------------------------------------------

def test_requests_the_pcsx_search_path():
    """`robots.txt` allows /api/pcsx specifically. Any other path on this host is
    `Disallow: /`, so the path is a politeness constraint, not a detail."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_envelope(_positions(), 4))

    list(adapter.fetch())

    assert adapter.http.get.call_args.args[0] == (
        "https://apply.careers.microsoft.com/api/pcsx/search"
    )


def test_sorts_by_timestamp_because_the_early_stop_depends_on_it():
    """sort_by=timestamp is what makes postedTs descending. Without it the
    "stop once the page falls out of the window" rule is simply wrong."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_envelope(_positions(), 4))

    list(adapter.fetch())

    assert adapter.http.get.call_args.kwargs["params"]["sort_by"] == "timestamp"


def test_query_is_empty_so_the_result_is_the_whole_company():
    """A narrow server-side query makes fetched==0 ambiguous — "nothing matched
    today" or "the adapter is broken" — and src/health.py depends on that
    distinction. The bot's own filter pipeline does the selecting."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_envelope(_positions(), 4))

    params = None
    list(adapter.fetch())
    params = adapter.http.get.call_args.kwargs["params"]

    assert params["query"] == ""
    assert params["domain"] == "microsoft.com"
    assert params["location"] == "United States"


def test_domain_is_derived_from_base_url_when_not_configured():
    adapter = _make_adapter({
        "base_url": "https://apply.careers.microsoft.com",
        "location": "United States",
    })
    adapter.http.get.return_value = _mock_response(_envelope(_positions(), 4))

    list(adapter.fetch())

    assert adapter.http.get.call_args.kwargs["params"]["domain"] == (
        "apply.careers.microsoft.com"
    )


# ---------------------------------------------------------------------------
# Pagination and the date-based early stop
# ---------------------------------------------------------------------------

def _pos(n: int, hours_ago: float) -> dict:
    """A real-shaped position posted `hours_ago` before now."""
    ts = int((datetime.now(timezone.utc) - timedelta(hours=hours_ago)).timestamp())
    job_id = 1970393556900000 + n
    return {
        "id": job_id,
        "displayJobId": str(200000000 + n),
        "name": f"Software Engineer {n}",
        "locations": ["United States, Washington, Redmond"],
        "standardizedLocations": ["Redmond, WA, US"],
        "postedTs": ts,
        "department": "Software Engineering",
        "positionUrl": f"/careers/job/{job_id}",
    }


def _full_page(page_index: int, hours_ago: float) -> MagicMock:
    """A full page (the API's hard-fixed 10) of postings all this old."""
    first = page_index * PAGE_SIZE
    return _mock_response(
        _envelope([_pos(first + i, hours_ago) for i in range(PAGE_SIZE)])
    )


def test_pages_with_start_in_steps_of_ten():
    """`num`/`limit`/`page_size` are accepted and ignored — page size is hard-fixed
    at 10 server-side, so `start` is the only paging control that works."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = [
        _full_page(0, 1), _full_page(1, 2), _full_page(2, 500),
    ]

    jobs = list(adapter.fetch())

    assert adapter.http.get.call_count == 3
    starts = [c.kwargs["params"]["start"] for c in adapter.http.get.call_args_list]
    assert starts == [0, 10, 20]
    assert len(jobs) == 30


def test_stops_paging_once_a_page_falls_outside_the_window():
    """The cheap half of the design: 48h is a handful of pages, the full corpus
    is 114 requests against an API that 429s after ~5 rapid ones."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = [_full_page(0, 1), _full_page(1, 500)]

    list(adapter.fetch())

    assert adapter.http.get.call_count == 2


def test_page_zero_is_read_whole_even_when_every_posting_is_stale():
    """THE health-monitor guarantee, and the subtle half of the design.

    main.py feeds the PRE-FILTER fetched count into src/health.py, which reports
    a company as broken when it fetches zero. An early stop that skipped page 0
    on date would make a genuinely quiet day indistinguishable from a dead
    adapter, and the monitor would cry wolf. Reading page 0 unconditionally
    guarantees fetched >= 1 whenever the API is healthy, so zero still means
    broken. The freshness filter downstream drops the stale ones.
    """
    adapter = _make_adapter()
    adapter.http.get.return_value = _full_page(0, 500)

    jobs = list(adapter.fetch())

    assert len(jobs) == 10, "page 0 must be yielded whole regardless of timestamps"
    assert adapter.http.get.call_count == 1, "but must not page past a stale page 0"


def test_the_window_is_configurable():
    adapter = _make_adapter({**_CONFIG, "stop_after_hours": 200})
    adapter.http.get.side_effect = [_full_page(0, 100), _full_page(1, 500)]

    list(adapter.fetch())

    assert adapter.http.get.call_count == 2, "100h old is inside a 200h window"


def test_stops_when_the_result_set_is_exhausted():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        _envelope([_pos(0, 1), _pos(1, 1)], count=2)
    )

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    assert adapter.http.get.call_count == 1


def test_a_short_page_ends_the_paging():
    """Fewer than a full page means the server has nothing more, whatever `count`
    claims — trusting count alone would page forever against a wrong count."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        _envelope([_pos(0, 1), _pos(1, 1)], count=1140)
    )

    list(adapter.fetch())

    assert adapter.http.get.call_count == 1


def test_polite_delay_of_three_to_five_seconds_between_pages():
    """Rate limiting is real and gives NO Retry-After: the API returns 429 after
    roughly 5 rapid requests. 3s spacing was stable."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = [_full_page(0, 1), _full_page(1, 500)]

    list(adapter.fetch())

    assert adapter.http.polite_delay.call_count == 1, "one gap between two pages"
    assert adapter.http.polite_delay.call_args.args == (3.0, 5.0)


def test_pagination_is_capped_against_a_runaway():
    adapter = _make_adapter()
    adapter.http.get.side_effect = lambda *a, **k: _full_page(
        k["params"]["start"] // PAGE_SIZE, 1
    )

    jobs = list(adapter.fetch())

    assert adapter.http.get.call_count == MAX_PAGES
    assert len(jobs) == MAX_PAGES * PAGE_SIZE


def test_hitting_the_page_cap_is_logged_not_silent(caplog):
    """Truncating at the cap must say so. A silent stop reads as "we got
    everything", which is the failure mode this bot exists to avoid."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = lambda *a, **k: _full_page(
        k["params"]["start"] // PAGE_SIZE, 1
    )

    with caplog.at_level(logging.WARNING):
        list(adapter.fetch())

    assert "cap" in caplog.text.lower()
    assert str(MAX_PAGES) in caplog.text


# ---------------------------------------------------------------------------
# Deduplication and unusable postings
# ---------------------------------------------------------------------------

def test_the_same_posting_is_never_yielded_twice():
    """One posting must become one Discord alert.

    Nothing downstream deduplicates within a run, so if the API ever ignores or
    clamps `start`, repeated postings become repeated embeds for one job.
    """
    adapter = _make_adapter()
    adapter.http.get.return_value = _full_page(0, 1)  # every page identical

    jobs = list(adapter.fetch())

    assert adapter.http.get.call_count == MAX_PAGES, "the API ignored `start`"
    assert len(jobs) == PAGE_SIZE, f"yielded {len(jobs)} copies of {PAGE_SIZE} postings"
    assert len({j.id for j in jobs}) == len(jobs)


def test_posting_without_an_apply_url_is_skipped():
    """notifier.py puts job.url straight into a Discord embed field value, and
    Discord rejects an empty value with HTTP 400. The send fails, mark_alerted
    never runs, and the posting retries every run until it ages out of the
    freshness window. A posting with no link cannot be applied to anyway."""
    adapter = _make_adapter()
    broken = _pos(0, 1)
    broken["name"] = "No Link Here"
    broken["positionUrl"] = ""
    adapter.http.get.return_value = _mock_response(
        _envelope([broken, _pos(1, 1)], count=2)
    )

    jobs = list(adapter.fetch())

    assert "No Link Here" not in [j.title for j in jobs]
    assert all(j.url for j in jobs)


def test_posting_without_a_name_is_skipped_not_fatal():
    adapter = _make_adapter()
    nameless = _pos(0, 1)
    nameless["name"] = ""
    adapter.http.get.return_value = _mock_response(
        _envelope([nameless, _pos(1, 1)], count=2)
    )

    jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert all(job.title for job in jobs)


# ---------------------------------------------------------------------------
# Failure paths — the adapter NEVER raises
#
# fetch() is a generator, so an exception surfaces on CONSUMPTION, inside
# main.py's list(adapter.fetch()). That discards every posting already yielded
# and records the company as fetched=0 — making a healthy adapter look dead to
# the health tracking. Every path below must degrade instead.
# ---------------------------------------------------------------------------

def test_http_error_yields_nothing():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.HTTPError("429 Too Many Requests")

    assert list(adapter.fetch()) == []


def test_network_error_yields_nothing():
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.ConnectionError("DNS failure")

    assert list(adapter.fetch()) == []


def test_malformed_json_yields_nothing():
    adapter = _make_adapter()
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.side_effect = ValueError("not json")
    adapter.http.get.return_value = resp

    assert list(adapter.fetch()) == []


def test_a_non_dict_payload_yields_nothing():
    for bad in ([], "nope", 7, None):
        adapter = _make_adapter()
        adapter.http.get.return_value = _mock_response(bad)

        assert list(adapter.fetch()) == [], f"payload={bad!r} raised or yielded"


def test_a_non_dict_data_block_yields_nothing():
    for bad in (None, [], "nope", 200):
        adapter = _make_adapter()
        adapter.http.get.return_value = _mock_response({"status": 200, "data": bad})

        assert list(adapter.fetch()) == [], f"data={bad!r} raised or yielded"


def test_missing_or_non_list_positions_yields_nothing():
    for bad in (None, {}, "nope", 0):
        adapter = _make_adapter()
        adapter.http.get.return_value = _mock_response(
            {"status": 200, "data": {"positions": bad, "count": 1140}}
        )

        assert list(adapter.fetch()) == [], f"positions={bad!r} raised or yielded"


def test_the_integer_status_field_is_not_read_as_a_failure_flag():
    """payload["status"] is the INTEGER 200 on success. The older eightfold.py
    route bails on a "failure" string; copying that check here and comparing an
    int would throw away every healthy response."""
    adapter = _make_adapter()
    payload = _envelope([_pos(0, 1)], count=1)
    payload["status"] = 200

    adapter.http.get.return_value = _mock_response(payload)

    assert len(list(adapter.fetch())) == 1


def test_one_unparseable_position_does_not_lose_the_others():
    """A stray non-dict in `positions` must cost that entry, not the whole page."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(
        _envelope(["not-an-object", _pos(0, 1), _pos(1, 1)], count=3)
    )

    jobs = list(adapter.fetch())

    assert len(jobs) == 2


def test_a_malformed_subfield_degrades_that_field_not_the_posting():
    """`locations` arriving as a bare string rather than a list loses the
    location and nothing else. Dropping a real job over one bad field is the
    worse failure."""
    adapter = _make_adapter()
    broken = _pos(0, 1)
    broken["locations"] = "United States, Washington, Redmond"
    adapter.http.get.return_value = _mock_response(_envelope([broken], count=1))

    jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert jobs[0].location == ""


def test_an_unparseable_timestamp_leaves_posted_at_unset():
    """filter_freshness explicitly allows posted_at=None through rather than
    guessing; what it cannot survive is a naive datetime."""
    adapter = _make_adapter()
    broken = _pos(0, 1)
    broken["postedTs"] = "not-a-timestamp"
    adapter.http.get.return_value = _mock_response(_envelope([broken], count=1))

    jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert jobs[0].posted_at is None


def test_failure_on_a_later_page_keeps_the_earlier_results():
    adapter = _make_adapter()
    adapter.http.get.side_effect = [
        _full_page(0, 1),
        requests.ConnectionError("dropped"),
    ]

    jobs = list(adapter.fetch())

    assert len(jobs) == PAGE_SIZE


def test_a_later_page_of_junk_keeps_the_earlier_results():
    adapter = _make_adapter()
    adapter.http.get.side_effect = [_full_page(0, 1), _mock_response("garbage")]

    jobs = list(adapter.fetch())

    assert len(jobs) == PAGE_SIZE


def test_an_empty_later_page_is_logged(caplog):
    """A short result that looks complete is worse than a loud partial one —
    the same argument the page-cap warning was added for."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = [_full_page(0, 1), _mock_response(_envelope([]))]

    with caplog.at_level(logging.WARNING):
        jobs = list(adapter.fetch())

    assert len(jobs) == PAGE_SIZE
    assert "start=10" in caplog.text


def test_a_page_with_no_usable_timestamp_stops_and_says_so(caplog):
    """The window cannot be evaluated, so paging the whole 1140-posting corpus
    is the wrong default — but a silent stop would look like a complete read."""
    adapter = _make_adapter()
    positions = [_pos(i, 1) for i in range(PAGE_SIZE)]
    for p in positions:
        p["postedTs"] = None

    adapter.http.get.return_value = _mock_response(_envelope(positions))

    with caplog.at_level(logging.WARNING):
        jobs = list(adapter.fetch())

    assert len(jobs) == PAGE_SIZE
    assert adapter.http.get.call_count == 1
    assert "postedts" in caplog.text.lower()


def test_a_junk_window_config_falls_back_to_the_default(caplog):
    adapter = _make_adapter({**_CONFIG, "stop_after_hours": "soon"})
    adapter.http.get.return_value = _mock_response(_envelope([_pos(0, 1)], count=1))

    with caplog.at_level(logging.WARNING):
        jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert "stop_after_hours" in caplog.text


# ---------------------------------------------------------------------------
# Registration and config wiring
# ---------------------------------------------------------------------------

def test_registered_under_its_own_key():
    from src.adapters import ADAPTER_REGISTRY

    assert ADAPTER_REGISTRY["eightfold_pcsx"] is EightfoldPCSXAdapter


def test_does_not_require_a_browser():
    """This is a plain HTTP API. Declaring requires_browser would make the CI
    workflow install Chromium on all 96 daily runs for nothing."""
    assert EightfoldPCSXAdapter.requires_browser is False


def test_microsoft_is_configured_and_enabled():
    import yaml

    config = yaml.safe_load(Path("companies.yaml").read_text())
    by_name = {c["name"]: c for c in config["companies"]}

    microsoft = by_name["Microsoft"]
    assert microsoft["adapter"] == "eightfold_pcsx"
    assert microsoft["enabled"] is True
    assert microsoft["config"]["base_url"] == "https://apply.careers.microsoft.com"


def test_microsoft_research_is_a_separate_untouched_entry():
    """Microsoft Research is covered by its own WordPress adapter. Two entries,
    two sources, no overlap — MSR postings do not appear in the PCSX search."""
    import yaml

    config = yaml.safe_load(Path("companies.yaml").read_text())
    by_name = {c["name"]: c for c in config["companies"]}

    assert by_name["Microsoft Research"]["adapter"] == "microsoft_research"
    assert by_name["Microsoft"]["adapter"] == "eightfold_pcsx"


# ---------------------------------------------------------------------------
# Diagnosability of silent drops
#
# Found in the first live run: 21 pages x 10 positions = 210, but fetched=209.
# No warning was logged, so the missing posting could have been either the
# dedup or a nameless entry and there was no way to tell them apart after the
# fact. Both drops now say which they were.
# ---------------------------------------------------------------------------

def test_a_nameless_posting_says_why_it_was_dropped(caplog):
    adapter = _make_adapter()
    nameless = _pos(0, 1)
    nameless["name"] = ""
    adapter.http.get.return_value = _mock_response(
        _envelope([nameless, _pos(1, 1)], count=2)
    )

    with caplog.at_level(logging.WARNING):
        jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert "no title" in caplog.text.lower()


def test_a_duplicate_posting_says_it_was_a_duplicate(caplog):
    """Debug, not warning: the API legitimately repeats a posting across pages
    when the corpus shifts mid-walk, so this is expected, not a fault."""
    adapter = _make_adapter()
    duplicate = _pos(0, 1)
    adapter.http.get.return_value = _mock_response(
        _envelope([duplicate, dict(duplicate)], count=2)
    )

    with caplog.at_level(logging.DEBUG):
        jobs = list(adapter.fetch())

    assert len(jobs) == 1
    assert "duplicate" in caplog.text.lower()
