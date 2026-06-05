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