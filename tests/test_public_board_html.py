"""P2-A review regression: inline formatting cannot weaken job requirements."""
import pytest
import responses

from src.adapters.public_board import description
from src.eligibility import classify_eligibility
from tests.test_public_board_adapters import payload, first_job


@pytest.mark.parametrize('platform', ['greenhouse', 'ashby'])
@pytest.mark.parametrize('markup', [
    "<p>Bachelor's degree and <strong>5 years</strong> of professional experience required.</p>",
    "<div>Bachelor's degree and\n <span><b>5</b> years</span> of professional <em>experience</em> required.</div>",
])
@responses.activate
def test_inline_html_requirement_not_split_into_false_newgrad_eligibility(platform, markup):
    data = payload(platform)
    row = data['jobs'][0]
    row['title'] = 'Software Engineer I'
    if platform == 'greenhouse':
        row['content'] = markup
    else:
        row.pop('descriptionPlain', None)
        row['descriptionHtml'] = markup
    job = first_job(platform, data)
    assert '5 years of professional experience' in job.raw_text
    verdict = classify_eligibility(job)
    assert verdict.status == 'excluded', (job.raw_text, verdict)
    assert 'EXPERIENCE_EXCEEDS_RANGE' in verdict.reasons


def test_html_block_headings_preserved_without_inline_text_breaks():
    raw = (
        '<h2>Minimum <strong>Qualifications</strong></h2>'
        '<p>Full-time. Bachelor\'s degree and <b>0-2 years</b> of '
        '<span>professional experience</span> required.</p>'
        '<h2>Preferred Qualifications</h2><ul><li>5 years experience preferred.</li></ul>'
    )
    normalized, complete = description(raw, is_html=True)
    assert complete
    assert 'Minimum Qualifications\n' in normalized
    assert '0-2 years of professional experience' in normalized
    assert '\nPreferred Qualifications\n' in normalized
    from src.experience import assess_experience_requirements
    assert assess_experience_requirements(normalized).minimum_years == 0


def test_html_source_line_wrapping_does_not_create_clause_boundaries():
    normalized, complete = description(
        '<p>Bachelor\'s degree and\n5 years of\nprofessional experience required.</p><br>Full-time.',
        is_html=True,
    )
    assert complete
    assert "Bachelor's degree and 5 years of professional experience required." in normalized
    assert '\nFull-time.' in normalized


def test_html_comments_are_not_promoted_to_visible_job_requirements():
    normalized, complete = description(
        '<!doctype html><p>Full-time role.</p><!--Requires 20 years of experience-->',
        is_html=True,
    )
    assert complete and normalized == 'Full-time role.'
