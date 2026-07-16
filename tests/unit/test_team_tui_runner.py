import io
import json
from pathlib import Path

import pytest

from paperclaw.tui.team_runner import TeamPlanError, load_team_plan, run_team_tui


def _write_plan(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "goal": "ship two isolated tasks",
                "tasks": [
                    {
                        "task_id": "a",
                        "title": "A",
                        "objective": "Implement A",
                        "acceptance_criteria": ["A passes"],
                    },
                    {
                        "task_id": "b",
                        "title": "B",
                        "objective": "Implement B",
                        "acceptance_criteria": ["B passes"],
                    },
                ],
                "budget": {"max_fix_rounds": 1},
            }
        ),
        encoding="utf-8",
    )


def test_load_team_plan_builds_runtime_contracts(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    goal, tasks, budget = load_team_plan(plan)
    assert goal == "ship two isolated tasks"
    assert [task.task_id for task in tasks] == ["a", "b"]
    assert budget.max_fix_rounds == 1


def test_load_team_plan_rejects_non_object_task(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    plan.write_text(
        json.dumps({"goal": "x", "tasks": ["not-an-object"]}),
        encoding="utf-8",
    )
    with pytest.raises(TeamPlanError, match="every team task"):
        load_team_plan(plan)


def test_no_tui_fails_before_provider_or_plan_execution(tmp_path: Path) -> None:
    plan = tmp_path / "plan.json"
    _write_plan(plan)
    stderr = io.StringIO()
    result = run_team_tui(
        plan_path=plan,
        workspace=tmp_path,
        no_tui=True,
        stdin=io.StringIO(),
        stdout=io.StringIO(),
        stderr=stderr,
    )
    assert result == 2
    assert "disabled by --no-tui" in stderr.getvalue()
