"""Tier 3 meta-evaluation metrics (ADR-001): judge the judge.

Agreement between judge and human scores on the golden set decides whether
the judge earns verdict rights. All metrics are dependency-free on purpose
(no scipy/sklearn): the formulas are small, and owning them keeps the
zero-key install lean and the numbers auditable.
"""

from __future__ import annotations

from collections import Counter

from evalforge import policy
from evalforge.judge import Judge
from evalforge.models import CalibrationReport, CandidateOutput, EvalSuite, GoldenSet


def exact_agreement(a: list[int], b: list[int]) -> float:
    """Fraction of positions where both raters gave the same score."""
    _validate_pair(a, b)
    return sum(x == y for x, y in zip(a, b)) / len(a)


def adjacent_agreement(
    a: list[int], b: list[int], distance: int = policy.ADJACENT_DISTANCE
) -> float:
    """Fraction of positions where the raters differ by at most ``distance``."""
    _validate_pair(a, b)
    return sum(abs(x - y) <= distance for x, y in zip(a, b)) / len(a)


def cohen_kappa(a: list[int], b: list[int]) -> float:
    """Cohen's kappa: agreement corrected for chance, in [-1, 1].

    Degenerate case: when expected chance agreement is 1 (both raters
    constant), kappa is 1.0 on perfect agreement and 0.0 otherwise.
    """
    _validate_pair(a, b)
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    counts_a, counts_b = Counter(a), Counter(b)
    expected = sum(
        (counts_a[category] / n) * (counts_b[category] / n)
        for category in counts_a.keys() | counts_b.keys()
    )
    if expected == 1.0:
        return 1.0 if observed == 1.0 else 0.0
    return (observed - expected) / (1.0 - expected)


def self_consistency(runs: list[list[int]]) -> float:
    """Mean pairwise exact agreement across repeated judge runs.

    ``runs`` holds one score list per run, all over the same cases in the
    same order. 1.0 means the judge is perfectly repeatable.
    """
    if len(runs) < 2:
        raise ValueError("self_consistency needs at least two runs")
    agreements = [
        exact_agreement(runs[i], runs[j])
        for i in range(len(runs))
        for j in range(i + 1, len(runs))
    ]
    return sum(agreements) / len(agreements)


def calibrate(
    suite: EvalSuite,
    outputs: list[CandidateOutput],
    golden: GoldenSet,
    judge: Judge,
) -> CalibrationReport:
    """Grade the golden set with ``judge`` and measure agreement with humans.

    The returned report's ``calibrated`` flag is computed from the ADR-001
    policy gate (and re-enforced by the model itself): kappa >= KAPPA_FLOOR
    over at least MIN_GOLDEN_CASES labeled cases.
    """
    cases_by_id = {case.id: case for case in suite.cases}
    outputs_by_id = {output.case_id: output for output in outputs}
    missing = [
        label.case_id
        for label in golden.labels
        if label.case_id not in cases_by_id or label.case_id not in outputs_by_id
    ]
    if missing:
        raise ValueError(
            "golden labels without a matching case/output: " + ", ".join(missing)
        )

    human_scores: list[int] = []
    judge_scores: list[int] = []
    for label in golden.labels:
        case = cases_by_id[label.case_id]
        score = judge.grade(case, outputs_by_id[label.case_id].output, suite.rubric)
        human_scores.append(label.score)
        judge_scores.append(_to_scale(score.overall))

    n_cases = len(golden.labels)
    kappa = cohen_kappa(judge_scores, human_scores)
    return CalibrationReport(
        n_cases=n_cases,
        exact_agreement=exact_agreement(judge_scores, human_scores),
        adjacent_agreement=adjacent_agreement(judge_scores, human_scores),
        cohen_kappa=kappa,
        calibrated=n_cases >= policy.MIN_GOLDEN_CASES and kappa >= policy.KAPPA_FLOOR,
        generated_by=judge.name,
    )


def _to_scale(overall: float) -> int:
    """Round a judge overall to the nearest integer on the policy scale."""
    rounded = int(overall + 0.5)  # round half up, deterministically
    return max(policy.SCORE_MIN, min(policy.SCORE_MAX, rounded))


def _validate_pair(a: list[int], b: list[int]) -> None:
    if len(a) != len(b):
        raise ValueError(f"score lists differ in length: {len(a)} vs {len(b)}")
    if not a:
        raise ValueError("score lists must not be empty")
