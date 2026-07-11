"""Command-line interface (ADR-002): verdict-mapped exit codes for CI.

Two subcommands:
  evalforge run       — evaluate candidate outputs against a suite
  evalforge calibrate — measure judge/human agreement on a golden set

Exit codes: 0 PASS/calibrated, 1 DEGRADED/uncalibrated, 2 FAIL, 3 error.
Usage errors exit 3 (argparse's default of 2 would collide with FAIL).
Console output is ASCII-only by convention.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable

from evalforge import policy
from evalforge.evaluator import evaluate_suite
from evalforge.judge import Judge, judge_from_env
from evalforge.metrics import calibrate
from evalforge.models import (
    CalibrationReport,
    CandidateOutput,
    CaseResult,
    EvalSuite,
    GoldenSet,
    SuiteReport,
    Verdict,
)

EXIT_BY_VERDICT = {
    Verdict.PASS: policy.EXIT_PASS,
    Verdict.DEGRADED: policy.EXIT_DEGRADED,
    Verdict.FAIL: policy.EXIT_FAIL,
}


class _Parser(argparse.ArgumentParser):
    """ArgumentParser whose usage errors exit EXIT_ERROR instead of 2 (ADR-002)."""

    def error(self, message: str) -> None:  # type: ignore[override]
        self.print_usage(sys.stderr)
        print(f"error: {message}", file=sys.stderr)
        raise SystemExit(policy.EXIT_ERROR)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(
        prog="evalforge",
        description="LLM output quality evaluator (deterministic checks, "
        "calibration-gated judge, meta-evaluation).",
    )
    subparsers = parser.add_subparsers(dest="command", required=True, parser_class=_Parser)

    run = subparsers.add_parser("run", help="evaluate candidate outputs against a suite")
    run.add_argument("--suite", required=True, help="eval suite JSON file")
    run.add_argument("--outputs", required=True, help="candidate outputs JSONL file")
    run.add_argument(
        "--calibration",
        help="calibration report JSON (from 'evalforge calibrate'); "
        "without it a present judge stays advisory",
    )
    run.add_argument("--report", help="write the full SuiteReport JSON to this path")

    cal = subparsers.add_parser(
        "calibrate", help="measure judge/human agreement on a golden set"
    )
    cal.add_argument("--suite", required=True, help="golden suite JSON file")
    cal.add_argument("--outputs", required=True, help="golden candidate outputs JSONL file")
    cal.add_argument("--labels", required=True, help="human labels JSON file")
    cal.add_argument("--out", required=True, help="write the CalibrationReport JSON here")

    return parser


def main(
    argv: list[str] | None = None,
    judge_provider: Callable[[], Judge | None] = judge_from_env,
) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "run":
            return _cmd_run(args, judge_provider)
        return _cmd_calibrate(args, judge_provider)
    except Exception as exc:  # every operational failure maps to EXIT_ERROR
        print(f"error: {exc}", file=sys.stderr)
        return policy.EXIT_ERROR


# ------------------------------------------------------------------ commands


def _cmd_run(args: argparse.Namespace, judge_provider: Callable[[], Judge | None]) -> int:
    suite = _load_suite(args.suite)
    outputs = _load_outputs(args.outputs)
    calibration = _load_calibration(args.calibration) if args.calibration else None
    report = evaluate_suite(suite, outputs, judge=judge_provider(), calibration=calibration)
    print(_render_report(report))
    if args.report:
        Path(args.report).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    return EXIT_BY_VERDICT[report.verdict]


def _cmd_calibrate(
    args: argparse.Namespace, judge_provider: Callable[[], Judge | None]
) -> int:
    judge = judge_provider()
    if judge is None:
        print(
            "error: calibration requires the LLM judge - set ANTHROPIC_API_KEY "
            "and install the llm extra (pip install -e .[llm])",
            file=sys.stderr,
        )
        return policy.EXIT_ERROR
    suite = _load_suite(args.suite)
    outputs = _load_outputs(args.outputs)
    labels = GoldenSet.model_validate(_load_json(args.labels))
    report = calibrate(suite, outputs, labels, judge)
    print(_render_calibration(report))
    Path(args.out).write_text(report.model_dump_json(indent=2), encoding="utf-8")
    print(f"Calibration report written to {args.out}")
    return policy.EXIT_PASS if report.calibrated else policy.EXIT_DEGRADED


# ------------------------------------------------------------------- loaders


def _load_json(path: str) -> object:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def _load_suite(path: str) -> EvalSuite:
    return EvalSuite.model_validate(_load_json(path))


def _load_outputs(path: str) -> list[CandidateOutput]:
    return [
        CandidateOutput.model_validate(json.loads(line))
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def _load_calibration(path: str) -> CalibrationReport:
    return CalibrationReport.model_validate(_load_json(path))


# ----------------------------------------------------------------- rendering


def _case_status(result: CaseResult) -> str:
    if result.has_blocking_failure:
        return "fail "
    if any(not check.passed for check in result.check_results):
        return "warn "
    return "pass "


def _render_report(report: SuiteReport) -> str:
    lines = [f"EvalForge verdict: {report.verdict.value} (score {report.score:.2f})", ""]

    lines.append("Cases:")
    for result in report.case_results:
        passed = sum(check.passed for check in result.check_results)
        total = len(result.check_results)
        line = f"  [{_case_status(result)}] {result.case_id}  {passed}/{total} checks"
        if result.judge is not None:
            line += f", judge {result.judge.overall:.1f}/{policy.SCORE_MAX}"
        lines.append(line)

    lines += ["", "Signals:"]
    total_checks = sum(len(r.check_results) for r in report.case_results)
    if report.deterministic_score is not None:
        lines.append(
            f"  deterministic  {report.deterministic_score:.2f}"
            f"  (weight {policy.WEIGHT_DETERMINISTIC:.2f}, {total_checks} checks)"
        )
    else:
        lines.append("  deterministic  n/a (suite defines no checks: judge-only)")
    if report.judge_score is not None and report.calibration is not None:
        lines.append(
            f"  judge          {report.judge_score:.2f}"
            f"  (weight {policy.WEIGHT_JUDGE:.2f}, calibrated: kappa "
            f"{report.calibration.cohen_kappa:.2f} on {report.calibration.n_cases} cases)"
        )
    elif any(r.judge is not None for r in report.case_results):
        lines.append("  judge          advisory only (uncalibrated - ADR-001 gate)")
    else:
        lines.append("  judge          absent (weights renormalized to deterministic-only)")

    if report.conditions:
        lines += ["", "Conditions:"]
        lines += [f"  - {condition}" for condition in report.conditions]

    lines += ["", f"Generated by: {report.generated_by}"]
    return "\n".join(lines)


def _render_calibration(report: CalibrationReport) -> str:
    headline = "CALIBRATED" if report.calibrated else "NOT CALIBRATED (judge stays advisory)"
    return "\n".join(
        [
            f"EvalForge calibration: {headline}",
            f"  cases:              {report.n_cases} (minimum {policy.MIN_GOLDEN_CASES})",
            f"  exact agreement:    {report.exact_agreement:.2f}",
            f"  adjacent agreement: {report.adjacent_agreement:.2f}",
            f"  cohen kappa:        {report.cohen_kappa:.2f} (floor {policy.KAPPA_FLOOR:.2f})",
            f"  judge:              {report.generated_by}",
        ]
    )


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
