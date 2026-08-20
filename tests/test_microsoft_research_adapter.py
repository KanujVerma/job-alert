"""Tests for MicrosoftResearchAdapter — Microsoft Research WordPress REST API.

Endpoint (verified live 2026-08-19):
    GET https://www.microsoft.com/en-us/research/wp-json/microsoft-research/v2/careers

Public, unauthenticated, and self-describing: the namespace root documents its own
query args. 99 postings, one page at per_page=100.

The fixture is a real three-item slice captured verbatim from that endpoint on
2026-08-19 (only `_pagination.total` was adjusted to match the slice). The three
were chosen because they exercise the cases that differ:
    - "Research Intern - Self-Improving AI"  — US internship, two cities
    - "Research Intern for Media Computing Group (Video)" — China internship
    - "UK Residency Programme - ..." — non-US, non-internship

The adapter NEVER raises; every failure path yields nothing and logs.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock

import requests

from src.adapters.microsoft_research import MicrosoftResearchAdapter
from src.http import HTTPClient
from src.models import Job

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "microsoft_research.json"

_CONFIG = {
    "base_url": "https://www.microsoft.com/en-us/research/careers/open-positions/",
}


def _make_adapter(config: dict | None = None) -> MicrosoftResearchAdapter:
    http = MagicMock(spec=HTTPClient)
    return MicrosoftResearchAdapter(
        company="microsoft research",
        config=config or _CONFIG,
        http=http,
    )


def _mock_response(payload: dict) -> MagicMock:
    resp = MagicMock()
    resp.ok = True
    resp.status_code = 200
    resp.json.return_value = payload
    return resp


def _fixture() -> dict:
    return json.loads(FIXTURE_PATH.read_text())


def _fetch_with_fixture() -> list[Job]:
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_fixture())
    return list(adapter.fetch())




def _by_title(jobs: list[Job], fragment: str) -> Job:
    matches = [j for j in jobs if fragment in j.title]
    assert len(matches) == 1, f"expected exactly one job matching {fragment!r}"
    return matches[0]


# ---------------------------------------------------------------------------
# Field mapping
# ---------------------------------------------------------------------------

def test_source_platform_constant():
    assert MicrosoftResearchAdapter.source_platform == "microsoft_research"


def test_yields_every_item_in_the_payload():
    assert len(_fetch_with_fixture()) == 3


def test_title_comes_from_name_not_title():
    """The API field is `name`. There is no `title` key — reading one yields nothing."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.title == "Research Intern - Self-Improving AI"


def test_url_is_the_application_link():
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.url == "https://apply.careers.microsoft.com/careers/job/1970393556867858"


def test_official_id_is_used_for_the_job_id():
    """A stable numeric id from the source beats a title/location hash."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.id == "microsoft research::microsoft_research::1173006"


def test_location_joins_every_city():
    """A posting open in two cities must say so — dropping one hides a US option."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.location == "Cambridge, MA, US; New York, NY, US"


def test_posted_at_honours_the_utc_offset():
    """datePublished carries a -07:00 offset, not a Z suffix. Compared as a UTC
    instant: an adapter that drops the offset lands on 16:20Z instead of 23:20Z."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.posted_at == datetime(2026, 5, 18, 23, 20, 11, tzinfo=timezone.utc)


def test_department_comes_from_research_areas():
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.department == "Artificial intelligence"


def test_company_is_passed_through():
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.company == "microsoft research"
    assert job.source_platform == "microsoft_research"


# ---------------------------------------------------------------------------
# role_type — a real signal from the source, not a guess from the title
# ---------------------------------------------------------------------------

def test_internship_opportunity_type_sets_role_type():
    """opportunityTypes carries slug 'internship'. base.py asks adapters to set
    role_type when the source knows it — here it does, so don't leave it unknown."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert job.role_type == "internship"


def test_non_internship_opportunity_type_stays_unknown():
    """'Post-doc researcher' is not an internship and must not be labelled one."""
    job = _by_title(_fetch_with_fixture(), "UK Residency Programme")
    assert job.role_type == "unknown"


# ---------------------------------------------------------------------------
# raw_text — what the filter pipeline actually reads
# ---------------------------------------------------------------------------

def test_raw_text_carries_the_excerpt():
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert "self-improving" in job.raw_text


def test_raw_text_decodes_html_entities():
    """The excerpt ends in a literal '[&hellip;]'. Leaving it encoded puts the
    string 'hellip' into text the keyword filters match against."""
    job = _by_title(_fetch_with_fixture(), "UK Residency Programme")
    assert "hellip" not in job.raw_text


