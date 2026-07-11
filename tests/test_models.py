"""Contract tests for the ADR-001 Pydantic models.

The verdict invariants live in the models themselves: these tests prove
that an ADR-001-violating report cannot even be constructed.
"""

import pytest
from pydantic import ValidationError

from evalforge import policy
from evalforge.models import (
    CalibrationReport,
    CandidateOutput,
    CaseResult,
    CheckResult,
    Criterion,
    EvalCase,
    EvalSuite,
    GoldenLabel,
    GoldenSet,
    JudgeScore,
    Rubric,
    SuiteReport,
    Verdict,
)

# ---------------------------------------------------------------- builders


def make_rubric() -> Rubric:
    return Rubric(criteria=[Criterion(name="correctness", description="Matches the defect.")])


def make_case(case_id: str = "C-1", checks: list | None = None) -> EvalCase:
    return EvalCase(id=case_id, input="Raw bug report: something broke.", checks=checks or [])


def make_check_result(*, blocking: bool, passed: bool) -> CheckResult:
    return CheckResult(check_type="json_structure", blocking=blocking, passed=passed)


def make_case_result(*, blocking_failure: bool = False) -> CaseResult:
    return CaseResult(
        case_id="C-1",
        check_results=[make_check_result(blocking=blocking_failure, passed=not blocking_failure)],
    )


def make_calibration(*, kappa: float = 0.62, n: int = 12) -> CalibrationReport:
    calibrated = n >= policy.MIN_GOLDEN_CASES and kappa >= policy.KAPPA_FLOOR
    return CalibrationReport(
        n_cases=n,
        exact_agreement=0.6,
        adjacent_agreement=0.9,
        cohen_kappa=kappa,
        calibrated=calibrated,
        generated_by="fake-judge",
    )


def make_report(**overrides) -> SuiteReport:
    fields = dict(
        suite_name="demo",
        verdict=Verdict.PASS,
        score=1.0,
        deterministic_score=1.0,
        conditions=["judge unavailable: weights renormalized to deterministic-only"],
        case_results=[make_case_result()],
        generated_by="system1",
    )
    fields.update(overrides)
    return SuiteReport(**fields)


# ---------------------------------------------------------- check specs


@pytest.mark.parametrize(
    "spec",
    [
        {"type": "contains", "value": "alarm"},
        {"type": "regex", "pattern": r"\bGiven\b"},
        {"type": "json_structure", "required_keys": ["title"], "blocking": True},
        {"type": "length", "min_chars": 10, "max_chars": 100},
        {"type": "forbidden", "values": ["as an ai"], "blocking": True},
    ],
)
def test_each_check_type_parses(spec):
    case = EvalCase.model_validate({"id": "C-1", "input": "x", "checks": [spec]})
    assert case.checks[0].type == spec["type"]


def test_unknown_check_type_rejected():
    with pytest.raises(ValidationError):
        EvalCase.model_validate({"id": "C-1", "input": "x", "checks": [{"type": "semantic"}]})


def test_invalid_regex_rejected():
    with pytest.raises(ValidationError):
        EvalCase.model_validate(
            {"id": "C-1", "input": "x", "checks": [{"type": "regex", "pattern": "(unclosed"}]}
        )


def test_length_bounds_must_be_ordered():
    with pytest.raises(ValidationError):
        EvalCase.model_validate(
            {"id": "C-1", "input": "x", "checks": [{"type": "length", "min_chars": 50, "max_chars": 10}]}
        )


def test_forbidden_requires_values():
    with pytest.raises(ValidationError):
        EvalCase.model_validate({"id": "C-1", "input": "x", "checks": [{"type": "forbidden", "values": []}]})


def test_extra_fields_rejected():
    with pytest.raises(ValidationError):
        EvalCase.model_validate({"id": "C-1", "input": "x", "surprise": True})


# ------------------------------------------------------- suite and rubric


def test_suite_requires_unique_case_ids():
    with pytest.raises(ValidationError, match="unique"):
        EvalSuite(name="s", rubric=make_rubric(), cases=[make_case("C-1"), make_case("C-1")])


def test_suite_requires_at_least_one_case():
    with pytest.raises(ValidationError):
        EvalSuite(name="s", rubric=make_rubric(), cases=[])


def test_rubric_requires_unique_criterion_names():
    with pytest.raises(ValidationError, match="unique"):
        Rubric(
            criteria=[
                Criterion(name="correctness", description="a"),
                Criterion(name="correctness", description="b"),
            ]
        )


# ------------------------------------------------------------ judge score


def test_judge_score_valid():
    score = JudgeScore(
        criterion_scores={"correctness": 4, "clarity": 5},
        overall=4.5,
        generated_by="fake-judge",
    )
    assert score.overall == 4.5


