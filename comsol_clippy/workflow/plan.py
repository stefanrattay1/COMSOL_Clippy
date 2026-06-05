"""Structured workflow plans for editing COMSOL ``.mph`` files."""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

ACTION_REQUIREMENTS: dict[str, set[str]] = {
    "set_parameter": {"name", "value"},
    "set_property": {"node", "name", "value"},
    "create_node": {"node", "arguments"},
    "create_bell_oven_geometry": {
        "geometry",
        "coil_count",
        "coil_inner_radius",
        "coil_outer_radius",
        "coil_height",
        "coil_spacing",
        "support_height",
        "support_width",
        "base_height",
        "base_radius",
        "inner_cover_thickness",
        "inner_cover_clearance",
        "inner_cover_headspace",
        "bell_thickness",
        "bell_clearance",
        "bell_headspace",
        "gas_domain_radius",
        "gas_domain_height",
    },
    "remove_node": {"node"},
    "import_file": {"node", "path"},
    "export_file": set(),
    "build_geometry": set(),
    "apply_fillet": {"geometry", "radius", "targets"},
    "apply_chamfer": {"geometry", "distance", "targets"},
    "defeature_geometry": {"geometry", "min_feature_size"},
    "round_coil_edges": {"geometry", "radius"},
    "run_mesh": set(),
    "solve": set(),
    "evaluate": {"expression"},
    "rename_model": {"name"},
    "clear_results": set(),
    "reset_history": set(),
}


def workflow_plan_schema() -> dict[str, Any]:
    """Return the JSON shape expected from an external planner or AI agent."""
    return {
        "type": "object",
        "required": ["actions"],
        "properties": {
            "goal": {"type": "string"},
            "notes": {"type": "array", "items": {"type": "string"}},
            "actions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["kind"],
                    "properties": {
                        "kind": {"enum": sorted(ACTION_REQUIREMENTS)},
                        "args": {"type": "object"},
                    },
                    "description": (
                        "If args is omitted, every key except 'kind' is treated as an action argument."
                    ),
                },
            },
            "save": {
                "type": "object",
                "properties": {
                    "enabled": {"type": "boolean"},
                    "path": {"type": "string"},
                    "format": {"type": "string"},
                },
            },
        },
    }


@dataclass(frozen=True)
class WorkflowAction:
    """One model-editing step."""

    kind: str
    args: dict[str, Any] = field(default_factory=dict)

    def summary(self) -> str:
        args = self.args
        if self.kind == "set_parameter":
            return f"set parameter {args['name']} = {args['value']}"
        if self.kind == "set_property":
            return f"set property {args['name']} on {args['node']}"
        if self.kind == "create_node":
            return f"create node under {args['node']} with arguments {args['arguments']}"
        if self.kind == "create_bell_oven_geometry":
            return (
                "create axisymmetric bell oven geometry "
                f"with {args['coil_count']} coils in {args['geometry']}"
            )
        if self.kind == "remove_node":
            return f"remove node {args['node']}"
        if self.kind == "import_file":
            return f"import {args['path']} into {args['node']}"
        if self.kind == "export_file":
            target = args.get("node") or "all export nodes"
            return f"run export for {target}"
        if self.kind == "build_geometry":
            return f"build geometry {args.get('geometry') or '(all)'}"
        if self.kind == "apply_fillet":
            return f"apply fillet radius {args['radius']} on {args['geometry']} targets {args['targets']}"
        if self.kind == "apply_chamfer":
            return (
                f"apply chamfer distance {args['distance']} on {args['geometry']} "
                f"targets {args['targets']}"
            )
        if self.kind == "defeature_geometry":
            return (
                f"defeature {args['geometry']} with minimum feature size "
                f"{args['min_feature_size']}"
            )
        if self.kind == "round_coil_edges":
            return f"round repeated coil edges in {args['geometry']} with radius {args['radius']}"
        if self.kind == "run_mesh":
            return f"run mesh {args.get('mesh') or '(all)'}"
        if self.kind == "solve":
            return f"solve study {args.get('study') or '(all)'}"
        if self.kind == "evaluate":
            return f"evaluate {args['expression']}"
        if self.kind == "rename_model":
            return f"rename model to {args['name']}"
        if self.kind == "clear_results":
            return "clear stored solution, mesh, and plot data"
        if self.kind == "reset_history":
            return "reset model history"
        return self.kind