def test_raw_text_carries_research_areas():
    """Research area names are the strongest technical signal the list response
    has; without them a terse title can fail the tech-role filter on its own."""
    job = _by_title(_fetch_with_fixture(), "Self-Improving AI")
    assert "artificial intelligence" in job.raw_text


def test_raw_text_carries_the_location():
    """The location filter reads location AND raw_text; a China posting must be
    identifiable from either."""
    job = _by_title(_fetch_with_fixture(), "Media Computing Group")
    assert "china" in job.raw_text


def test_raw_text_is_lowercased():
    for job in _fetch_with_fixture():
        assert job.raw_text == job.raw_text.lower()


# ---------------------------------------------------------------------------
# The request itself
# ---------------------------------------------------------------------------

def test_requests_the_wordpress_api_not_the_eightfold_endpoint():
    """The Eightfold API answers 403 and jobs.careers.microsoft.com is a JS SPA.
    Neither may be called."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_fixture())

    list(adapter.fetch())

    url = adapter.http.get.call_args.args[0]
    assert url == (
        "https://www.microsoft.com/en-us/research/wp-json/microsoft-research/v2/careers"
    )


def test_query_is_deliberately_unfiltered():
    """No server-side type/region filter. A narrow query makes fetched==0 an
    ambiguous signal, which is exactly what the adapter-health design warned
    about — the bot's own filter pipeline does the selecting."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_fixture())

    list(adapter.fetch())

    params = adapter.http.get.call_args.kwargs["params"]
    assert "type" not in params
    assert "region" not in params
    assert "search" not in params


def test_requests_the_fields_it_parses():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_fixture())

    list(adapter.fetch())

    fields = adapter.http.get.call_args.kwargs["params"]["fields"].split(",")
    for required in (
        "id", "name", "url", "datePublished",
        "cities", "opportunityTypes", "researchAreas", "excerpt",
    ):
        assert required in fields


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------

def _page(page_num: int, total_pages: int, items: list[dict]) -> MagicMock:
    return _mock_response({
        "_pagination": {
            "total": 200, "perPage": 100,
            "currentPage": page_num, "totalPages": total_pages,
        },
        "items": items,
    })


def test_follows_pagination_to_the_last_page():
    adapter = _make_adapter()
    items = _fixture()["items"]
    adapter.http.get.side_effect = [
        _page(1, 2, items[:1]),
        _page(2, 2, items[1:2]),
    ]

    jobs = list(adapter.fetch())

    assert len(jobs) == 2
    assert adapter.http.get.call_count == 2
    assert adapter.http.get.call_args_list[1].kwargs["params"]["page"] == 2


def test_stops_at_a_single_page():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response(_fixture())

    list(adapter.fetch())

    assert adapter.http.get.call_count == 1


def test_pagination_is_capped_against_a_runaway_response():
    """A totalPages the server reports wrong must not spin the run forever.

    Only the request count is asserted here. This test previously also asserted
    len(jobs) == call_count — i.e. that ten copies of one posting was correct.
    That was pinning a bug: deduplication is covered by
    test_the_same_posting_is_never_yielded_twice.
    """
    adapter = _make_adapter()
    items = _fixture()["items"][:1]
    adapter.http.get.return_value = _page(1, 9999, items)

    list(adapter.fetch())

    assert adapter.http.get.call_count <= 10


# ---------------------------------------------------------------------------
# Failure paths — never raises
# ---------------------------------------------------------------------------

