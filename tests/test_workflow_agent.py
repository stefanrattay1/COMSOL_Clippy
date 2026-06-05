from __future__ import annotations

from pathlib import Path

from comsol_clippy.workflow.agent import WorkflowAgent
from comsol_clippy.workflow.runtime import ModelSnapshot, WorkflowExecutionResult


class FakeRuntime:
    def __init__(self):
        self.loaded = []
        self.released = []
        self.applied = []

    def load_model(self, path):
        self.loaded.append(Path(path))
        return {"path": str(path)}

    def snapshot(self, model):
        return ModelSnapshot(
            name="Demo",
            file=model["path"],
            version="6.3",
            parameters={"Q0": "50[W]"},
            studies=["std1"],
            physics=["ht"],
        )

    def release_model(self, model):
        self.released.append(model)

    def apply_plan(self, model, plan, **kwargs):
        self.applied.append((model, plan, kwargs))
        return WorkflowExecutionResult(plan=plan, action_summaries=["1. ok"], dry_run=kwargs.get("dry_run", False))


class FakeSearcher:
    def search(self, query, top_k=3):
        return [
            {
                "text": "Use Heat Transfer in Solids for this setup.",
                "relevance": 0.91,
                "metadata": {"source": "HeatTransfer.pdf", "page": 12},
            }
        ][:top_k]


def test_build_prompt_includes_request_snapshot_and_manual_context(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    agent = WorkflowAgent(FakeRuntime(), searcher=FakeSearcher())

    context = agent.build_context(model_path, "Increase Q0 and solve the thermal study", top_k=1)
    prompt = agent.build_prompt(context)

    assert "Increase Q0 and solve the thermal study" in prompt
    assert '"Q0": "50[W]"' in prompt
    assert "[HeatTransfer.pdf p.12]" in prompt
    assert "create_bell_oven_geometry" in prompt


def test_parse_agent_response_extracts_fenced_json():
    agent = WorkflowAgent(FakeRuntime())
    response = """
Here is the plan.

```json
{
  "actions": [
    {"kind": "set_parameter", "name": "Q0", "value": "100[W]"}
  ],
  "save": {"path": "edited/demo.mph"}
}
```
"""

    plan = agent.parse_agent_response(response)

    assert plan.actions[0].kind == "set_parameter"
    assert plan.save.path == "edited/demo.mph"


def test_run_with_planner_executes_parsed_plan(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    runtime = FakeRuntime()
    agent = WorkflowAgent(runtime)

    def planner(prompt, context):
        assert "Demo" in prompt
        return {
            "actions": [
                {"kind": "set_parameter", "name": "Q0", "value": "75[W]"},
                {"kind": "solve", "study": "std1"},
            ]
        }

    plan, result = agent.run_with_planner(model_path, "Raise heat and solve.", planner, dry_run=True)

    assert plan.actions[0].args["value"] == "75[W]"
    assert result.dry_run is True
    assert runtime.applied[0][1].actions[1].kind == "solve"


class RepairRuntime(FakeRuntime):
    """FakeRuntime that reports a problem on the first execution only."""

    def __init__(self, problem_attempts: int = 1):
        super().__init__()
        self.problem_attempts = problem_attempts
        self.calls = 0

    def apply_plan(self, model, plan, **kwargs):
        self.calls += 1
        problems = ["solver did not converge"] if self.calls <= self.problem_attempts else []
        self.applied.append((model, plan, kwargs))
        from comsol_clippy.workflow.runtime import ModelSnapshot

        snapshot = ModelSnapshot(name="Demo", file=model["path"], version="6.3", problems=problems)
        return WorkflowExecutionResult(plan=plan, action_summaries=["1. ok"], snapshot=snapshot)


def test_run_with_repair_replans_against_reported_problems(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    runtime = RepairRuntime(problem_attempts=1)
    agent = WorkflowAgent(runtime, searcher=FakeSearcher())

    prompts: list[str] = []

    def planner(prompt, context):
        prompts.append(prompt)
        return {"actions": [{"kind": "set_parameter", "name": "Q0", "value": "10[W]"}]}

    plan, result = agent.run_with_repair(
        model_path, "Fix convergence", planner, max_attempts=2, top_k=1, backup=False
    )

    assert runtime.calls == 2  # executed, found problem, re-executed
    assert result.attempts == 2
    assert "solver did not converge" in prompts[1]  # repair prompt carried the problem


def test_run_with_repair_stops_when_clean(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    runtime = RepairRuntime(problem_attempts=0)
    agent = WorkflowAgent(runtime)

    def planner(prompt, context):
        return {"actions": [{"kind": "set_parameter", "name": "Q0", "value": "10[W]"}]}

    _plan, result = agent.run_with_repair(model_path, "Edit", planner, max_attempts=3, backup=False)

    assert runtime.calls == 1
    assert result.attempts == 1


class BackupRuntime(FakeRuntime):
    def __init__(self, *, raise_on_apply: bool):
        super().__init__()
        self.raise_on_apply = raise_on_apply

    def apply_plan(self, model, plan, **kwargs):
        # Simulate a half-edit that corrupts the file, then fails.
        Path(model["path"]).write_text("CORRUPTED")
        if self.raise_on_apply:
            raise RuntimeError("boom mid-plan")
        return WorkflowExecutionResult(plan=plan, action_summaries=["1. ok"])


def _plan():
    from comsol_clippy.workflow.plan import WorkflowPlan

    return WorkflowPlan.from_dict({"actions": [{"kind": "set_parameter", "name": "Q0", "value": "1[W]"}]})


def test_run_plan_restores_backup_on_failure(tmp_path: Path):
    import pytest

    model_path = tmp_path / "demo.mph"
    model_path.write_text("ORIGINAL")
    agent = WorkflowAgent(BackupRuntime(raise_on_apply=True))

    with pytest.raises(RuntimeError):
        agent.run_plan(model_path, _plan())

    assert model_path.read_text() == "ORIGINAL"  # restored
    assert not model_path.with_suffix(".mph.bak").exists()  # cleaned up


def test_run_plan_discards_backup_on_success(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("ORIGINAL")
    agent = WorkflowAgent(BackupRuntime(raise_on_apply=False))

    agent.run_plan(model_path, _plan())

    assert not model_path.with_suffix(".mph.bak").exists()