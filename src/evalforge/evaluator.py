"""ADR-001 aggregation: checks -> gates -> score -> verdict.

The three-tier contract, in order:
1. Any failed blocking check forces FAIL (non-compensable).
2. Judge scores enter the suite score only through the calibration gate —
   an uncalibrated or absent judge leaves the score deterministic-only,
   with the judge's grades kept as advisory data on the case results.
3. FAIL requires an identifiable blocker; the score alone only chooses
   between PASS and DEGRADED.
"""

from __future__ import annotations

from evalforge import policy
from evalforge.checkers import run_case_checks
from evalforge.judge import Judge
from evalforge.models import (
    CalibrationReport,
    CandidateOutput,
    CaseResult,
    EvalSuite,
    SuiteReport,
    Verdict,
)


def evaluate_suite(
    suite: EvalSuite,
    outputs: list[CandidateOutput],
    judge: Judge | None = None,
    calibration: CalibrationReport | None = None,
) -> SuiteReport:
    """Evaluate candidate outputs against a suite and produce the report.

    ``outputs`` must map 1:1 to the suite's cases — no evidence, no opinion
    (an absent output is an error, never a verdict). ``judge`` is optional;
    ``calibration`` is the judge's report on the golden set and decides
    whether its scores may affect the verdict (ADR-001 calibration gate).
    """
    outputs_by_id = _outputs_by_id(suite, outputs)
    conditions: list[str] = []

    # Tier 1 — deterministic checks.
    case_results: list[CaseResult] = []
    for case in suite.cases:
        check_results = run_case_checks(case, outputs_by_id[case.id].output)
        case_results.append(CaseResult(case_id=case.id, check_results=check_results))

    for result in case_results:
        for check in result.check_results:
            if check.passed:
                continue
            kind = "blocking" if check.blocking else "non-blocking"
            conditions.append(
                f"case {result.case_id}: {kind} {check.check_type} check failed"
                f" ({check.detail})"
            )
    has_blocker = any(result.has_blocking_failure for result in case_results)

    # Tier 2 — judge grading (blocked cases are not graded: garbage in).
    judge_ran = False
    if judge is not None:
        try:
            for case, result in zip(suite.cases, case_results):
                if result.has_blocking_failure:
                    continue
                result.judge = judge.grade(case, outputs_by_id[case.id].output, suite.rubric)
            judge_ran = True
        except Exception as exc:  # deterministic fallback on any judge failure
            for result in case_results:
                result.judge = None
            conditions.append(
                f"judge error ({exc}): falling back to deterministic-only scoring"
            )
    else:
        conditions.append("judge unavailable: score is deterministic-only")

    # Tier 3 gate — an uncalibrated judge can never affect the verdict.
    judge_counted = judge_ran and calibration is not None and calibration.calibrated
    if judge_ran and not judge_counted:
        conditions.append(
            "judge uncalibrated: judge scores are advisory only (ADR-001 calibration gate)"
        )

    deterministic_score = _deterministic_score(case_results)
    judge_quality = _judge_quality(case_results) if judge_counted else None

    if deterministic_score is not None and judge_quality is not None:
        score = (
            policy.WEIGHT_DETERMINISTIC * deterministic_score
            + policy.WEIGHT_JUDGE * judge_quality
        )
    elif deterministic_score is not None:
        score = deterministic_score  # judge weight renormalized away
    elif judge_quality is not None:
        score = judge_quality
        conditions.append("no deterministic checks defined: score is judge-only")
    else:
        raise ValueError(
            "no evaluable evidence: the suite defines no checks and no "
            "calibrated judge is available"
        )

    if has_blocker:
        verdict = Verdict.FAIL
    elif score >= policy.PASS_THRESHOLD:
        verdict = Verdict.PASS
    else:
        verdict = Verdict.DEGRADED

    return SuiteReport(
        suite_name=suite.name,
        verdict=verdict,
        score=round(score, 6),
        deterministic_score=round(deterministic_score, 6)
        if deterministic_score is not None
        else None,
        judge_score=round(judge_quality, 6) if judge_quality is not None else None,
        calibration=calibration if judge_counted else None,
        conditions=conditions,
        case_results=case_results,
        generated_by=f"system1+judge:{judge.name}" if judge_counted else "system1",
    )


def _outputs_by_id(suite: EvalSuite, outputs: list[CandidateOutput]) -> dict[str, CandidateOutput]:
    outputs_by_id = {output.case_id: output for output in outputs}
    if len(outputs_by_id) != len(outputs):
        raise ValueError("duplicate case_id in outputs")
    case_ids = {case.id for case in suite.cases}
    missing = sorted(case_ids - outputs_by_id.keys())
    if missing:
        raise ValueError("missing output for case(s): " + ", ".join(missing))
    unknown = sorted(outputs_by_id.keys() - case_ids)
    if unknown:
        raise ValueError("output(s) for unknown case(s): " + ", ".join(unknown))
    return outputs_by_id


def _deterministic_score(case_results: list[CaseResult]) -> float | None:
    """Pass rate over all declared checks; None when the suite has none."""
    total = sum(len(result.check_results) for result in case_results)
    if total == 0:
        return None
    passed = sum(
        check.passed for result in case_results for check in result.check_results
    )
    return passed / total


def _judge_quality(case_results: list[CaseResult]) -> float | None:
    """Mean judge overall, normalized from the policy scale to [0, 1]."""
    overalls = [result.judge.overall for result in case_results if result.judge is not None]
    if not overalls:
        return None
    span = policy.SCORE_MAX - policy.SCORE_MIN
    return sum((overall - policy.SCORE_MIN) / span for overall in overalls) / len(overalls)
