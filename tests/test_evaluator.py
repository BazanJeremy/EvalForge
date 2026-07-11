"""End-to-end tests for the ADR-001 verdict engine.

The three canonical scenario fixtures are pinned here: the manifests'
expected verdicts are now enforced by the evaluator itself, zero-key.
"""

import pytest

from conftest import load_json, load_jsonl

from evalforge import policy
from evalforge.evaluator import evaluate_suite
from evalforge.judge import FakeJudge
from evalforge.models import (
    CalibrationReport,
    CandidateOutput,
    Criterion,
    EvalCase,
    EvalSuite,
    Rubric,
    Verdict,
)


def load_scenario(scenario_dir):
    suite = EvalSuite.model_validate(load_json(scenario_dir / "suite.json"))
    outputs = [
        CandidateOutput.model_validate(line)
        for line in load_jsonl(scenario_dir / "outputs.jsonl")
    ]
    manifest = load_json(scenario_dir / "manifest.json")
    return suite, outputs, manifest


def make_calibration(*, calibrated: bool = True) -> CalibrationReport:
    kappa = 0.62 if calibrated else policy.KAPPA_FLOOR - 0.2
    return CalibrationReport(
        n_cases=12,
        exact_agreement=0.5,
        adjacent_agreement=0.9,
        cohen_kappa=kappa,
        calibrated=calibrated,
        generated_by="fake-judge",
    )


def make_suite() -> EvalSuite:
    """Two cases, four checks; one non-blocking contains check fails.

    Deterministic score is 3/4 = 0.75 (< PASS_THRESHOLD): DEGRADED alone,
    but a calibrated judge scoring 5/5 lifts 0.6*0.75 + 0.4*1.0 = 0.85: PASS.
    """
    return EvalSuite(
        name="lift-demo",
        rubric=Rubric(criteria=[Criterion(name="quality", description="Overall quality.")]),
        cases=[
            EvalCase(
                id="C-1",
                input="raw report one",
                checks=[
                    {"type": "json_structure", "required_keys": ["title"], "blocking": True},
                    {"type": "length", "min_chars": 5},
                ],
            ),
            EvalCase(
                id="C-2",
                input="raw report two",
                checks=[
                    {"type": "json_structure", "required_keys": ["title"], "blocking": True},
                    {"type": "contains", "value": "firefox"},
                ],
            ),
        ],
    )


SUITE_OUTPUTS = [
    CandidateOutput(case_id="C-1", output='{"title": "Pump alarm silent on occlusion"}'),
    CandidateOutput(case_id="C-2", output='{"title": "Login button unresponsive"}'),
]
PERFECT_SCORES = {"C-1": {"quality": 5}, "C-2": {"quality": 5}}


# -------------------------------------------------- canonical scenarios


def test_canonical_scenarios_produce_their_declared_verdict(scenario_dir):
    suite, outputs, manifest = load_scenario(scenario_dir)
    report = evaluate_suite(suite, outputs)
    assert report.verdict is Verdict(manifest["expected_verdict"])


def test_scenario_pass_is_perfect_and_notes_the_missing_judge():
    suite, outputs, _ = load_scenario_by_name("scenario_pass")
    report = evaluate_suite(suite, outputs)
    assert report.score == 1.0
    assert report.judge_score is None
    assert any("judge unavailable" in c for c in report.conditions)


def test_scenario_degraded_scores_the_expected_pass_rate():
    suite, outputs, _ = load_scenario_by_name("scenario_degraded")
    report = evaluate_suite(suite, outputs)
    assert report.deterministic_score == pytest.approx(7 / 12)
    assert report.verdict is Verdict.DEGRADED


def test_scenario_fail_names_the_blocking_case():
    suite, outputs, _ = load_scenario_by_name("scenario_fail")
    report = evaluate_suite(suite, outputs)
    assert report.verdict is Verdict.FAIL
    assert any("BR-002" in c and "blocking" in c for c in report.conditions)


def load_scenario_by_name(name: str):
    from conftest import SAMPLES_DIR

    return load_scenario(SAMPLES_DIR / name)


# -------------------------------------------------- the calibration gate


