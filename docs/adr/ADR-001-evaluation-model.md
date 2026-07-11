# ADR-001: Evaluation model — deterministic checks, calibration-gated judge, meta-evaluation

- **Status:** Accepted
- **Date:** 2026-07-10
- **Deciders:** Jérémy Bazan

## Context

LLM outputs are probabilistic: the same prompt can yield different answers, and "looks good" is not a quality gate. The industry's default fix — **LLM-as-judge** — grades outputs with another model, but an unvalidated judge is just a second opinion of unknown quality stacked on the first. Known failure modes (verbosity bias, self-preference, scale drift) go unmeasured unless the judge itself is evaluated.

EvalForge must produce an explainable, CI-gateable verdict on a batch of LLM outputs while honoring the portfolio-wide constraint: **the full test suite and CI run green with zero API keys**, and no component is trusted blindly.

## Decision

A **three-tier evaluation model** where each tier has a distinct epistemic status:

### Tier 1 — Deterministic checks (always on)

Code-based checks per case: `json_structure` (parses + required keys), `contains`, `regex`, `length`, `forbidden`. A check may be declared **`blocking`**. Any failed blocking check ⇒ suite verdict `FAIL`. Same non-compensability principle as ReleaseGuard ADR-001: a hard defect (malformed JSON, forbidden content) must not be tradable against good average quality elsewhere.

### Tier 2 — LLM-as-judge (env-gated System 2)

Rubric-based grading: each criterion scored on a **1–5 integer scale**, structured output, per-case rationale. Client behind a `Protocol` (same pattern as FlakySense ADR-004 / ReleaseGuard `llm.py`): activation requires `ANTHROPIC_API_KEY` + the `[llm]` extra; tests use a scripted `FakeJudge`. Judge absent ⇒ score weights renormalize to deterministic-only and the absence is appended to the conditions list (ReleaseGuard's missing-signal pattern).

### Tier 3 — Meta-evaluation ("judge the judge")

Against a **golden set** of human-labeled cases (n ≥ `MIN_GOLDEN_CASES` = 10), compute judge↔human agreement: exact agreement, adjacent agreement (|judge − human| ≤ 1), and **Cohen's kappa** (chance-corrected).

**Calibration gate — the core commitment: an uncalibrated judge can never affect the verdict.** Judge scores enter the suite score only when kappa ≥ `KAPPA_FLOOR` = 0.4 ("moderate" per Landis & Koch). Below the floor, judge output is demoted to advisory — reported for transparency, excluded from scoring — and a condition is added. This is P6's parallel to P5's "hard verdicts never depend on an LLM".

### Scoring and verdict

`score = 0.6 · deterministic_pass_rate + 0.4 · judge_quality` — judge quality is the mean overall judge score normalized from [1, 5] to [0, 1]; weights renormalize to deterministic-only when the judge is absent or uncalibrated.

- Any failed blocking check ⇒ `FAIL`.
- Otherwise `score ≥ 0.85` ⇒ `PASS`, else `DEGRADED` with a machine-generated conditions list.
- **`FAIL` requires an identifiable blocker.** The score alone can only choose between `PASS` and `DEGRADED` — low quality without a named hard defect is a degraded ship with listed risks, not a veto.

Every number above lives in `policy.py` — nothing else may hard-code a threshold.

### Output contract

`SuiteReport { verdict, score, deterministic_score, judge_score?, calibration?, conditions[], case_results[], generated_by }`.
CLI exit codes (S3): `0` PASS · `1` DEGRADED · `2` FAIL · `3` error.

## Options Considered

1. **Pure LLM-as-judge** — maximum flexibility, minimum ceremony; but the judge's reliability is assumed, not measured, CI would need API keys, and runs are non-reproducible. Rejected.
2. **Adopt an existing harness (promptfoo, deepeval, OpenAI Evals)** — mature, feature-rich. Rejected *here* for two honest reasons: the portfolio goal is demonstrating evaluation engineering from first principles, and calibration-gating the judge against human labels is not a first-class primitive in these tools. In a real team, adopting one and layering calibration on top is often the right call — this trade-off is deliberate and should be stated in interviews, not hidden.
3. **Three-tier model with calibration-gated judge** — deterministic core, optional judge that must *earn* verdict rights on a golden set. **Accepted.**

## Consequences

- Reproducible zero-key core: Tier 1 + verdict logic are fully deterministic; every verdict is auditable from the report alone.
- The judge's reliability becomes a **measured quantity** (kappa, agreement) instead of an assumption — the differentiating claim of this project.
- Cost: the golden set requires human labeling effort — bounded at `MIN_GOLDEN_CASES` = 10; kappa on small n is noisy, which is why adjacent agreement is reported alongside and thresholds are tunable only via a superseding ADR.
- Deliberate v1 cuts: no pairwise/A-B comparison (and no position-bias probes), single judge implementation, `json_structure` instead of full JSON Schema.
- Follow-up: S2 implements checkers, judge layer, and metrics; S3 exposes the CLI contract and the CI canonical-scenario gate.
