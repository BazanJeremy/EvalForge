"""Pin every ADR-001 number. A failing test here means either a drive-by
threshold change (revert it) or a deliberate one (supersede ADR-001 first).
"""

from evalforge import policy


def test_judge_scale():
    assert policy.SCORE_MIN == 1
    assert policy.SCORE_MAX == 5


def test_score_weights():
    assert policy.WEIGHT_DETERMINISTIC == 0.60
    assert policy.WEIGHT_JUDGE == 0.40


def test_weights_sum_to_one():
    assert policy.WEIGHT_DETERMINISTIC + policy.WEIGHT_JUDGE == 1.0


def test_pass_threshold():
    assert policy.PASS_THRESHOLD == 0.85


def test_calibration_gate():
    assert policy.KAPPA_FLOOR == 0.40
    assert policy.MIN_GOLDEN_CASES == 10
    assert policy.ADJACENT_DISTANCE == 1


def test_exit_codes_are_verdict_mapped():
    assert policy.EXIT_PASS == 0
    assert policy.EXIT_DEGRADED == 1
    assert policy.EXIT_FAIL == 2
    assert policy.EXIT_ERROR == 3
