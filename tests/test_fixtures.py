"""Integrity contracts for the canonical scenario fixtures and the golden set.

These tests pin the *data* side of the ADR-001 contract: every fixture must
load through the Pydantic models, outputs must map 1:1 to suite cases, and
each scenario must be structurally able to produce its declared verdict.
Exact verdicts are pinned end-to-end by the S2/S3 evaluator tests; here we
only emulate the blocking-check semantics as a data guard.
"""

import json

from conftest import SAMPLES_DIR, load_json, load_jsonl

from evalforge import policy
from evalforge.models import CandidateOutput, EvalSuite, GoldenSet, Verdict

VERDICT_TO_EXIT = {
    Verdict.PASS: policy.EXIT_PASS,
    Verdict.DEGRADED: policy.EXIT_DEGRADED,
    Verdict.FAIL: policy.EXIT_FAIL,
}


def blocking_checks_satisfied(output: str, case) -> bool:
    """Minimal emulation of blocking-check semantics, as a fixture data guard."""
    for check in case.checks:
        if not check.blocking:
            continue
        if check.type == "json_structure":
            try:
                payload = json.loads(output)
            except json.JSONDecodeError:
                return False
            if not isinstance(payload, dict):
                return False
            if any(key not in payload for key in check.required_keys):
                return False
        elif check.type == "forbidden":
            lowered = output.lower()
            if any(value.lower() in lowered for value in check.values):
                return False
    return True


# ------------------------------------------------------------- scenarios


def test_scenario_loads_through_models(scenario_dir):
    suite = EvalSuite.model_validate(load_json(scenario_dir / "suite.json"))
    outputs = [CandidateOutput.model_validate(line) for line in load_jsonl(scenario_dir / "outputs.jsonl")]
    assert suite.cases and outputs


def test_scenario_outputs_map_one_to_one_to_cases(scenario_dir):
    suite = EvalSuite.model_validate(load_json(scenario_dir / "suite.json"))
    outputs = [CandidateOutput.model_validate(line) for line in load_jsonl(scenario_dir / "outputs.jsonl")]
    assert {o.case_id for o in outputs} == {c.id for c in suite.cases}
    assert len(outputs) == len(suite.cases)


def test_scenario_manifest_declares_valid_expectation(scenario_dir):
    manifest = load_json(scenario_dir / "manifest.json")
    verdict = Verdict(manifest["expected_verdict"])
    assert manifest["expected_exit"] == VERDICT_TO_EXIT[verdict]


def test_scenario_fail_contains_a_blocking_violation():
    scenario = SAMPLES_DIR / "scenario_fail"
    suite = EvalSuite.model_validate(load_json(scenario / "suite.json"))
    outputs = {o.case_id: o for o in map(CandidateOutput.model_validate, load_jsonl(scenario / "outputs.jsonl"))}
    violations = [
        case.id for case in suite.cases if not blocking_checks_satisfied(outputs[case.id].output, case)
    ]
    assert violations, "scenario_fail must contain at least one blocking-check violation"


def test_non_fail_scenarios_satisfy_every_blocking_check():
    """PASS and DEGRADED scenarios must be structurally unable to FAIL."""
    for name in ("scenario_pass", "scenario_degraded"):
        scenario = SAMPLES_DIR / name
        suite = EvalSuite.model_validate(load_json(scenario / "suite.json"))
        outputs = {
            o.case_id: o for o in map(CandidateOutput.model_validate, load_jsonl(scenario / "outputs.jsonl"))
        }
        for case in suite.cases:
            assert blocking_checks_satisfied(outputs[case.id].output, case), (
                f"{name}/{case.id} violates a blocking check"
            )


def test_every_scenario_declares_blocking_gates(scenario_dir):
    suite = EvalSuite.model_validate(load_json(scenario_dir / "suite.json"))
    for case in suite.cases:
        assert any(check.blocking for check in case.checks), (
            f"{case.id} declares no blocking check: FAIL would be unreachable"
        )


# ------------------------------------------------------------- golden set


def test_golden_set_loads_and_is_large_enough(golden_dir):
    suite = EvalSuite.model_validate(load_json(golden_dir / "suite.json"))
    golden = GoldenSet.model_validate(load_json(golden_dir / "labels.json"))
    outputs = [CandidateOutput.model_validate(line) for line in load_jsonl(golden_dir / "outputs.jsonl")]

    case_ids = {c.id for c in suite.cases}
    assert {label.case_id for label in golden.labels} == case_ids
    assert {o.case_id for o in outputs} == case_ids
    assert len(golden.labels) >= policy.MIN_GOLDEN_CASES


def test_golden_scores_span_the_scale(golden_dir):
    """Kappa is meaningless on a constant label distribution."""
    golden = GoldenSet.model_validate(load_json(golden_dir / "labels.json"))
    distinct = {label.score for label in golden.labels}
    assert len(distinct) >= 3
    assert min(distinct) == policy.SCORE_MIN
    assert max(distinct) == policy.SCORE_MAX


def test_golden_outputs_are_deliberately_uneven(golden_dir):
    """Low-labeled outputs exist so a sycophantic judge scores badly on kappa."""
    golden = GoldenSet.model_validate(load_json(golden_dir / "labels.json"))
    low = [label for label in golden.labels if label.score <= 2]
    assert len(low) >= 3
