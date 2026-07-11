"""Shared helpers for the S1 contract tests: fixture paths and loaders."""

import json
from pathlib import Path

import pytest

SAMPLES_DIR = Path(__file__).resolve().parents[1] / "data" / "samples"
SCENARIOS = ("scenario_pass", "scenario_fail", "scenario_degraded")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def load_jsonl(path: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


@pytest.fixture(params=SCENARIOS)
def scenario_dir(request) -> Path:
    return SAMPLES_DIR / request.param


@pytest.fixture
def golden_dir() -> Path:
    return SAMPLES_DIR / "golden"