def test_http_error_yields_nothing():
    """The WAF 403s on some user agents. That must degrade, not crash."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = requests.HTTPError("403 Forbidden")

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


def test_missing_items_key_yields_nothing():
    adapter = _make_adapter()
    adapter.http.get.return_value = _mock_response({"_pagination": {"totalPages": 1}})

    assert list(adapter.fetch()) == []


def test_item_without_a_name_is_skipped_not_fatal():
    adapter = _make_adapter()
    payload = _fixture()
    payload["items"].insert(0, {"id": 1, "url": "https://example.com"})
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 3
    assert all(job.title for job in jobs)


def test_one_unparseable_item_does_not_lose_the_others():
    """A stray non-dict in `items` must cost that entry, not the whole page."""
    adapter = _make_adapter()
    payload = _fixture()
    payload["items"].insert(0, "not-an-object")
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 3


def test_a_malformed_subfield_degrades_that_field_not_the_posting():
    """`cities` arriving as a string rather than a list loses the location and
    nothing else. Dropping a real job over one bad field is the worse failure."""
    adapter = _make_adapter()
    payload = _fixture()
    payload["items"].insert(0, {
        "id": 2,
        "name": "Broken Cities",
        "url": "https://apply.careers.microsoft.com/careers/job/2",
        "cities": "not-a-list",
    })
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert len(jobs) == 4
    broken = _by_title(jobs, "Broken Cities")
    assert broken.location == ""


def test_failure_on_a_later_page_keeps_the_earlier_results():
    adapter = _make_adapter()
    adapter.http.get.side_effect = [
        _page(1, 3, _fixture()["items"][:2]),
        requests.ConnectionError("dropped"),
    ]

    jobs = list(adapter.fetch())

    assert len(jobs) == 2


def test_hitting_the_page_cap_is_logged_not_silent(caplog):
    """Truncating at the cap must say so. A silent stop reads as 'we got
    everything', which is the failure mode this bot exists to avoid."""
    adapter = _make_adapter()
    adapter.http.get.return_value = _page(1, 9999, _fixture()["items"][:1])

    with caplog.at_level(logging.WARNING):
        list(adapter.fetch())

    assert "cap" in caplog.text.lower()
    assert "9999" in caplog.text


# ---------------------------------------------------------------------------
# Hardening — defects found by adversarial review, 2026-08-20
# ---------------------------------------------------------------------------

def test_non_dict_pagination_does_not_raise():
    """`_pagination` arriving as a string/int/list must degrade to one page.

    `.get` on a non-dict raises AttributeError, which is NOT a RequestException
    or ValueError, so it escapes the generator. It escapes AFTER page 1 has
    yielded, so main.py's `list(adapter.fetch())` discards the postings it
    already produced and records the company as fetched=0 — which makes a
    healthy adapter look silent to the health tracking.
    """
    for bad in ("1", 7, [1, 2], True):
        adapter = _make_adapter()
        payload = _fixture()
        payload["_pagination"] = bad
        adapter.http.get.return_value = _mock_response(payload)

        jobs = list(adapter.fetch())  # must not raise

        assert len(jobs) == 3, f"_pagination={bad!r} lost the page's postings"


def test_naive_date_published_is_made_utc_aware():
    """A naive posted_at would abort the ENTIRE run, not just this adapter.

    filter_freshness subtracts it from an aware now(), raising TypeError, and
    main.py runs the filter pipeline outside any try/except — so one such
    posting kills every company after it and state is never saved.
    smartrecruiters.py already guards this way.
    """
    adapter = _make_adapter()
    payload = _fixture()
    payload["items"][0]["datePublished"] = "2026-05-18T16:20:11"  # no offset
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    stamped = [j for j in jobs if j.posted_at is not None]
    assert stamped, "expected at least one posting with a timestamp"
    for job in stamped:
        assert job.posted_at.tzinfo is not None
        assert job.posted_at.utcoffset() is not None


def test_the_same_posting_is_never_yielded_twice():
    """One posting must become one Discord alert.

    Nothing downstream deduplicates within a run, so if the API ever ignores or
    clamps `page`, repeated postings become repeated embeds for one job.
    """
    adapter = _make_adapter()
    adapter.http.get.return_value = _page(1, 9999, _fixture()["items"][:1])

    jobs = list(adapter.fetch())

    assert len(jobs) == 1, f"yielded {len(jobs)} copies of one posting"
    assert len({j.id for j in jobs}) == len(jobs)


def test_an_empty_middle_page_is_logged(caplog):
    """A short result that looks complete is worse than a loud partial one —
    the same argument the page-cap warning was added for."""
    adapter = _make_adapter()
    adapter.http.get.side_effect = [
        _page(1, 5, _fixture()["items"][:2]),
        _page(2, 5, []),
    ]

    with caplog.at_level(logging.WARNING):
        jobs = list(adapter.fetch())

    assert len(jobs) == 2
    assert "page 2" in caplog.text.lower()


def test_posting_without_a_url_is_skipped():
    """notifier.py puts job.url straight into an embed field value; Discord
    rejects an empty value with 400, so the send fails, mark_alerted never
    runs, and the job retries every run until it ages out — ~192 failed
    sends. A posting with no link cannot be applied to anyway."""
    adapter = _make_adapter()
    payload = _fixture()
    payload["items"].insert(0, {"id": 99, "name": "No Link Here", "url": ""})
    adapter.http.get.return_value = _mock_response(payload)

    jobs = list(adapter.fetch())

    assert "No Link Here" not in [j.title for j in jobs]
    assert all(j.url for j in jobs)
