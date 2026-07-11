"""Tests for the ADR-002 CLI contract: exit codes, ASCII output, artifacts."""

import json

import pytest

from conftest import SAMPLES_DIR, load_json

from evalforge import policy
from evalforge.cli import main
from evalforge.judge import FakeJudge
from evalforge.models import CalibrationReport, SuiteReport, Verdict

NO_JUDGE = lambda: None  # noqa: E731 - zero-key judge provider

LIFT_SUITE = {
    "name": "lift-demo",
    "rubric": {"criteria": [{"name": "quality", "description": "Overall quality."}]},
    "cases": [
        {
            "id": "C-1",
            "input": "raw report one",
            "checks": [
                {"type": "json_structure", "required_keys": ["title"], "blocking": True},
                {"type": "length", "min_chars": 5},
            ],
        },
        {
            "id": "C-2",
            "input": "raw report two",
            "checks": [
                {"type": "json_structure", "required_keys": ["title"], "blocking": True},
                {"type": "contains", "value": "firefox"},
            ],
        },
    ],
}
LIFT_OUTPUTS = [
    {"case_id": "C-1", "output": '{"title": "Pump alarm silent on occlusion"}'},
    {"case_id": "C-2", "output": '{"title": "Login button unresponsive"}'},
]
CALIBRATION = {
    "n_cases": 12,
    "exact_agreement": 0.5,
    "adjacent_agreement": 0.9,
    "cohen_kappa": 0.62,
    "calibrated": True,
    "generated_by": "fake-judge",
}


def scenario_args(scenario_dir) -> list[str]:
    return [
        "run",
        "--suite", str(scenario_dir / "suite.json"),
        "--outputs", str(scenario_dir / "outputs.jsonl"),
    ]


def write_lift_files(tmp_path) -> list[str]:
    suite = tmp_path / "suite.json"
    outputs = tmp_path / "outputs.jsonl"
    suite.write_text(json.dumps(LIFT_SUITE), encoding="utf-8")
    outputs.write_text(
        "\n".join(json.dumps(o) for o in LIFT_OUTPUTS), encoding="utf-8"
    )
    return ["run", "--suite", str(suite), "--outputs", str(outputs)]


def perfect_judge() -> FakeJudge:
    return FakeJudge({"C-1": {"quality": 5}, "C-2": {"quality": 5}})


# ----------------------------------------------------- exit-code contract


def test_canonical_scenarios_exit_with_their_declared_code(scenario_dir, capsys):
    expected = load_json(scenario_dir / "manifest.json")["expected_exit"]
    assert main(scenario_args(scenario_dir), judge_provider=NO_JUDGE) == expected


def test_console_output_is_ascii_only(scenario_dir, capsys):
    """Pins the portfolio convention: legacy Windows consoles garble non-ASCII."""
    main(scenario_args(scenario_dir), judge_provider=NO_JUDGE)
    out = capsys.readouterr().out
    assert out and out.isascii()


def test_run_prints_verdict_cases_and_conditions(capsys):
    scenario = SAMPLES_DIR / "scenario_fail"
    main(scenario_args(scenario), judge_provider=NO_JUDGE)
    out = capsys.readouterr().out
    assert "EvalForge verdict: FAIL" in out
    assert "[fail ] BR-002" in out
    assert "Conditions:" in out


def test_usage_error_exits_3_not_argparses_2():
    with pytest.raises(SystemExit) as excinfo:
        main(["run", "--suite", "only-half-the-args.json"], judge_provider=NO_JUDGE)
    assert excinfo.value.code == policy.EXIT_ERROR


def test_missing_file_exits_3_with_message_on_stderr(capsys):
    code = main(
        ["run", "--suite", "no-such-file.json", "--outputs", "also-missing.jsonl"],
        judge_provider=NO_JUDGE,
    )
    assert code == policy.EXIT_ERROR
    assert "error:" in capsys.readouterr().err


