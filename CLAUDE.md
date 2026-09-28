# CLAUDE.md — EvalForge

> LLM output quality evaluator — deterministic checks, a calibration-gated LLM judge, and meta-evaluation ("judge the judge").
> The capstone of a six-project AI Test Engineering series.

## Project State — READ FIRST

- **Status: ✅ COMPLETE — all three sprints delivered (2026-07-11).**
- S1 (PR #1): this charter, ADR-001 accepted (three-tier evaluation model, calibration-gated judge), Pydantic v2 models, policy constants module, canonical scenario fixtures (PASS / FAIL / DEGRADED + golden set), 53 contract tests, zero-key CI.
- S2 (PR #2): Tier 1 deterministic checkers, Tier 2 judge layer (`LLMClient`/`Judge` Protocols, `AnthropicClient` + `LLMJudge` reference impl, scripted `FakeJudge`), Tier 3 meta-evaluation (exact/adjacent agreement, Cohen's kappa, self-consistency, `calibrate`), verdict engine enforcing ADR-001 end-to-end. 105 tests.
- S3 (PR #3): ADR-002 accepted (CLI contract — verdict-mapped exit codes 0/1/2/3, usage errors moved off argparse's 2 to avoid the FAIL collision, calibration as an explicit step and durable artifact, no tuning flags), `evalforge run` / `evalforge calibrate` CLI, CI canonical-scenario gate (the pipeline executes the installed binary against the committed manifests), senior README, bug-evidence log (#1: nullable `deterministic_score`). Suite: 121 tests, zero API keys.
- Any future work follows the same discipline: **small, session-scoped increments** — one concern per session, plan validated before code, feature branch + PR to `main`.
- Work discipline: **small, session-scoped increments** — one concern per session, plan validated before code, feature branch + PR to `main`.

## Project Goal

Answer the question every team shipping LLM features faces: **"is this model output good enough — and can we trust the thing that says so?"**

- **Tier 1 — deterministic checks** (JSON structure, contains/regex, length, forbidden content): code-based, always on, zero API keys. A failed *blocking* check ⇒ suite `FAIL` — non-compensable.
- **Tier 2 — LLM-as-judge** (env-gated System 2): rubric-based 1–5 grading with structured output. Absent ⇒ weights renormalize to deterministic-only, noted as a condition.
- **Tier 3 — meta-evaluation**: judge↔human agreement on a golden set (exact + adjacent agreement, Cohen's kappa). **An uncalibrated judge can never affect the verdict** — below the kappa floor it is demoted to advisory.

Output: an explainable `SuiteReport` (`PASS` / `DEGRADED` / `FAIL`) with per-case breakdown and conditions; CLI exit codes `0/1/2/3` (S3) so CI can gate on it.

Differentiating skills vs the five earlier projects: **evaluating probabilistic outputs and quantifying the evaluator's own reliability**. ReleaseGuard fused deterministic signals into a verdict; EvalForge measures how much an LLM signal can be trusted at all before letting it vote. Soft interop with TestScribe: sample datasets evaluate TestScribe-style enriched bug reports — no runtime coupling.

## Deliberate scope cuts (quality over quantity)

- **No Docker** (FlakySense demonstrates it), **no dashboard/API** (TestScribe has one), **no multi-agent** (FlakySense), **no RAG** (TestScribe). Deployment story = zero-key CI + canonical-scenario gate (S3).
- **No pairwise/A-B comparison** in v1 — and with it, no position-bias probes. Documented extension point.
- **Single judge implementation** (Anthropic reference impl behind a `Protocol`; scripted `FakeJudge` for tests). No judge ensembles.
- **`json_structure` check, not full JSON Schema** — parse + required keys covers the fixtures without a `jsonschema` dependency. Extension point.
- **Build-vs-adopt is an ADR, not an accident**: ADR-001 weighs promptfoo/deepeval honestly.

## Sprint Plan (3 sessions)

- **S1 — Architecture**: CLAUDE.md, scaffold, ADR-001 (evaluation model), Pydantic v2 models, policy constants, canonical fixtures + golden set, contract tests, zero-key CI.
- **S2 — Implementation**: deterministic checkers, judge layer (`Protocol` + `AnthropicJudge` + `FakeJudge`), aggregation/verdict engine, meta-evaluation metrics (agreement, kappa, consistency).
- **S3 — Integration**: CLI (`evalforge run`, `evalforge calibrate`, verdict-mapped exit codes), CI canonical-scenario gate, senior README, bug-evidence log.

## Architecture Principles (non-negotiable, series-wide)

1. **Deterministic fallback on every AI component.** Full test suite and CI run green with **zero API keys**. LLM calls are an enhancement layer.
2. **Pydantic v2** for all data models.
3. **ADRs in `docs/adr/`** are first-class deliverables. Superseded, never edited retroactively.
4. **Bugs found by tests = documented evidence.** Document (what the test caught, why it mattered) before fixing.
5. **Free/open-source only.** Solo-buildable. No paid services, no enterprise access.

## Environment

- OS: Windows, shell: PowerShell
- Python 3.14, virtualenv in `.venv` — activate: `.\.venv\Scripts\Activate.ps1`
- Run tests with `python -m pytest`, not bare `pytest`: a bare `pytest` runs from the first
  interpreter on PATH (the system Python on this machine), not from `.venv`, and nothing warns.
- CI: GitHub Actions (free tier), zero API keys, no Docker
- Console output ASCII-only (legacy Windows consoles garble non-ASCII)
- After changing `[project.scripts]`, re-run `pip install -e .` to refresh the console-script shim

## Conventions

- Codebase, comments, ADRs: **professional English** (Swiss/international market). README is bilingual, series-wide convention: `README.md` in French (primary, Suisse romande market), `README.en.md` in English — kept in sync. Conversation with the user: French.
- Commits: small, atomic, imperative English (`feat: …`, `test: …`, `docs: …`).
- Branch workflow: never commit to `main` directly. Each session works on a feature branch (`feat/…`, `docs/…`, `fix/…`) keeping its atomic commits, then opens a GitHub PR to `main`. No "Generated with Claude Code" footer in PR bodies.
- Targeted changes only — fix precisely, never rewrite broadly.
- Never scan `.venv/` or generated report folders (token waste).

## Definition of Done (per component)

- [ ] Pydantic v2 models with validation
- [ ] Deterministic behavior implemented and tested (LLM strictly optional)
- [ ] Unit tests green via `python -m pytest`
- [ ] Docstrings + entry in README architecture section
- [ ] ADR updated/added if a design decision was made
