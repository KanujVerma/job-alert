"""Tests for make_job_id and normalize_for_hash in src/filtering.py."""
import pytest

from src.filtering import make_job_id, normalize_for_hash


class TestNormalizeForHash:
    def test_lowercases(self):
        assert normalize_for_hash("Software Engineer") == "software engineer"

    def test_collapses_whitespace(self):
        assert normalize_for_hash("  data   science  ") == "data science"

    def test_strips_punctuation(self):
        # Non-alphanumeric chars (except spaces) are stripped
        result = normalize_for_hash("C++ Engineer, Senior!")
        assert "+" not in result
        assert "," not in result
        assert "!" not in result
        assert "engineer" in result

    def test_empty_string(self):
        assert normalize_for_hash("") == ""

    def test_only_punctuation(self):
        assert normalize_for_hash("!!!") == ""

    def test_mixed(self):
        result = normalize_for_hash("New York, NY")
        assert result == "new york ny"


class TestMakeJobId:
    def test_with_official_id(self):
        result = make_job_id("Acme", "workday", "SWE", "San Francisco", official_id="JR-1234")
        assert result == "Acme::workday::JR-1234"

    def test_with_official_id_format(self):
        """official_id preserves original company/platform casing."""
        result = make_job_id("MyCompany", "lever", "Engineer", "Remote", official_id="abc123")
        assert result == "MyCompany::lever::abc123"

    def test_without_official_id_returns_16_hex_chars(self):
        result = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        assert len(result) == 16
        assert all(c in "0123456789abcdef" for c in result)

    def test_without_official_id_is_stable(self):
        """Same inputs → same hash."""
        a = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        b = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        assert a == b

    def test_same_title_location_company_platform_same_hash(self):
        a = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        b = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        assert a == b

    def test_different_titles_different_hash(self):
        a = make_job_id("Acme", "workday", "Software Engineer", "San Francisco")
        b = make_job_id("Acme", "workday", "Data Scientist", "San Francisco")
        assert a != b

    def test_different_companies_different_hash(self):
        a = make_job_id("Acme", "workday", "Software Engineer", "Remote")
        b = make_job_id("Beta Corp", "workday", "Software Engineer", "Remote")
        assert a != b

    def test_different_locations_different_hash(self):
        a = make_job_id("Acme", "workday", "Software Engineer", "Remote")
        b = make_job_id("Acme", "workday", "Software Engineer", "New York")
        assert a != b

    def test_official_id_none_uses_hash(self):
        result = make_job_id("X", "y", "Title", "Loc", official_id=None)
        assert len(result) == 16

    def test_official_id_empty_string_uses_hash(self):
        """Empty string is falsy — should use hash path."""
        result = make_job_id("X", "y", "Title", "Loc", official_id="")
        # Empty string is falsy, so hash path is used
        assert len(result) == 16
