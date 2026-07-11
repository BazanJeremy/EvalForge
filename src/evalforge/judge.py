"""Tier 2 LLM-as-judge layer (env-gated, ADR-001).

Same discipline as ReleaseGuard's llm.py: the verdict never depends on this
module being functional. Activation requires ``ANTHROPIC_API_KEY`` plus the
optional ``llm`` dependency group (``pip install -e .[llm]``); tests and
zero-key runs use the scripted ``FakeJudge``.
"""

from __future__ import annotations

import json
import os
import re
from typing import Protocol

from evalforge import policy
from evalforge.models import EvalCase, JudgeScore, Rubric

DEFAULT_MODEL = "claude-opus-4-8"


class LLMClient(Protocol):
    """Minimal completion surface the LLM judge depends on."""

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        """Return the model's text response; ``schema`` requests strict JSON."""
        ...


class AnthropicClient:
    """Reference ``LLMClient`` backed by the Anthropic Messages API."""

    def __init__(self, model: str = DEFAULT_MODEL, max_tokens: int = 16000) -> None:
        import anthropic  # deferred import: optional dependency

        self._client = anthropic.Anthropic()
        self._model = model
        self._max_tokens = max_tokens

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        kwargs: dict = {}
        if schema is not None:
            kwargs["output_config"] = {"format": {"type": "json_schema", "schema": schema}}
        response = self._client.messages.create(
            model=self._model,
            max_tokens=self._max_tokens,
            system=system,
            thinking={"type": "adaptive"},
            messages=[{"role": "user", "content": user}],
            **kwargs,
        )
        if response.stop_reason == "refusal":
            raise RuntimeError("LLM declined the request (stop_reason=refusal)")
        text = "".join(
            block.text for block in response.content if block.type == "text"
        ).strip()
        if not text:
            raise RuntimeError("LLM returned an empty text response")
        return text


class Judge(Protocol):
    """Grading surface the evaluator and calibration depend on."""

    name: str

    def grade(self, case: EvalCase, output: str, rubric: Rubric) -> JudgeScore:
        """Score one candidate output against the rubric."""
        ...


class FakeJudge:
    """Scripted judge for tests and zero-key demos.

    ``scores`` maps case id to per-criterion integer scores. Grading a case
    with no script entry raises, so a test cannot silently grade on defaults.
    """

    def __init__(
        self,
        scores: dict[str, dict[str, int]],
        rationale: str = "scripted verdict",
        name: str = "fake-judge",
    ) -> None:
        self._scores = scores
        self._rationale = rationale
        self.name = name
        self.calls: list[str] = []

    def grade(self, case: EvalCase, output: str, rubric: Rubric) -> JudgeScore:
        self.calls.append(case.id)
        if case.id not in self._scores:
            raise KeyError(f"FakeJudge has no scripted scores for case '{case.id}'")
        criterion_scores = self._scores[case.id]
        return _build_judge_score(criterion_scores, self._rationale, rubric, self.name)


class LLMJudge:
    """Rubric-based grader on top of any ``LLMClient``."""

    def __init__(self, client: LLMClient, name: str = f"anthropic:{DEFAULT_MODEL}") -> None:
        self._client = client
        self.name = name

    def grade(self, case: EvalCase, output: str, rubric: Rubric) -> JudgeScore:
        text = self._client.complete(
            system=_system_prompt(),
            user=_user_prompt(case, output, rubric),
            schema=_response_schema(rubric),
        )
        payload = _parse_judge_json(text)
        criterion_scores = payload.get("criterion_scores")
        if not isinstance(criterion_scores, dict):
            raise ValueError("judge response is missing the 'criterion_scores' object")
        rationale = payload.get("rationale", "")
        if not isinstance(rationale, str):
            raise ValueError("judge response 'rationale' must be a string")
        return _build_judge_score(criterion_scores, rationale, rubric, self.name)


def _system_prompt() -> str:
    return (
        "You are a strict quality grader for QA artifacts (enriched bug reports, "
        "test steps). Score the candidate output against each rubric criterion on "
        f"an integer scale from {policy.SCORE_MIN} to {policy.SCORE_MAX}: "
        f"{policy.SCORE_MIN} = unusable, 3 = usable with real gaps, "
        f"{policy.SCORE_MAX} = excellent with nothing missing. "
        "Judge only what is present in the output; do not reward length or style. "
        "Respond with a single JSON object: "
        '{"criterion_scores": {"<criterion>": <int>, ...}, "rationale": "<short reason>"}.'
    )


def _user_prompt(case: EvalCase, output: str, rubric: Rubric) -> str:
    lines = ["Rubric criteria:"]
    lines += [f"- {c.name}: {c.description}" for c in rubric.criteria]
    lines += ["", "Original input:", case.input]
    if case.reference is not None:
        lines += ["", "Reference (known-good) output:", case.reference]
    lines += ["", "Candidate output to grade:", output]
    return "\n".join(lines)


def _response_schema(rubric: Rubric) -> dict:
    scale = list(range(policy.SCORE_MIN, policy.SCORE_MAX + 1))
    return {
        "type": "object",
        "properties": {
            "criterion_scores": {
                "type": "object",
                "properties": {
                    c.name: {"type": "integer", "enum": scale} for c in rubric.criteria
                },
                "required": [c.name for c in rubric.criteria],
                "additionalProperties": False,
            },
            "rationale": {"type": "string"},
        },
        "required": ["criterion_scores", "rationale"],
        "additionalProperties": False,
    }


def _parse_judge_json(text: str) -> dict:
    """Parse the judge's JSON response, tolerating code fences around it."""
    cleaned = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", cleaned, flags=re.DOTALL)
    if fenced:
        cleaned = fenced.group(1)
    try:
        payload = json.loads(cleaned)
    except json.JSONDecodeError as exc:
        raise ValueError(f"judge response is not valid JSON: {exc.msg}") from exc
    if not isinstance(payload, dict):
        raise ValueError("judge response must be a JSON object")
    return payload


def _build_judge_score(
    criterion_scores: dict[str, int], rationale: str, rubric: Rubric, generated_by: str
) -> JudgeScore:
    expected = {c.name for c in rubric.criteria}
    got = set(criterion_scores)
    if got != expected:
        raise ValueError(
            "judge scores do not match the rubric criteria: "
            f"expected {sorted(expected)}, got {sorted(got)}"
        )
    overall = sum(criterion_scores.values()) / len(criterion_scores)
    return JudgeScore(
        criterion_scores=criterion_scores,
        overall=overall,
        rationale=rationale,
        generated_by=generated_by,
    )


def judge_from_env() -> Judge | None:
    """Build the default judge when the environment enables Tier 2.

    Returns ``None`` when ``ANTHROPIC_API_KEY`` is unset or the ``anthropic``
    SDK is not installed — the evaluation then runs deterministic-only.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return None
    try:
        return LLMJudge(AnthropicClient())
    except ImportError:
        return None
