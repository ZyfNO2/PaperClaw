from __future__ import annotations

import importlib.util
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[3]
DATASET_DIR = REPO_ROOT / "evals" / "academic_tailoring_v1"


def _load_validator():
    path = DATASET_DIR / "validate_cases.py"
    spec = importlib.util.spec_from_file_location("academic_tailoring_gold_validator", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_academic_tailoring_gold_dataset_is_structurally_valid() -> None:
    validator = _load_validator()
    rows = validator.validate_dataset(DATASET_DIR)
    assert len(rows) == 20


def test_supplied_material_distribution_matches_realistic_input_mix() -> None:
    validator = _load_validator()
    rows = validator.validate_dataset(DATASET_DIR)
    supplied_counts = [len(row["supplied_materials"]) for row in rows]
    assert supplied_counts.count(0) == 15
    assert supplied_counts.count(1) == 3
    assert supplied_counts.count(2) == 2
    assert max(supplied_counts) == 2


def test_every_case_has_recovery_path_and_forbidden_behaviors() -> None:
    validator = _load_validator()
    rows = validator.validate_dataset(DATASET_DIR)
    for row in rows:
        assert row["stop_conditions"]
        assert row["special_assertions"]["forbidden"]
        assert row["decision"] in {
            "GO",
            "REVISE",
            "REVISE_TO_PILOT",
            "NO_GO",
        }
