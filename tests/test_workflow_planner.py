from __future__ import annotations

import sys

import pytest

from comsol_clippy.workflow.planner import CommandPlanner, PlannerError

CANNED_PLAN = '{"actions": [{"kind": "set_parameter", "name": "Q0", "value": "100[W]"}]}'


def test_command_planner_pipes_prompt_and_returns_stdout():
    # Echo a canned plan regardless of the (ignored) stdin prompt.
    planner = CommandPlanner([sys.executable, "-c", f"print({CANNED_PLAN!r})"])
    out = planner("ignored prompt", context=None)
    assert '"set_parameter"' in out


def test_command_planner_round_trips_stdin():
    # Read the prompt on stdin and wrap it in a plan, proving the prompt is delivered.
    script = (
        "import sys, json;"
        "prompt = sys.stdin.read();"
        "print(json.dumps({'actions': [{'kind': 'rename_model', 'name': prompt.strip()}]}))"
    )
    planner = CommandPlanner([sys.executable, "-c", script])
    out = planner("MyModel", context=None)
    assert "MyModel" in out


def test_command_planner_accepts_shell_string():
    planner = CommandPlanner("claude -p --model opus")
    assert planner.argv == ["claude", "-p", "--model", "opus"]


def test_command_planner_raises_on_nonzero_exit():
    planner = CommandPlanner([sys.executable, "-c", "import sys; sys.exit(3)"])
    with pytest.raises(PlannerError):
        planner("p", context=None)


def test_command_planner_raises_on_empty_output():
    planner = CommandPlanner([sys.executable, "-c", "pass"])
    with pytest.raises(PlannerError):
        planner("p", context=None)


def test_command_planner_rejects_empty_command():
    with pytest.raises(ValueError):
        CommandPlanner([])


def test_command_planner_raises_on_missing_command():
    planner = CommandPlanner(["definitely-not-a-real-command-xyz"])
    with pytest.raises(PlannerError):
        planner("p", context=None)
