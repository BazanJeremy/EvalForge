"""Unit tests for the Tier 1 deterministic checkers."""

import pytest

from evalforge.checkers import run_case_checks, run_check
from evalforge.models import (
    ContainsCheck,
    EvalCase,
    ForbiddenCheck,
    JsonStructureCheck,
    LengthCheck,
    RegexCheck,
)

GOOD_JSON = '{"title": "Alarm silent", "severity": "critical", "reproduction_steps": ["Given", "When", "Then"]}'


# ------------------------------------------------------------------ contains


def test_contains_is_case_insensitive_by_default():
    assert run_check(ContainsCheck(value="alarm"), "Alarm issue").passed


def test_contains_case_sensitive_mode():
    check = ContainsCheck(value="alarm", case_sensitive=True)
    assert not run_check(check, "Alarm issue").passed
    assert run_check(check, "the alarm is silent").passed


def test_contains_failure_detail_names_the_value():
    result = run_check(ContainsCheck(value="firefox"), "Button broken")
    assert not result.passed
    assert "firefox" in result.detail


# --------------------------------------------------------------------- regex


def test_regex_match_and_miss():
    check = RegexCheck(pattern=r"\bGiven\b")
    assert run_check(check, "Given a running pump").passed
    assert not run_check(check, "It does not work").passed


# ------------------------------------------------------------ json_structure


def test_json_structure_accepts_object_with_required_keys():
    check = JsonStructureCheck(required_keys=["title", "severity", "reproduction_steps"])
    assert run_check(check, GOOD_JSON).passed


def test_json_structure_rejects_truncated_json():
    check = JsonStructureCheck(required_keys=["title"])
    result = run_check(check, '{"title": "Login button unresponsive", "severity": "hi')
    assert not result.passed
    assert "not valid JSON" in result.detail


def test_json_structure_rejects_non_object_json():
    result = run_check(JsonStructureCheck(), "[1, 2, 3]")
    assert not result.passed
    assert "not an object" in result.detail


def test_json_structure_reports_missing_keys():
    check = JsonStructureCheck(required_keys=["title", "severity"])
    result = run_check(check, '{"title": "x"}')
    assert not result.passed
    assert "severity" in result.detail


# -------------------------------------------------------------------- length


def test_length_bounds_are_inclusive():
    check = LengthCheck(min_chars=3, max_chars=5)
    assert run_check(check, "abc").passed
    assert run_check(check, "abcde").passed
    assert not run_check(check, "ab").passed
    assert not run_check(check, "abcdef").passed


def test_length_without_max_is_open_ended():
    assert run_check(LengthCheck(min_chars=1), "x" * 10_000).passed


# ----------------------------------------------------------------- forbidden


def test_forbidden_matches_case_insensitively():
    check = ForbiddenCheck(values=["as an AI", "lorem ipsum"])
    result = run_check(check, "As an ai language model, I cannot")
    assert not result.passed
    assert "as an AI" in result.detail


def test_forbidden_passes_on_clean_output():
    assert run_check(ForbiddenCheck(values=["lorem ipsum"]), GOOD_JSON).passed


# ------------------------------------------------------------------ plumbing


def test_blocking_flag_propagates_to_result():
    blocking = run_check(JsonStructureCheck(blocking=True), GOOD_JSON)
    advisory = run_check(JsonStructureCheck(), GOOD_JSON)
    assert blocking.blocking and not advisory.blocking


def test_run_case_checks_preserves_declaration_order():
    case = EvalCase(
        id="C-1",
        input="raw report",
        checks=[
            {"type": "json_structure", "required_keys": ["title"], "blocking": True},
            {"type": "contains", "value": "alarm"},
            {"type": "length", "min_chars": 5},
        ],
    )
    results = run_case_checks(case, GOOD_JSON)
    assert [r.check_type for r in results] == ["json_structure", "contains", "length"]
    assert [r.passed for r in results] == [True, True, True]
