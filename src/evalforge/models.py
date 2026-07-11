"""Pydantic v2 data models: the ADR-001 evaluation contract.

The ADR-001 verdict invariants are enforced *in the models*, not just in
the evaluator: a report that violates them cannot even be constructed.
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from evalforge import policy


class Verdict(str, Enum):
    PASS = "PASS"
    DEGRADED = "DEGRADED"
    FAIL = "FAIL"


# --------------------------------------------------------------------------
# Tier 1 — deterministic check specifications (discriminated union on `type`)
# --------------------------------------------------------------------------


class _CheckBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    # A failed blocking check forces the suite verdict to FAIL (ADR-001).
    blocking: bool = False


class ContainsCheck(_CheckBase):
    """Output must contain a substring."""

    type: Literal["contains"] = "contains"
    value: str = Field(min_length=1)
    case_sensitive: bool = False


class RegexCheck(_CheckBase):
    """Output must match a regular expression."""

    type: Literal["regex"] = "regex"
    pattern: str = Field(min_length=1)

    @field_validator("pattern")
    @classmethod
    def _pattern_compiles(cls, value: str) -> str:
        try:
            re.compile(value)
        except re.error as exc:
            raise ValueError(f"invalid regex pattern: {exc}") from exc
        return value


class JsonStructureCheck(_CheckBase):
    """Output must parse as JSON and expose the required top-level keys.

    Deliberately not full JSON Schema (v1 scope cut, ADR-001).
    """

    type: Literal["json_structure"] = "json_structure"
    required_keys: list[str] = Field(default_factory=list)


class LengthCheck(_CheckBase):
    """Output length must fall within [min_chars, max_chars]."""

    type: Literal["length"] = "length"
    min_chars: int = Field(default=0, ge=0)
    max_chars: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def _bounds_ordered(self) -> "LengthCheck":
        if self.max_chars is not None and self.max_chars < self.min_chars:
            raise ValueError("max_chars must be >= min_chars")
        return self


class ForbiddenCheck(_CheckBase):
    """Output must contain none of these substrings (case-insensitive)."""

    type: Literal["forbidden"] = "forbidden"
    values: list[str] = Field(min_length=1)


CheckSpec = Annotated[
    Union[ContainsCheck, RegexCheck, JsonStructureCheck, LengthCheck, ForbiddenCheck],
    Field(discriminator="type"),
]

CheckType = Literal["contains", "regex", "json_structure", "length", "forbidden"]


# --------------------------------------------------------------------------
# Suite definition and candidate outputs
# --------------------------------------------------------------------------


class EvalCase(BaseModel):
    """One evaluable unit: the input that produced an output, and its checks."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1)
    input: str = Field(min_length=1)
    reference: str | None = None
    checks: list[CheckSpec] = Field(default_factory=list)


