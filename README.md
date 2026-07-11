# EvalForge

> LLM output quality evaluator — deterministic checks, a calibration-gated LLM judge, and meta-evaluation ("judge the judge").

**Status: 🚧 S2 — Implementation delivered.** S1 shipped the charter ([CLAUDE.md](CLAUDE.md)), [ADR-001](docs/adr/ADR-001-evaluation-model.md), Pydantic v2 contract models, canonical fixtures and zero-key CI. S2 adds the three tiers themselves: deterministic checkers, the env-gated judge layer, meta-evaluation metrics, and the verdict engine — 105 tests, still zero API keys. S3 (CLI + CI gate + full README) follows.

## The idea in three tiers

1. **Deterministic checks** (JSON structure, contains/regex, length, forbidden content) — always on, zero API keys. A failed *blocking* check ⇒ `FAIL`, non-compensable.
2. **LLM-as-judge** (env-gated) — rubric-based 1–5 grading with structured output. Absent ⇒ the score renormalizes to deterministic-only, noted as a condition.
3. **Meta-evaluation** — the judge must *earn* verdict rights on a human-labeled golden set (exact + adjacent agreement, Cohen's kappa). **An uncalibrated judge can never affect the verdict** — that invariant is enforced inside the Pydantic models, not just in the evaluator.

## Try it (S1: models, fixtures, contract tests)

```powershell
git clone https://github.com/BazanJeremy/EvalForge.git
cd EvalForge
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
python -m pytest        # zero API keys required
```

## Project structure

```
src/evalforge/
  models.py     # Pydantic v2 contract models; ADR-001 invariants enforced in-model
  policy.py     # every ADR-001 number, single source
  checkers.py   # Tier 1 deterministic checks (json_structure, contains, regex, length, forbidden)
  judge.py      # Tier 2 env-gated LLM judge (LLMClient/Judge Protocols, Anthropic impl, FakeJudge)
  metrics.py    # Tier 3 meta-evaluation (exact/adjacent agreement, Cohen's kappa, self-consistency, calibrate)
  evaluator.py  # verdict engine: blocking gates -> calibration-gated score -> PASS/DEGRADED/FAIL
data/samples/   # canonical scenarios (PASS / FAIL / DEGRADED) + human-labeled golden set
docs/adr/       # architecture decision records
tests/          # 105 tests: contracts, checkers, judge parsing, metrics, end-to-end verdicts
```

## Portfolio context

P6 of a 6-project AI Test Engineering portfolio — the final capstone. [ReleaseGuard (P5)](https://github.com/BazanJeremy/ReleaseGuard) fused deterministic quality signals into a verdict; EvalForge answers the next question: **how much can an LLM signal be trusted before letting it vote?** Sample datasets evaluate [TestScribe](https://github.com/BazanJeremy/testscribe)-style enriched bug reports — soft interop, no runtime coupling.

The full senior README (architecture diagram, CLI contract, bug-evidence log) lands in S3.
