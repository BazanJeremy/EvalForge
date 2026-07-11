# ADR-002: CLI contract — verdict-mapped exit codes, explicit calibration step

- **Status:** Accepted
- **Date:** 2026-07-11
- **Deciders:** Jérémy Bazan

## Context

EvalForge's deployment story is CI: a pipeline must be able to gate on the
suite verdict without parsing text. That requires a stable exit-code contract
and a CLI whose failure modes cannot be confused with verdicts. Two forces
shape the design:

1. `argparse` exits usage errors with code 2 — which would collide with the
   `FAIL` verdict (same trap ReleaseGuard ADR-003 documented).
2. Calibration (Tier 3) runs the LLM judge over the whole golden set. That is
   an expensive, key-requiring step which produces a durable measurement — it
   must not run implicitly inside every evaluation.

## Decision

Two subcommands with a shared exit-code contract:

### `evalforge run --suite s.json --outputs o.jsonl [--calibration c.json] [--report r.json]`

- Evaluates the suite (ADR-001 engine). The judge activates from the
  environment (`ANTHROPIC_API_KEY` + `[llm]` extra) — never from a flag.
- `--calibration` takes the JSON report written by `evalforge calibrate`;
  without it a present judge stays advisory (the calibration gate).
- `--report` writes the full `SuiteReport` as JSON for machines; the console
  gets a human-readable, **ASCII-only** breakdown.
- Exit codes: `0` PASS · `1` DEGRADED · `2` FAIL · `3` error.

### `evalforge calibrate --suite s.json --outputs o.jsonl --labels l.json --out c.json`

- Grades the golden set with the env-gated judge and writes the
  `CalibrationReport` JSON that `run --calibration` consumes.
- Requires the judge: without it, exit `3` with an actionable message.
- Exit codes: `0` calibrated · `1` not calibrated (advisory judge) · `3` error.

### Shared rules

- **Usage errors exit `3`, not argparse's default `2`** — a typo in a flag
  must never read as a FAIL verdict in CI.
- Console output is ASCII-only (legacy Windows consoles garble non-ASCII).
- **No tuning flags in v1** — stricter than ReleaseGuard ADR-003 (which
  exposed threshold flags): EvalForge's thresholds *are* the product's core
  promise (the calibration gate), so every number stays in `policy.py` and
  changes only through a superseding ADR. Per-run overrides are a documented
  extension point, not a v1 feature.

## Options Considered

1. **Single command, calibration inline via `--labels`** — fewer commands, but
   hides an expensive LLM step inside every run, conflates measurement with
   evaluation, and re-spends API budget on every CI run. Rejected.
2. **Two subcommands, calibration as a durable artifact** — calibrate once,
   commit the report, gate every run against it for free. **Accepted.**
3. **argparse defaults for usage errors** — exit 2 collides with FAIL; a CI
   pipeline would treat a typo as a failed quality gate. Rejected.

## Consequences

- CI can gate with `evalforge run ... ; test $? -le 1` (or stricter).
- The calibration report is a trusted input: `run` does not verify it was
  produced from the same suite/judge. Provenance metadata (suite hash, judge
  id verification) is a documented extension point.
- A calibration report becomes stale when the judge model or rubric changes;
  re-running `evalforge calibrate` is the operator's responsibility (noted in
  the README).
