"""Every ADR-001 number, single source of truth.

No other module may hard-code an evaluation threshold. Changing a value
here is a governance decision that goes through a superseding ADR, not a
code tweak (same discipline as ReleaseGuard's policy module).
"""

# Judge rubric scale (Tier 2): integer score per criterion.
SCORE_MIN = 1
SCORE_MAX = 5

# Suite score weights. They renormalize to deterministic-only when the
# judge is absent or uncalibrated (ADR-001 missing-signal pattern).
WEIGHT_DETERMINISTIC = 0.60
WEIGHT_JUDGE = 0.40

# Verdict threshold: absent blockers, score >= PASS_THRESHOLD => PASS,
# otherwise DEGRADED. FAIL always requires an identifiable blocker.
PASS_THRESHOLD = 0.85

# Calibration gate (Tier 3): judge scores may enter the verdict only when
# Cohen's kappa on the golden set reaches this floor ("moderate" agreement
# per Landis & Koch) over at least MIN_GOLDEN_CASES labeled cases.
KAPPA_FLOOR = 0.40
MIN_GOLDEN_CASES = 10

# Adjacent agreement counts |judge - human| <= ADJACENT_DISTANCE.
ADJACENT_DISTANCE = 1

# CLI exit codes (S3 contract): verdict-mapped, ReleaseGuard ADR-003 style.
EXIT_PASS = 0
EXIT_DEGRADED = 1
EXIT_FAIL = 2
EXIT_ERROR = 3
