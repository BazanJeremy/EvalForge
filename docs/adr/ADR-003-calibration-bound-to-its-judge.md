# ADR-003: A calibration report only speaks for the judge that produced it

- **Status:** Accepted
- **Date:** 2026-11-15
- **Deciders:** Jérémy Bazan
- **Supersedes:** ADR-002, on one consequence only — "The calibration report
  is a trusted input: `run` does not verify it was produced from the same
  suite/judge." The judge half of that sentence no longer holds. The rest of
  ADR-002 stands unchanged.

## Context

ADR-001's core commitment is that an uncalibrated judge can never affect the
verdict. The gate that enforces it checked two things: a calibration report
was supplied, and its `calibrated` flag was true. It did not check *whose*
calibration it was.

`CalibrationReport.generated_by` already records the name of the judge that
was measured (`metrics.calibrate` writes `judge.name` into it), and every
`Judge` exposes a `name`. Nothing compared the two. A report measured on one
judge therefore opened the gate for any other judge that happened to run:
the kappa being trusted was a measurement of a different rater.

The realistic path to that state is not malice, it is staleness. The default
judge is named after the model it calls (`anthropic:<DEFAULT_MODEL>`), and
ADR-002 makes the calibration report a durable artifact, committed once and
reused on every run. Change the default model, keep the committed report, and
the new, never-measured judge inherits the old judge's verdict rights. ADR-002
named this risk and left the check as an extension point, the operator being
responsible for re-running `evalforge calibrate`.

For a tool whose thesis is that an evaluator must earn its vote, a vote earned
by someone else is the same defect as an unearned one.

## Decision

The calibration gate opens only when the report's `generated_by` equals the
running judge's `name`. On a mismatch the judge is treated exactly as an
uncalibrated one — its grades stay on the case results as advisory data, the
score is deterministic-only — and a condition names both judges:

```
calibration mismatch: the report was produced by '<report judge>', the active
judge is '<running judge>' - judge scores are advisory only (ADR-003)
```

When a report is both another judge's and not calibrated, the mismatch is the
reason reported: that report says nothing about the running judge either way.

No change to the report format, to the CLI flags or to the exit codes.

## Options Considered

1. **Keep the report a trusted input (ADR-002 as written)** — zero code, but
   the headline guarantee then rests on operator discipline at precisely the
   moment discipline is least likely: a routine model bump. Rejected.
2. **Compare `generated_by` with `judge.name`; a mismatch demotes the judge to
   advisory** — both values already exist, so no format change and no new
   field; the failure mode is the one ADR-001 already defines for a judge that
   has not earned its vote. **Accepted.**
3. **Same comparison, but a mismatch is an error (exit `3`)** — stricter, and
   it would make the staleness impossible to miss. Rejected: it turns a model
   bump into a broken pipeline, while the deterministic verdict is still
   perfectly valid without the judge. Falling back to deterministic-only and
   saying why is the series-wide rule for every AI component.
4. **Full provenance — hash of the rubric, the suite and the judge prompt in
   the report** — the complete answer to "is this calibration still about
   what is running". It needs new fields in `CalibrationReport`, hence a
   format change and a migration story for committed reports. Out of scope
   here; still a documented extension point.

## Consequences

- A calibration report from another judge can no longer lift a verdict. Pinned
  by `test_calibration_from_another_judge_cannot_affect_the_verdict`,
  `test_calibration_mismatch_condition_names_both_judges` and, through the
  CLI, `test_calibration_from_another_judge_does_not_lift_the_verdict`. All
  three failed before the change (verdict `PASS`, exit `0`).
- A report whose `generated_by` matches the running judge behaves exactly as
  before. Committed reports need no migration.
- **The identity is a declared name, compared as a string.** It is not proof:
  a judge built on a different model but given the same `name` still matches.
  The check catches the honest mistake (a stale report), not a forged one.
- **Still not verified:** the rubric, the suite, the golden set and the judge
  prompt. A report goes stale when any of them changes, and re-running
  `evalforge calibrate` remains the operator's responsibility — ADR-002's last
  consequence stands for those.
- The console "Signals" line keeps its existing wording for an advisory judge
  (`advisory only (uncalibrated - ADR-001 gate)`) in the mismatch case too;
  the precise reason is the condition listed just below it.
