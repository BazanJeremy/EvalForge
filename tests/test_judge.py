"""Unit tests for the Tier 2 judge layer (FakeJudge, LLMJudge parsing, env gate)."""

import pytest
from pydantic import ValidationError

from evalforge.judge import FakeJudge, LLMJudge, judge_from_env
from evalforge.models import Criterion, EvalCase, Rubric

RUBRIC = Rubric(
    criteria=[
        Criterion(name="correctness", description="Matches the defect."),
        Criterion(name="clarity", description="Steps are unambiguous."),
    ]
)
CASE = EvalCase(id="BR-001", input="Raw bug report: alarm silent.")


class ScriptedClient:
    """LLMClient stand-in returning a canned response, recording the call."""

    def __init__(self, response: str) -> None:
        self._response = response
        self.system: str | None = None
        self.user: str | None = None
        self.schema: dict | None = None

    def complete(self, system: str, user: str, schema: dict | None = None) -> str:
        self.system, self.user, self.schema = system, user, schema
        return self._response


# ----------------------------------------------------------------- FakeJudge


def test_fake_judge_returns_scripted_scores_and_records_calls():
    judge = FakeJudge({"BR-001": {"correctness": 4, "clarity": 5}})
    score = judge.grade(CASE, "output", RUBRIC)
    assert score.overall == 4.5
    assert score.generated_by == "fake-judge"
    assert judge.calls == ["BR-001"]


def test_fake_judge_refuses_unscripted_cases():
    judge = FakeJudge({})
    with pytest.raises(KeyError, match="BR-001"):
        judge.grade(CASE, "output", RUBRIC)


# ------------------------------------------------------------------ LLMJudge


def test_llm_judge_parses_plain_json():
    client = ScriptedClient(
        '{"criterion_scores": {"correctness": 3, "clarity": 4}, "rationale": "ok"}'
    )
    score = LLMJudge(client).grade(CASE, "candidate output", RUBRIC)
    assert score.criterion_scores == {"correctness": 3, "clarity": 4}
    assert score.overall == 3.5
    assert score.rationale == "ok"


def test_llm_judge_tolerates_code_fences():
    client = ScriptedClient(
        '```json\n{"criterion_scores": {"correctness": 5, "clarity": 5}, "rationale": "clean"}\n```'
    )
    assert LLMJudge(client).grade(CASE, "output", RUBRIC).overall == 5.0


def test_llm_judge_rejects_invalid_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        LLMJudge(ScriptedClient("the output is decent, 4/5")).grade(CASE, "o", RUBRIC)


def test_llm_judge_rejects_criteria_mismatch():
    client = ScriptedClient(
        '{"criterion_scores": {"correctness": 3, "style": 4}, "rationale": "x"}'
    )
    with pytest.raises(ValueError, match="do not match the rubric"):
        LLMJudge(client).grade(CASE, "o", RUBRIC)


def test_llm_judge_rejects_out_of_scale_scores():
    client = ScriptedClient(
        '{"criterion_scores": {"correctness": 6, "clarity": 4}, "rationale": "x"}'
    )
    with pytest.raises(ValidationError):
        LLMJudge(client).grade(CASE, "o", RUBRIC)


def test_llm_judge_prompt_and_schema_carry_the_rubric():
    client = ScriptedClient(
        '{"criterion_scores": {"correctness": 3, "clarity": 3}, "rationale": "x"}'
    )
    LLMJudge(client).grade(CASE, "candidate output", RUBRIC)
    assert "correctness" in client.user and "clarity" in client.user
    assert CASE.input in client.user and "candidate output" in client.user
    schema_props = client.schema["properties"]["criterion_scores"]["properties"]
    assert set(schema_props) == {"correctness", "clarity"}


# ------------------------------------------------------------------ env gate


def test_judge_from_env_is_none_without_api_key(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    assert judge_from_env() is None