class Criterion(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Rubric(BaseModel):
    """Tier 2 grading dimensions, each scored on the policy integer scale."""

    model_config = ConfigDict(extra="forbid")

    criteria: list[Criterion] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_criterion_names(self) -> "Rubric":
        names = [criterion.name for criterion in self.criteria]
        if len(names) != len(set(names)):
            raise ValueError("criterion names must be unique")
        return self


class EvalSuite(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1)
    description: str = ""
    rubric: Rubric
    cases: list[EvalCase] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_case_ids(self) -> "EvalSuite":
        ids = [case.id for case in self.cases]
        if len(ids) != len(set(ids)):
            raise ValueError("case ids must be unique")
        return self


class CandidateOutput(BaseModel):
    """One raw LLM output to evaluate, keyed to its suite case."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    output: str
    source: str | None = None


# --------------------------------------------------------------------------
# Results
# --------------------------------------------------------------------------


class CheckResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    check_type: CheckType
    blocking: bool
    passed: bool
    detail: str = ""


class JudgeScore(BaseModel):
    """Tier 2 verdict for one case: per-criterion integer scores + rationale."""

    model_config = ConfigDict(extra="forbid")

    criterion_scores: dict[str, int]
    overall: float = Field(ge=policy.SCORE_MIN, le=policy.SCORE_MAX)
    rationale: str = ""
    generated_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _scores_consistent(self) -> "JudgeScore":
        if not self.criterion_scores:
            raise ValueError("criterion_scores must not be empty")
        for name, score in self.criterion_scores.items():
            if not policy.SCORE_MIN <= score <= policy.SCORE_MAX:
                raise ValueError(
                    f"criterion '{name}' score {score} outside "
                    f"[{policy.SCORE_MIN}, {policy.SCORE_MAX}]"
                )
        mean = sum(self.criterion_scores.values()) / len(self.criterion_scores)
        if abs(self.overall - mean) > 1e-6:
            raise ValueError("overall must equal the mean of criterion_scores")
        return self


class CaseResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    check_results: list[CheckResult] = Field(default_factory=list)
    judge: JudgeScore | None = None

    @property
    def has_blocking_failure(self) -> bool:
        return any(r.blocking and not r.passed for r in self.check_results)


# --------------------------------------------------------------------------
# Tier 3 — golden set and calibration
# --------------------------------------------------------------------------


class GoldenLabel(BaseModel):
    """A human overall score for one golden case, on the policy scale."""

    model_config = ConfigDict(extra="forbid")

    case_id: str = Field(min_length=1)
    score: int = Field(ge=policy.SCORE_MIN, le=policy.SCORE_MAX)
    notes: str = ""


class GoldenSet(BaseModel):
    model_config = ConfigDict(extra="forbid")

    labels: list[GoldenLabel] = Field(min_length=1)

    @model_validator(mode="after")
    def _unique_case_ids(self) -> "GoldenSet":
        ids = [label.case_id for label in self.labels]
        if len(ids) != len(set(ids)):
            raise ValueError("golden label case ids must be unique")
        return self


class CalibrationReport(BaseModel):
    """Judge-vs-human agreement on the golden set.

    The `calibrated` flag is not free-form: the model itself enforces the
    ADR-001 calibration gate, so an uncalibrated judge cannot be smuggled
    into a verdict by mislabeling the report.
    """

    model_config = ConfigDict(extra="forbid")

    n_cases: int = Field(ge=1)
    exact_agreement: float = Field(ge=0.0, le=1.0)
    adjacent_agreement: float = Field(ge=0.0, le=1.0)
    cohen_kappa: float = Field(ge=-1.0, le=1.0)
    calibrated: bool
    generated_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _calibration_gate(self) -> "CalibrationReport":
        eligible = (
            self.n_cases >= policy.MIN_GOLDEN_CASES
            and self.cohen_kappa >= policy.KAPPA_FLOOR
        )
        if self.calibrated != eligible:
            raise ValueError(
                "calibrated must equal (n_cases >= MIN_GOLDEN_CASES "
                "and cohen_kappa >= KAPPA_FLOOR) — ADR-001 calibration gate"
            )
        if self.adjacent_agreement + 1e-9 < self.exact_agreement:
            raise ValueError("adjacent_agreement cannot be below exact_agreement")
        return self


# --------------------------------------------------------------------------
# Suite report — the output contract
# --------------------------------------------------------------------------


class SuiteReport(BaseModel):
    model_config = ConfigDict(extra="forbid")

    suite_name: str = Field(min_length=1)
    verdict: Verdict
    score: float = Field(ge=0.0, le=1.0)
    # None means "no checks defined" (judge-only suite) -- deliberately
    # distinct from 0.0, which means every declared check failed.
    deterministic_score: float | None = Field(default=None, ge=0.0, le=1.0)
    judge_score: float | None = Field(default=None, ge=0.0, le=1.0)
    calibration: CalibrationReport | None = None
    conditions: list[str] = Field(default_factory=list)
    case_results: list[CaseResult] = Field(min_length=1)
    generated_by: str = Field(min_length=1)

    @model_validator(mode="after")
    def _adr001_invariants(self) -> "SuiteReport":
        has_blocker = any(cr.has_blocking_failure for cr in self.case_results)
        if has_blocker and self.verdict is not Verdict.FAIL:
            raise ValueError("a failed blocking check forces verdict FAIL (ADR-001)")
        if self.verdict is Verdict.FAIL and not has_blocker:
            raise ValueError("FAIL requires an identifiable blocker (ADR-001)")
        if self.verdict is Verdict.PASS and self.score < policy.PASS_THRESHOLD:
            raise ValueError("PASS requires score >= PASS_THRESHOLD (ADR-001)")
        if self.judge_score is not None and (
            self.calibration is None or not self.calibration.calibrated
        ):
            raise ValueError(
                "judge_score may only be set with a calibrated judge (ADR-001)"
            )
        return self
