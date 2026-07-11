"""Unit tests for the Tier 3 meta-evaluation metrics and calibration."""

import pytest

from conftest import SAMPLES_DIR, load_json, load_jsonl

from evalforge import policy
from evalforge.judge import FakeJudge
from evalforge.metrics import (
    adjacent_agreement,
    calibrate,
    cohen_kappa,
    exact_agreement,
    self_consistency,
)
from evalforge.models import CandidateOutput, EvalSuite, GoldenSet


def load_golden():
    golden_dir = SAMPLES_DIR / "golden"
    suite = EvalSuite.model_validate(load_json(golden_dir / "suite.json"))
    outputs = [
        CandidateOutput.model_validate(line)
        for line in load_jsonl(golden_dir / "outputs.jsonl")
    ]
    labels = GoldenSet.model_validate(load_json(golden_dir / "labels.json"))
    return suite, outputs, labels


# ----------------------------------------------------------------- agreement


def test_exact_agreement():
    assert exact_agreement([1, 2, 3, 4], [1, 2, 5, 5]) == 0.5


def test_adjacent_agreement_uses_policy_distance():
    assert policy.ADJACENT_DISTANCE == 1
    assert adjacent_agreement([1, 2, 3], [2, 4, 3]) == pytest.approx(2 / 3)


def test_agreement_rejects_mismatched_or_empty_lists():
    with pytest.raises(ValueError, match="length"):
        exact_agreement([1, 2], [1])
    with pytest.raises(ValueError, match="empty"):
        exact_agreement([], [])


# --------------------------------------------------------------------- kappa


def test_kappa_perfect_agreement_is_one():
    assert cohen_kappa([1, 2, 3, 4, 5], [1, 2, 3, 4, 5]) == 1.0


def test_kappa_chance_level_agreement_is_zero():
    # po = 0.5 and pe = 0.5: agreement no better than chance.
    assert cohen_kappa([1, 1, 2, 2], [1, 2, 1, 2]) == pytest.approx(0.0)


def test_kappa_hand_computed_value():
    # po = 0.5, pe = 0.25 -> kappa = (0.5 - 0.25) / 0.75 = 1/3
    assert cohen_kappa([5, 5, 4, 1], [5, 4, 4, 2]) == pytest.approx(1 / 3)


def test_kappa_degenerate_constant_raters():
    assert cohen_kappa([5, 5], [5, 5]) == 1.0
    assert cohen_kappa([5, 5], [5, 4]) == pytest.approx(0.0)


# --------------------------------------------------------------- consistency


def test_self_consistency_perfect_repeatability():
    assert self_consistency([[1, 2, 3], [1, 2, 3], [1, 2, 3]]) == 1.0


def test_self_consistency_mean_pairwise_agreement():
    # pairs: (1,2)=0.5, (1,3)=0.5, (2,3)=1.0 -> mean 2/3
    assert self_consistency([[1, 2], [1, 3], [1, 3]]) == pytest.approx(2 / 3)


def test_self_consistency_needs_two_runs():
    with pytest.raises(ValueError, match="two runs"):
        self_consistency([[1, 2, 3]])


# --------------------------------------------------------------- calibration


def test_accurate_judge_calibrates_on_the_golden_set():
    suite, outputs, labels = load_golden()
    criteria = [c.name for c in suite.rubric.criteria]
    accurate = FakeJudge(
        {label.case_id: {name: label.score for name in criteria} for label in labels.labels}
    )
    report = calibrate(suite, outputs, labels, accurate)
    assert report.n_cases == len(labels.labels) >= policy.MIN_GOLDEN_CASES
    assert report.exact_agreement == 1.0
    assert report.cohen_kappa == 1.0
    assert report.calibrated
    assert report.generated_by == "fake-judge"


def test_sycophantic_judge_fails_calibration():
    """A judge that scores everything 5/5 must be denied verdict rights."""
    suite, outputs, labels = load_golden()
    criteria = [c.name for c in suite.rubric.criteria]
    sycophant = FakeJudge(
        {label.case_id: {name: policy.SCORE_MAX for name in criteria} for label in labels.labels}
    )
    report = calibrate(suite, outputs, labels, sycophant)
    assert report.cohen_kappa == pytest.approx(0.0)
    assert not report.calibrated


def test_calibrate_rejects_labels_without_case_or_output():
    suite, outputs, labels = load_golden()
    with pytest.raises(ValueError, match="G-01"):
        calibrate(suite, outputs[1:], labels, FakeJudge({}))