@dataclass(frozen=True)
class SaveTarget:
    """Save behaviour for a workflow run."""

    enabled: bool = False
    path: str | None = None
    format: str | None = None

    @property
    def requested(self) -> bool:
        return self.enabled or self.path is not None or self.format is not None


@dataclass(frozen=True)
class WorkflowPlan:
    """Typed plan produced by a human-authored JSON file or an AI agent."""

    actions: list[WorkflowAction]
    goal: str = ""
    notes: list[str] = field(default_factory=list)
    save: SaveTarget = field(default_factory=SaveTarget)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WorkflowPlan":
        if not isinstance(data, dict):
            raise ValueError("workflow plan must be a JSON object")
        raw_actions = data.get("actions")
        if not isinstance(raw_actions, list) or not raw_actions:
            raise ValueError("workflow plan must contain a non-empty 'actions' array")

        actions = [parse_workflow_action(item) for item in raw_actions]
        raw_notes = data.get("notes", [])
        if raw_notes is None:
            raw_notes = []
        if not isinstance(raw_notes, list) or any(not isinstance(x, str) for x in raw_notes):
            raise ValueError("workflow plan 'notes' must be an array of strings")

        return cls(
            goal=str(data.get("goal", "")),
            notes=list(raw_notes),
            actions=actions,
            save=_parse_save_target(data.get("save")),
        )


def parse_workflow_action(data: dict[str, Any]) -> WorkflowAction:
    if not isinstance(data, dict):
        raise ValueError("workflow action must be an object")
    kind = data.get("kind")
    if kind not in ACTION_REQUIREMENTS:
        allowed = ", ".join(sorted(ACTION_REQUIREMENTS))
        raise ValueError(f"unsupported workflow action '{kind}'; allowed: {allowed}")

    raw_args = data.get("args")
    if raw_args is None:
        raw_args = {k: v for (k, v) in data.items() if k != "kind"}
    if not isinstance(raw_args, dict):
        raise ValueError(f"workflow action '{kind}' must provide object-valued args")

    args = dict(raw_args)
    if kind == "create_node":
        arguments = args.get("arguments")
        if isinstance(arguments, str):
            args["arguments"] = [arguments]
        elif isinstance(arguments, list):
            args["arguments"] = list(arguments)
    if kind in {"apply_fillet", "apply_chamfer"}:
        targets = args.get("targets")
        if isinstance(targets, (str, int)):
            args["targets"] = [targets]
        elif isinstance(targets, list):
            args["targets"] = list(targets)

    missing = sorted(name for name in ACTION_REQUIREMENTS[kind] if name not in args)
    if missing:
        raise ValueError(f"workflow action '{kind}' is missing required fields: {', '.join(missing)}")
    return WorkflowAction(kind=kind, args=args)


def merge_save_targets(base: SaveTarget, override: SaveTarget | None = None) -> SaveTarget:
    if override is None:
        return base
    return SaveTarget(
        enabled=override.enabled or base.enabled,
        path=override.path if override.path is not None else base.path,
        format=override.format if override.format is not None else base.format,
    )


def load_workflow_plan(path: str | Path) -> WorkflowPlan:
    plan_path = Path(path)
    data = json.loads(plan_path.read_text(encoding="utf-8"))
    return WorkflowPlan.from_dict(data)


def _parse_save_target(raw: Any) -> SaveTarget:
    if raw in (None, False):
        return SaveTarget()
    if raw is True:
        return SaveTarget(enabled=True)
    if not isinstance(raw, dict):
        raise ValueError("workflow plan 'save' must be an object when provided")
    enabled = bool(raw.get("enabled", False))
    path = raw.get("path")
    fmt = raw.get("format")
    if path is not None and not isinstance(path, str):
        raise ValueError("workflow plan save.path must be a string")
    if fmt is not None and not isinstance(fmt, str):
        raise ValueError("workflow plan save.format must be a string")
    if path is not None or fmt is not None:
        enabled = True
    return SaveTarget(enabled=enabled, path=path, format=fmt)