def test_calibrated_judge_lifts_degraded_to_pass():
    judge = FakeJudge(PERFECT_SCORES)
    without_judge = evaluate_suite(make_suite(), SUITE_OUTPUTS)
    with_judge = evaluate_suite(
        make_suite(), SUITE_OUTPUTS, judge=judge, calibration=make_calibration()
    )
    assert without_judge.verdict is Verdict.DEGRADED
    assert with_judge.verdict is Verdict.PASS
    assert with_judge.score == pytest.approx(0.85)
    assert with_judge.judge_score == 1.0
    assert with_judge.generated_by == "system1+judge:fake-judge"


def test_uncalibrated_judge_cannot_affect_the_verdict():
    """ADR-001 headline commitment, end to end."""
    judge = FakeJudge(PERFECT_SCORES)
    report = evaluate_suite(
        make_suite(), SUITE_OUTPUTS, judge=judge, calibration=make_calibration(calibrated=False)
    )
    assert report.verdict is Verdict.DEGRADED  # the 5/5 grades changed nothing
    assert report.judge_score is None and report.calibration is None
    assert any("advisory" in c for c in report.conditions)
    # ...but the grades remain visible as advisory data on the cases.
    assert all(r.judge is not None for r in report.case_results)


def test_judge_without_calibration_report_is_advisory_too():
    report = evaluate_suite(make_suite(), SUITE_OUTPUTS, judge=FakeJudge(PERFECT_SCORES))
    assert report.verdict is Verdict.DEGRADED
    assert report.judge_score is None


def test_blocked_cases_are_never_graded():
    suite, outputs, _ = load_scenario_by_name("scenario_fail")
    criteria = [c.name for c in suite.rubric.criteria]
    judge = FakeJudge(
        {case_id: {name: 5 for name in criteria} for case_id in ("BR-001", "BR-003")}
    )
    report = evaluate_suite(suite, outputs, judge=judge, calibration=make_calibration())
    assert report.verdict is Verdict.FAIL
    assert "BR-002" not in judge.calls  # garbage in, no grade out


def test_judge_failure_falls_back_to_deterministic():
    broken = FakeJudge({})  # raises on every grade call
    report = evaluate_suite(make_suite(), SUITE_OUTPUTS, judge=broken, calibration=make_calibration())
    assert report.verdict is Verdict.DEGRADED
    assert report.judge_score is None
    assert all(r.judge is None for r in report.case_results)
    assert any("judge error" in c for c in report.conditions)


# -------------------------------------------------- evidence requirements


def test_missing_output_is_an_error_not_a_verdict():
    with pytest.raises(ValueError, match="missing output.*C-2"):
        evaluate_suite(make_suite(), SUITE_OUTPUTS[:1])


def test_unknown_output_is_an_error():
    extra = SUITE_OUTPUTS + [CandidateOutput(case_id="C-99", output="{}")]
    with pytest.raises(ValueError, match="unknown case.*C-99"):
        evaluate_suite(make_suite(), extra)


def test_duplicate_outputs_are_an_error():
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_suite(make_suite(), SUITE_OUTPUTS + [SUITE_OUTPUTS[0]])


def make_checkless_suite() -> EvalSuite:
    return EvalSuite(
        name="no-checks",
        rubric=Rubric(criteria=[Criterion(name="quality", description="Overall quality.")]),
        cases=[EvalCase(id="C-1", input="raw report")],
    )


def test_no_checks_and_no_judge_is_an_error():
    outputs = [CandidateOutput(case_id="C-1", output="anything")]
    with pytest.raises(ValueError, match="no evaluable evidence"):
        evaluate_suite(make_checkless_suite(), outputs)


def test_no_checks_with_calibrated_judge_scores_judge_only():
    outputs = [CandidateOutput(case_id="C-1", output="anything")]
    judge = FakeJudge({"C-1": {"quality": 5}})
    report = evaluate_suite(
        make_checkless_suite(), outputs, judge=judge, calibration=make_calibration()
    )
    assert report.score == 1.0
    assert report.verdict is Verdict.PASS
    assert any("judge-only" in c for c in report.conditions)
    # None, deliberately distinct from 0.0 ("every check failed") -- bug-evidence #1.
    assert report.deterministic_score is None
