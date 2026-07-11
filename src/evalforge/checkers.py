"""Tier 1 deterministic checkers (ADR-001).

Pure functions from (check spec, raw output) to CheckResult — no I/O, no
LLM, no policy numbers. Blocking semantics live in the evaluator; here a
check only reports pass/fail with an explainable detail string.
"""

from __future__ import annotations

import json
import re

from evalforge.models import (
    CheckResult,
    CheckSpec,
    ContainsCheck,
    EvalCase,
    ForbiddenCheck,
    JsonStructureCheck,
    LengthCheck,
    RegexCheck,
)


def run_check(check: CheckSpec, output: str) -> CheckResult:
    """Evaluate one check spec against a raw candidate output."""
    if isinstance(check, ContainsCheck):
        haystack = output if check.case_sensitive else output.lower()
        needle = check.value if check.case_sensitive else check.value.lower()
        passed = needle in haystack
        detail = (
            f"output contains '{check.value}'"
            if passed
            else f"output does not contain '{check.value}'"
        )
    elif isinstance(check, RegexCheck):
        passed = re.search(check.pattern, output) is not None
        detail = (
            f"pattern '{check.pattern}' matched"
            if passed
            else f"pattern '{check.pattern}' did not match"
        )
    elif isinstance(check, JsonStructureCheck):
        passed, detail = _check_json_structure(check, output)
    elif isinstance(check, LengthCheck):
        n = len(output)
        if n < check.min_chars:
            passed, detail = False, f"length {n} below minimum {check.min_chars}"
        elif check.max_chars is not None and n > check.max_chars:
            passed, detail = False, f"length {n} above maximum {check.max_chars}"
        else:
            passed, detail = True, f"length {n} within bounds"
    elif isinstance(check, ForbiddenCheck):
        lowered = output.lower()
        hits = [value for value in check.values if value.lower() in lowered]
        passed = not hits
        detail = (
            "no forbidden content"
            if passed
            else "forbidden content found: " + ", ".join(f"'{hit}'" for hit in hits)
        )
    else:  # pragma: no cover - unreachable with a validated CheckSpec
        raise TypeError(f"unknown check spec: {type(check).__name__}")

    return CheckResult(
        check_type=check.type, blocking=check.blocking, passed=passed, detail=detail
    )


def _check_json_structure(check: JsonStructureCheck, output: str) -> tuple[bool, str]:
    try:
        payload = json.loads(output)
    except json.JSONDecodeError as exc:
        return False, f"output is not valid JSON: {exc.msg}"
    if not isinstance(payload, dict):
        return False, f"output is JSON but not an object ({type(payload).__name__})"
    missing = [key for key in check.required_keys if key not in payload]
    if missing:
        return False, "missing required keys: " + ", ".join(missing)
    return True, "valid JSON object with required keys"


def run_case_checks(case: EvalCase, output: str) -> list[CheckResult]:
    """Run every check declared on a case against its candidate output."""
    return [run_check(check, output) for check in case.checks]
