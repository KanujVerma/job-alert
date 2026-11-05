"""Phase 1E: bachelor's-path eligibility and lossless bounded backfill."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.backfill import deliver_backfill_batch
from src.eligibility import classify_eligibility
from src.experience import assess_experience_requirements
from src.models import Job
from src.storage import (
    POLICY_VERSION,
    _empty_state,
    is_backfill_pending,
    is_url_alerted,
)


NOW = datetime(2026, 11, 5, 12, 0, tzinfo=timezone.utc)


def make_job(i: int, *, title: str = "Software Engineer, New Grad",
             description: str = "", url: str | None = None) -> Job:
    return Job(
        id=f"Intel::workday::P1E-{i}", company="Intel", title=title,
        location="Austin, TX", department="Engineering", category="Software",
        url=url if url is not None else f"https://example.com/jobs/p1e-{i}",
        source_platform="workday", posted_at=NOW - timedelta(days=3),
        detected_at=NOW, raw_text=description.lower(), role_type="unknown",
        priority="normal", matched_keywords=(),
    )


@pytest.mark.parametrize(
    "description, expected_years, ambiguous",
    [
        (
            "Minimum Qualifications Bachelor's degree with 4+ years of industry experience OR "
            "Master's degree with 2+ years of industry experience. "
            "2+ years of experience using Python.",
            4, False,
        ),
        (
            "Minimum Qualifications Bachelor’s degree with 3+ years relevant industry experience "
            "- OR - Master’s degree with 2+ years relevant industry experience. "
            "2+ years of experience troubleshooting robotics.",
            3, False,
        ),
        ("Bachelors & 4+ years or Masters & 3+ years in an engineering field", 4, False),
        ("BS degree with 4+ yrs of professional experience OR MS degree with 3+ yrs of experience", 4, False),
        (
            "Minimum Qualifications: Bachelor's degree in CS required. "
            "4+ years of experience in software engineering. "
            "Preferred Qualifications: 7+ years industry experience.",
            4, False,
        ),
        ("0-2 years of software engineering experience", 0, False),
        ("Minimum 1 year of programming experience in Python or Go", 1, False),
        ("Bachelor's degree in Computer Science or closely related field", None, False),
        ("Bachelor's degree OR Master's degree with 2+ years of relevant industry experience", None, True),
        ("Master's degree with 2+ years of relevant industry experience", None, True),
        ("2+ years of experience with Kubernetes", None, True),
        ("2+ years of experience in Python", None, True),
        ("4+ years of professional experience and 2+ years of experience in Python", 4, False),
        ("2+ years of professional experience and 4+ years of experience with Kubernetes", 2, True),
        ("Bachelor's degree with 6+ months of industry experience OR Master's degree with 0 years experience", 0.5, False),
        ("Bachelor's degree with 2+ years experience OR Master's degree with 5+ years experience", 2, False),
        ("PhD required. 3+ years relevant industry experience", None, True),
        ("Preferred Qualifications: 8+ years of industry experience", None, False),
        ("Minimum Qualifications: 3+ years of relevant industry experience", 3, False),
        ("Minimum Qualifications: 4+ years of relevant industry experience", 4, False),
        ("Bachelor's degree with 5 years experience. Preferred Qualifications: 2 years Python experience", 5, False),
    ],
)
def test_required_experience_uses_correct_path(description, expected_years, ambiguous):
    assessment = assess_experience_requirements(description)
    assert assessment.minimum_years == expected_years
    assert assessment.ambiguous is ambiguous


@pytest.mark.parametrize(
    "title, requirement, expected",
    [
        (
            "EDA Tool Software Engineer",
            "Minimum Qualifications: Bachelor's in Computer Science with 4+ years of industry experience "
            "OR Master's with 3+ years OR PhD with 6+ months. "
            "2+ years of experience in Python.",
            "excluded",
        ),
        (
            "EDA Tool Software Engineer",
            "Minimum Qualifications Bachelors & 4+ years or Masters & 3+ years in EDA. "
            "2+ years of experience using Python.",
            "excluded",
        ),
        (
            "AMHS Intelligent Systems Engineer",
            "Minimum Qualifications: Bachelor’s degree with 3+ years relevant industry experience "
            "OR Master’s degree with 2+ years. "
            "2+ years hands-on experience troubleshooting industrial equipment.",
            "needs_review",
        ),
        (
            "Software Engineer, New Grad",
            "Bachelor's degree in Computer Science and 0-2 years of software development experience.",
            "eligible",
        ),
        (
            "Junior Backend Engineer",
            "Bachelor's degree with 2+ years overall engineering experience "
            "OR Master's with 0 years experience.",
            "eligible",
        ),
        (
            "Software Engineer, New Grad",
            "Bachelor's degree OR Master's degree with 2+ years relevant industry experience.",
            "needs_review",
        ),
        (
            "Software Engineer I",
            "Minimum qualifications: Bachelor's degree with 2+ years of industry experience; "
            "Preferred qualifications: 6 years of industry experience.",
            "eligible",
        ),
        (
            "Software Engineer",
            "Minimum 1 year programming experience in Python or Go.",
            "eligible",
        ),
        (
            "Software Engineer, New Grad",
            "Minimum qualifications: Bachelor's degree in Computer Science. "
            "4+ years of professional engineering experience; "
            "2+ years of experience with Kubernetes.",
            "excluded",
        ),
        (
            "Software Engineer, New Grad",
            "Minimum qualifications: 2+ years of professional experience "
            "and 4+ years of experience in specialized chip design.",
            "needs_review",
        ),
    ],
)
def test_job_eligibility_does_not_take_shortest_experience_clause(title, requirement, expected):
    job = make_job(0, title=title, description=f"{title}. Full-time. {requirement}")
    verdict = classify_eligibility(job)
    assert verdict.status == expected, f"{verdict.reasons}: {verdict.evidence_spans}"


class FakeSender:
    def __init__(self, outcomes: list[bool | Exception] | None = None):
        self.outcomes = list(outcomes or [])
        self.payloads: list[tuple[str, str]] = []

    def send_summary(self, title: str, description: str) -> bool:
        self.payloads.append((title, description))
        outcome = self.outcomes.pop(0) if self.outcomes else True
        if isinstance(outcome, Exception):
            raise outcome
        return bool(outcome)


def make_state(jobs: list[Job]) -> dict:
    state = _empty_state()
    state["migrations"][POLICY_VERSION] = {"backfill_completed": False}
    state["companies"]["Intel"] = {
        "seen_jobs": {
            job.id: {
                "first_seen": NOW.isoformat(),
                "last_seen": NOW.isoformat(),
                "alerted": False,
            }
            for job in jobs
        }
    }
    return state


def test_25_backfill_opportunities_are_all_displayed_in_three_bounded_batches():
    jobs = [make_job(i) for i in range(25)]
    state = make_state(jobs)
    sender = FakeSender()
    for expected_sent, expected_pending, expected_done in [
        (10, 15, False), (10, 5, False), (5, 0, True)
    ]:
        before = len(state["alerted_urls"])
        result = deliver_backfill_batch(jobs, state, sender, now=NOW)
        assert (result.delivered, result.remaining, result.completed) == (
            expected_sent, expected_pending, expected_done
        )
        assert len(state["alerted_urls"]) - before == expected_sent
        assert is_backfill_pending(state) is not expected_done

    assert len(sender.payloads) == 3
    all_delivered_urls = " ".join(body for _, body in sender.payloads)
    for job in jobs:
        assert sum(1 for line in all_delivered_urls.splitlines() if line.strip() == job.url) == 1
        assert is_url_alerted(job.url, state)
        assert state["companies"]["Intel"]["seen_jobs"][job.id]["alerted"] is True
    assert len(sender.payloads[0][1]) < 4096


def test_failed_first_batch_acks_nothing_and_retry_is_idempotent():
    jobs = [make_job(i) for i in range(12)]
    state = make_state(jobs)
    sender = FakeSender([False, True, True])
    failure = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert failure.delivered == 0
    assert failure.remaining == 12
    assert is_backfill_pending(state)
    assert len(state["alerted_urls"]) == 0

    first_success = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert first_success.delivered == 10
    assert first_success.remaining == 2
    assert len(state["alerted_urls"]) == 10
    last = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert last.delivered == 2 and last.completed
    assert len(state["alerted_urls"]) == 12


def test_missing_notifier_and_exception_do_not_ack_any_jobs():
    jobs = [make_job(1)]
    state = make_state(jobs)
    assert not deliver_backfill_batch(jobs, state, None, now=NOW).attempted
    assert not state["alerted_urls"]
    sender = FakeSender([TimeoutError("transport uncertain")])
    res = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert res.attempted and not res.completed and res.delivered == 0
    assert not state["alerted_urls"]


def test_non_url_or_unrenderable_first_job_is_not_acknowledged():
    jobs = [make_job(1, url="https://example.com/" + "a" * 4000)]
    state = make_state(jobs)
    sender = FakeSender()
    res = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert not res.attempted
    assert not state["alerted_urls"] and not sender.payloads
    assert is_backfill_pending(state)


def test_no_candidates_completes_backfill_without_sending():
    state = make_state([])
    sender = FakeSender()
    res = deliver_backfill_batch([], state, sender, now=NOW)
    assert res.completed and res.delivered == 0 and res.remaining == 0
    assert not sender.payloads


def test_repeated_job_urls_cannot_generate_duplicate_backfill_items():
    original = make_job(1)
    duplicate = make_job(2, url=original.url + "?utm_source=test")
    state = make_state([original, duplicate])
    sender = FakeSender()
    result = deliver_backfill_batch([original, duplicate], state, sender, now=NOW)
    assert result.delivered == 1 and result.completed
    assert sender.payloads[0][1].count(original.url) == 1


def test_malformed_url_is_skipped_without_blocking_valid_candidates():
    invalid = make_job(1, url="javascript:alert(1)")
    valid = make_job(2)
    state = make_state([invalid, valid])
    sender = FakeSender()
    outcome = deliver_backfill_batch([invalid, valid], state, sender, now=NOW)
    assert outcome.delivered == 1 and outcome.remaining == 1
    assert not outcome.completed
    assert is_url_alerted(valid.url, state)
    assert not is_url_alerted(invalid.url, state)
    assert valid.url in sender.payloads[0][1]
    assert "javascript:" not in sender.payloads[0][1]


@pytest.mark.parametrize(
    "description, years, ambiguous",
    [
        ("Minimum Qualifications: 4+ years of professional experience with a Bachelor's degree "
         "OR 2+ years of professional experience with a Master's degree.", 4, False),
        ("4+ years experience with bachelor's degree OR 2+ years with master's degree", 4, False),
        ("6 months experience with a bachelor's degree or master's degree with 0 years", 0.5, False),
        ("Bachelor's degree in CS or a related field with 4+ years experience OR Master's with 2+ years", 4, False),
        ("Master's with 2 years OR Bachelor's with 4 years experience", 4, False),
        ("Bachelor's degree OR 2+ years experience with a Master's degree", None, True),
    ],
)
def test_years_preceding_degree_not_stolen_from_next_degree_path(description, years, ambiguous):
    assessment = assess_experience_requirements(description)
    assert assessment.minimum_years == years
    assert assessment.ambiguous is ambiguous


def test_bachelors_pathway_with_prefix_four_years_blocks_false_newgrad_alert():
    title = "EDA Tool Software Engineer"
    description = (
        "Minimum Qualifications: 4+ years of relevant industry experience "
        "with a Bachelor's degree OR 2+ years of industry experience "
        "with a Master's degree. 1+ year of experience with EDA software."
    )
    verdict = classify_eligibility(make_job(45, title=title, description=description))
    assert verdict.status == "excluded"
    assert "EXPERIENCE_EXCEEDS_RANGE" in verdict.reasons


def test_unrelated_or_equivalent_does_not_cancel_masters_degree_requirement():
    requirement = (
        "Bachelor's degree in Computer Science or equivalent experience "
        "and 1 year of professional experience. Master's degree required."
    )
    assessment = assess_experience_requirements(requirement)
    assert not assessment.has_bachelors_alternative
    verdict = classify_eligibility(
        make_job(81, title="Software Engineer, New Grad", description=requirement)
    )
    assert verdict.status == "excluded"
    assert "MASTERS_REQUIRED" in verdict.reasons


def test_inline_preferred_tenure_does_not_become_required():
    requirement = (
        "Minimum qualifications: Bachelor's degree in CS and 0-2 years of "
        "professional experience required. 4 years of professional experience preferred."
    )
    assessment = assess_experience_requirements(requirement)
    assert assessment.minimum_years == 0
    assert not assessment.ambiguous
    verdict = classify_eligibility(
        make_job(82, title="Software Engineer, New Grad", description=requirement)
    )
    assert verdict.status == "eligible"


def test_four_year_degree_duration_is_not_four_years_of_work():
    requirement = "Bachelor's degree in Computer Science (4 years). No prior work experience required."
    assessment = assess_experience_requirements(requirement)
    assert assessment.minimum_years is None
    assert not assessment.ambiguous
    verdict = classify_eligibility(
        make_job(83, title="Software Engineer, New Grad", description=requirement)
    )
    assert verdict.status == "eligible"


def test_fractional_three_point_five_years_is_review_not_eligible():
    requirement = "Minimum qualifications: 3.5 years of professional experience required."
    assessment = assess_experience_requirements(requirement)
    assert assessment.minimum_years == 3.5
    verdict = classify_eligibility(
        make_job(84, title="Software Engineer, New Grad", description=requirement)
    )
    assert verdict.status == "needs_review"
    assert "EXPERIENCE_EXCEEDS_RANGE" in verdict.reasons


def test_bad_bracketed_url_does_not_abort_or_block_valid_job():
    broken = make_job(85, url="https://[invalid/jobs")
    good = make_job(86)
    jobs = [broken, good]
    state = make_state(jobs)
    sender = FakeSender()
    result = deliver_backfill_batch(jobs, state, sender, now=NOW)
    assert result.delivered == 1 and result.remaining == 1
    assert not result.completed
    assert not is_url_alerted(broken.url, state)
    assert is_url_alerted(good.url, state)
    assert good.url in sender.payloads[0][1]