def test_judge_score_out_of_scale_rejected():
    with pytest.raises(ValidationError, match="outside"):
        JudgeScore(criterion_scores={"correctness": 6}, overall=5.0, generated_by="fake-judge")


def test_judge_score_overall_must_be_mean():
    with pytest.raises(ValidationError, match="mean"):
        JudgeScore(criterion_scores={"correctness": 2, "clarity": 4}, overall=5.0, generated_by="fake-judge")


def test_judge_score_requires_criteria():
    with pytest.raises(ValidationError):
        JudgeScore(criterion_scores={}, overall=3.0, generated_by="fake-judge")


# ------------------------------------------------------------- golden set


def test_golden_set_requires_unique_case_ids():
    label = GoldenLabel(case_id="G-01", score=3)
    with pytest.raises(ValidationError, match="unique"):
        GoldenSet(labels=[label, label])


def test_golden_label_score_within_scale():
    with pytest.raises(ValidationError):
        GoldenLabel(case_id="G-01", score=policy.SCORE_MAX + 1)


# ------------------------------------------------- calibration gate (ADR-001)


def test_calibrated_flag_cannot_overstate_kappa():
    """An uncalibrated judge cannot be smuggled in by mislabeling the report."""
    with pytest.raises(ValidationError, match="calibration gate"):
        CalibrationReport(
            n_cases=12,
            exact_agreement=0.3,
            adjacent_agreement=0.5,
            cohen_kappa=policy.KAPPA_FLOOR - 0.1,
            calibrated=True,
            generated_by="fake-judge",
        )


def test_calibrated_flag_cannot_overstate_sample_size():
    with pytest.raises(ValidationError, match="calibration gate"):
        CalibrationReport(
            n_cases=policy.MIN_GOLDEN_CASES - 1,
            exact_agreement=0.9,
            adjacent_agreement=1.0,
            cohen_kappa=0.9,
            calibrated=True,
            generated_by="fake-judge",
        )


def test_calibrated_flag_cannot_understate():
    with pytest.raises(ValidationError, match="calibration gate"):
        CalibrationReport(
            n_cases=12,
            exact_agreement=0.7,
            adjacent_agreement=0.95,
            cohen_kappa=0.7,
            calibrated=False,
            generated_by="fake-judge",
        )


def test_adjacent_agreement_cannot_be_below_exact():
    with pytest.raises(ValidationError, match="adjacent"):
        CalibrationReport(
            n_cases=12,
            exact_agreement=0.8,
            adjacent_agreement=0.5,
            cohen_kappa=0.7,
            calibrated=True,
            generated_by="fake-judge",
        )


# ------------------------------------------------ suite report invariants


def test_blocking_failure_forces_fail():
    with pytest.raises(ValidationError, match="forces verdict FAIL"):
        make_report(verdict=Verdict.PASS, case_results=[make_case_result(blocking_failure=True)])
    with pytest.raises(ValidationError, match="forces verdict FAIL"):
        make_report(
            verdict=Verdict.DEGRADED,
            score=0.5,
            case_results=[make_case_result(blocking_failure=True)],
        )


def test_fail_requires_identifiable_blocker():
    with pytest.raises(ValidationError, match="identifiable blocker"):
        make_report(verdict=Verdict.FAIL, score=0.2)


def test_pass_requires_score_at_threshold():
    with pytest.raises(ValidationError, match="PASS_THRESHOLD"):
        make_report(verdict=Verdict.PASS, score=policy.PASS_THRESHOLD - 0.01)


def test_judge_score_requires_calibrated_judge():
    """ADR-001 headline: an uncalibrated judge can never affect the verdict."""
    with pytest.raises(ValidationError, match="calibrated judge"):
        make_report(judge_score=0.9)


def test_valid_reports_construct():
    passing = make_report()
    assert passing.verdict is Verdict.PASS

    failing = make_report(
        verdict=Verdict.FAIL,
        score=0.3,
        deterministic_score=0.3,
        case_results=[make_case_result(blocking_failure=True)],
    )
    assert failing.case_results[0].has_blocking_failure

    degraded = make_report(verdict=Verdict.DEGRADED, score=0.58, deterministic_score=0.58)
    assert degraded.verdict is Verdict.DEGRADED

    with_judge = make_report(judge_score=0.9, calibration=make_calibration())
    assert with_judge.calibration.calibrated


def test_suite_report_round_trip():
    report = make_report(judge_score=0.9, calibration=make_calibration())
    restored = SuiteReport.model_validate_json(report.model_dump_json())
    assert restored == report


def test_candidate_output_round_trip():
    out = CandidateOutput(case_id="C-1", output='{"title": "x"}', source="demo")
    assert CandidateOutput.model_validate_json(out.model_dump_json()) == out
