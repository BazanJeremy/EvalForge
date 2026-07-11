# Bug Evidence

Portfolio principle #4: **bugs found by the project's own tests and demo runs
are assets.** Each entry documents what was caught, by what, and why it
mattered — written before the fix landed.

## #1 — `deterministic_score: 0.0` was ambiguous for checkless suites

- **Caught by:** the S3 dogfood review of the CLI rendering (before any S3
  commit), while tracing what `evalforge run` would print for a judge-only
  suite — the golden-set shape, which defines no deterministic checks.
- **Symptom:** the evaluator coerced "no checks defined" to
  `deterministic_score = 0.0` in the serialized `SuiteReport`, because the
  model required a float. `0.0` is also the value for "every declared check
  failed" — two opposite realities, one number.
- **Why it mattered:** the JSON report is EvalForge's contract with CI and
  dashboards. A consumer reading `0.0` would conclude total deterministic
  failure when the truth is "no deterministic evidence exists". For a tool
  whose whole thesis is *quality signals must state their own reliability*,
  lying by omission of that distinction is a core defect, not cosmetics.
- **Fix:** `SuiteReport.deterministic_score` became `float | None` with the
  semantics documented in-model (`None` = no checks defined); the evaluator
  emits `None` and the CLI renders `n/a (suite defines no checks:
  judge-only)`. Pinned by `test_no_checks_with_calibrated_judge_scores_judge_only`.
