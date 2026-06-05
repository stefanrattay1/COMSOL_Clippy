"""Agent-oriented orchestration around workflow plans and ``mph`` execution."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any, Protocol

from .plan import SaveTarget, WorkflowPlan, workflow_plan_schema
from .runtime import ModelSnapshot, MPHRuntime, WorkflowExecutionResult


class WorkflowPlanner(Protocol):
    """Callable planner interface used by :class:`WorkflowAgent`."""

    def __call__(self, prompt: str, context: "WorkflowContext") -> str | dict[str, Any] | WorkflowPlan: ...


@dataclass(frozen=True)
class ManualExcerpt:
    """Relevant manual context provided to a planner."""

    citation: str
    text: str
    relevance: float = 0.0


@dataclass(frozen=True)
class WorkflowContext:
    """Everything a planner needs to draft a COMSOL edit plan."""

    request: str
    model: ModelSnapshot
    manual_context: list[ManualExcerpt] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "request": self.request,
            "model": self.model.to_dict(),
            "manual_context": [
                {"citation": item.citation, "text": item.text, "relevance": item.relevance}
                for item in self.manual_context
            ],
        }


class WorkflowAgent:
    """Bridges model inspection, manual context, planner output, and execution."""

    def __init__(self, runtime: MPHRuntime | None = None, *, searcher: Any | None = None):
        self.runtime = runtime or MPHRuntime()
        self.searcher = searcher

    def build_context(self, model_path: str | Path, request: str, *, top_k: int = 3) -> WorkflowContext:
        model = self.runtime.load_model(model_path)
        try:
            snapshot = self.runtime.snapshot(model)
        finally:
            self.runtime.release_model(model)

        manual_context = []
        if self.searcher is not None and top_k > 0:
            manual_context = self._manual_context(request, top_k=top_k)
        return WorkflowContext(request=request, model=snapshot, manual_context=manual_context)

    def build_prompt(self, context: WorkflowContext) -> str:
        manual_block = "(no manual context requested)"
        if context.manual_context:
            manual_block = "\n\n".join(
                f"{item.citation} (relevance {item.relevance:.2f})\n{item.text}"
                for item in context.manual_context
            )

        schema = json.dumps(workflow_plan_schema(), indent=2)
        snapshot = json.dumps(context.model.to_dict(), indent=2)
        return (
            "You are preparing a structured COMSOL workflow plan for a Python runner that uses the mph package.\n"
            "Return exactly one JSON object that matches the schema below. Do not include prose before or after the JSON.\n\n"
            "Rules:\n"
            "- Use only the documented action kinds.\n"
            "- Prefer create_bell_oven_geometry for a new bell oven or multi-coil furnace layout instead of many low-level create_node steps.\n"
            "- Prefer apply_fillet, apply_chamfer, defeature_geometry, or round_coil_edges for solver-oriented geometry cleanup.\n"
            "- Prefer set_parameter for global numeric changes and set_property for node properties.\n"
            "- Use relative paths only when they should resolve from the plan file's folder.\n"
            "- If the edit should be persisted, include a save object; otherwise leave save disabled.\n\n"
            f"JSON schema:\n{schema}\n\n"
            f"User request:\n{context.request}\n\n"
            f"Model snapshot:\n{snapshot}\n\n"
            f"Relevant manual context:\n{manual_block}\n"
        )

    def build_repair_prompt(
        self,
        context: "WorkflowContext",
        problems: list[Any],
        previous_plan: WorkflowPlan,
    ) -> str:
        """Build a follow-up prompt asking the planner to fix reported problems."""
        problem_block = "\n".join(f"- {problem}" for problem in problems) or "(no specific problems reported)"
        previous = json.dumps(
            {
                "goal": previous_plan.goal,
                "actions": [{"kind": a.kind, "args": a.args} for a in previous_plan.actions],
            },
            indent=2,
            default=str,
        )
        base = self.build_prompt(context)
        return (
            base
            + "\n\nThe previous plan was executed but the model now reports problems.\n"
            + "Return a corrected JSON plan that resolves them. Use the manual context above.\n\n"
            + f"Reported problems:\n{problem_block}\n\n"
            + f"Previous plan that caused these problems:\n{previous}\n"
        )

    def parse_agent_response(self, response: str | dict[str, Any] | WorkflowPlan) -> WorkflowPlan:
        if isinstance(response, WorkflowPlan):
            return response
        if isinstance(response, dict):
            return WorkflowPlan.from_dict(response)
        if not isinstance(response, str):
            raise ValueError("planner response must be a string, dict, or WorkflowPlan")
        return WorkflowPlan.from_dict(_decode_json_object(response))

    def run_plan(
        self,
        model_path: str | Path,
        plan: WorkflowPlan,
        *,
        base_dir: str | Path | None = None,
        save_target: SaveTarget | None = None,
        dry_run: bool = False,
        strict: bool = False,
        backup: bool = True,
    ) -> WorkflowExecutionResult:
        backup_path = self._make_backup(model_path) if (backup and not dry_run) else None
        model = self.runtime.load_model(model_path)
        try:
            result = self.runtime.apply_plan(
                model,
                plan,
                base_dir=base_dir,
                save_target=save_target,
                dry_run=dry_run,
                strict=strict,
            )
        except Exception:
            self._restore_backup(model_path, backup_path)
            raise
        finally:
            self.runtime.release_model(model)
        self._discard_backup(backup_path)
        return result

    @staticmethod
    def _make_backup(model_path: str | Path) -> Path | None:
        source = Path(model_path)
        if not source.exists():
            return None
        backup_path = source.with_suffix(source.suffix + ".bak")
        shutil.copy2(source, backup_path)
        return backup_path

    @staticmethod
    def _restore_backup(model_path: str | Path, backup_path: Path | None) -> None:
        if backup_path is None or not backup_path.exists():
            return
        shutil.copy2(backup_path, model_path)
        backup_path.unlink(missing_ok=True)

    @staticmethod
    def _discard_backup(backup_path: Path | None) -> None:
        if backup_path is not None:
            backup_path.unlink(missing_ok=True)

    def run_response(
        self,
        model_path: str | Path,
        response: str | dict[str, Any] | WorkflowPlan,
        *,
        base_dir: str | Path | None = None,
        save_target: SaveTarget | None = None,
        dry_run: bool = False,
        strict: bool = False,
        backup: bool = True,
    ) -> WorkflowExecutionResult:
        plan = self.parse_agent_response(response)
        return self.run_plan(
            model_path,
            plan,
            base_dir=base_dir,
            save_target=save_target,
            dry_run=dry_run,
            strict=strict,
            backup=backup,
        )

    def run_with_planner(
        self,
        model_path: str | Path,
        request: str,
        planner: WorkflowPlanner,
        *,
        top_k: int = 3,
        base_dir: str | Path | None = None,
        save_target: SaveTarget | None = None,
        dry_run: bool = False,
        strict: bool = False,
        backup: bool = True,
    ) -> tuple[WorkflowPlan, WorkflowExecutionResult]:
        context = self.build_context(model_path, request, top_k=top_k)
        prompt = self.build_prompt(context)
        response = planner(prompt, context)
        plan = self.parse_agent_response(response)
        result = self.run_plan(
            model_path,
            plan,
            base_dir=base_dir,
            save_target=save_target,
            dry_run=dry_run,
            strict=strict,
            backup=backup,
        )
        return plan, result

    def run_with_repair(
        self,
        model_path: str | Path,
        request: str,
        planner: WorkflowPlanner,
        *,
        max_attempts: int = 2,
        top_k: int = 3,
        base_dir: str | Path | None = None,
        save_target: SaveTarget | None = None,
        strict: bool = False,
        backup: bool = True,
    ) -> tuple[WorkflowPlan, WorkflowExecutionResult]:
        """Plan, execute, and re-plan against reported problems up to ``max_attempts``.

        After each real execution the model's reported ``problems`` (captured in the
        result snapshot) are fed back to the planner alongside fresh manual context,
        so a convergence error can drive a manual lookup and a corrected plan.
        """
        if max_attempts < 1:
            raise ValueError("max_attempts must be >= 1")

        context = self.build_context(model_path, request, top_k=top_k)
        prompt = self.build_prompt(context)
        plan = self.parse_agent_response(planner(prompt, context))

        attempt = 0
        result: WorkflowExecutionResult | None = None
        while attempt < max_attempts:
            attempt += 1
            result = self.run_plan(
                model_path,
                plan,
                base_dir=base_dir,
                save_target=save_target,
                strict=strict,
                backup=backup,
            )
            problems = list(result.snapshot.problems) if result.snapshot else []
            if not problems or attempt >= max_attempts:
                break
            # Re-plan against the problems with fresh manual context for the failure.
            repair_context = self.build_context(model_path, request, top_k=top_k)
            repair_prompt = self.build_repair_prompt(repair_context, problems, plan)
            plan = self.parse_agent_response(planner(repair_prompt, repair_context))

        assert result is not None  # loop runs at least once
        result = replace(result, attempts=attempt)
        return plan, result

    def _manual_context(self, request: str, *, top_k: int) -> list[ManualExcerpt]:
        hits = self.searcher.search(request, top_k=top_k)
        return [
            ManualExcerpt(
                citation=_citation(hit.get("metadata", {})),
                text=str(hit.get("text", "")),
                relevance=float(hit.get("relevance", 0.0) or 0.0),
            )
            for hit in hits
        ]


def _decode_json_object(text: str) -> dict[str, Any]:
    candidate = text.strip()
    decoder = json.JSONDecoder()
    try:
        parsed = json.loads(candidate)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass

    for index, char in enumerate(candidate):
        if char != "{":
            continue
        try:
            parsed, _ = decoder.raw_decode(candidate[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(parsed, dict):
            return parsed
    raise ValueError("planner response did not contain a valid JSON object")


def _citation(meta: dict[str, Any]) -> str:
    src = meta.get("source", "?")
    page = meta.get("page")
    page_end = meta.get("page_end", page)
    chunk_index = meta.get("chunk_index", 0)
    if not page:
        return f"[{src} #{chunk_index + 1}]"
    if page_end and page_end != page:
        return f"[{src} p.{page}-{page_end}]"
    return f"[{src} p.{page}]"