def test_malformed_suite_exits_3(tmp_path, capsys):
    bad = tmp_path / "suite.json"
    bad.write_text("{not json", encoding="utf-8")
    code = main(
        ["run", "--suite", str(bad), "--outputs", str(bad)], judge_provider=NO_JUDGE
    )
    assert code == policy.EXIT_ERROR


# ------------------------------------------------------------- report file


def test_report_flag_writes_a_round_trippable_suite_report(tmp_path, capsys):
    report_path = tmp_path / "report.json"
    args = scenario_args(SAMPLES_DIR / "scenario_degraded") + ["--report", str(report_path)]
    main(args, judge_provider=NO_JUDGE)
    report = SuiteReport.model_validate_json(report_path.read_text(encoding="utf-8"))
    assert report.verdict is Verdict.DEGRADED


# ------------------------------------------- calibration gate through the CLI


def test_calibrated_judge_lifts_the_verdict_end_to_end(tmp_path, capsys):
    args = write_lift_files(tmp_path)
    calibration = tmp_path / "calibration.json"
    calibration.write_text(json.dumps(CALIBRATION), encoding="utf-8")

    without = main(list(args), judge_provider=perfect_judge)
    assert without == policy.EXIT_DEGRADED  # judge present but advisory

    with_cal = main(args + ["--calibration", str(calibration)], judge_provider=perfect_judge)
    assert with_cal == policy.EXIT_PASS
    out = capsys.readouterr().out
    assert "calibrated: kappa 0.62" in out


def test_advisory_judge_is_labeled_in_the_signals(tmp_path, capsys):
    main(write_lift_files(tmp_path), judge_provider=perfect_judge)
    assert "advisory only" in capsys.readouterr().out


# ----------------------------------------------------------------- calibrate


def golden_calibrate_args(tmp_path) -> list[str]:
    golden = SAMPLES_DIR / "golden"
    return [
        "calibrate",
        "--suite", str(golden / "suite.json"),
        "--outputs", str(golden / "outputs.jsonl"),
        "--labels", str(golden / "labels.json"),
        "--out", str(tmp_path / "calibration.json"),
    ]


def accurate_golden_judge() -> FakeJudge:
    labels = load_json(SAMPLES_DIR / "golden" / "labels.json")["labels"]
    criteria = [c["name"] for c in load_json(SAMPLES_DIR / "golden" / "suite.json")["rubric"]["criteria"]]
    return FakeJudge(
        {label["case_id"]: {name: label["score"] for name in criteria} for label in labels}
    )


def test_calibrate_requires_the_judge(tmp_path, capsys):
    code = main(golden_calibrate_args(tmp_path), judge_provider=NO_JUDGE)
    assert code == policy.EXIT_ERROR
    assert "ANTHROPIC_API_KEY" in capsys.readouterr().err


def test_calibrate_writes_report_and_exits_0_when_calibrated(tmp_path, capsys):
    code = main(golden_calibrate_args(tmp_path), judge_provider=accurate_golden_judge)
    assert code == policy.EXIT_PASS
    report = CalibrationReport.model_validate_json(
        (tmp_path / "calibration.json").read_text(encoding="utf-8")
    )
    assert report.calibrated and report.cohen_kappa == 1.0
    out = capsys.readouterr().out
    assert "CALIBRATED" in out and out.isascii()


def test_calibrate_exits_1_when_judge_stays_advisory(tmp_path, capsys):
    labels = load_json(SAMPLES_DIR / "golden" / "labels.json")["labels"]
    criteria = [c["name"] for c in load_json(SAMPLES_DIR / "golden" / "suite.json")["rubric"]["criteria"]]
    sycophant = FakeJudge(
        {label["case_id"]: {name: policy.SCORE_MAX for name in criteria} for label in labels}
    )
    code = main(golden_calibrate_args(tmp_path), judge_provider=lambda: sycophant)
    assert code == policy.EXIT_DEGRADED
    assert "NOT CALIBRATED" in capsys.readouterr().out
