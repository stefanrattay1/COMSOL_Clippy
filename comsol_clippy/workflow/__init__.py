"""Workflow automation for COMSOL ``.mph`` files via the optional ``mph`` package."""

from .agent import ManualExcerpt, WorkflowAgent, WorkflowContext, WorkflowPlanner
from .builders import (
    apply_chamfer,
    apply_fillet,
    build_bell_oven_geometry,
    create_difference,
    create_rectangle,
    defeature_geometry,
    round_coil_edges,
)
from .offline_geometry import (
    BellOvenLayout,
    build_bell_oven_layout,
    export_bell_oven_layout_json,
    export_bell_oven_svg,
)
from .plan import (
    SaveTarget,
    WorkflowAction,
    WorkflowPlan,
    load_workflow_plan,
    validate_plan_against_snapshot,
    workflow_plan_schema,
)
from .planner import CommandPlanner, PlannerError
from .runtime import ModelSnapshot, MPHRuntime, WorkflowExecutionResult

__all__ = [
    "MPHRuntime",
    "BellOvenLayout",
    "CommandPlanner",
    "PlannerError",
    "apply_chamfer",
    "apply_fillet",
    "build_bell_oven_geometry",
    "build_bell_oven_layout",
    "create_difference",
    "create_rectangle",
    "defeature_geometry",
    "export_bell_oven_layout_json",
    "export_bell_oven_svg",
    "ManualExcerpt",
    "ModelSnapshot",
    "round_coil_edges",
    "SaveTarget",
    "validate_plan_against_snapshot",
    "WorkflowAction",
    "WorkflowAgent",
    "WorkflowContext",
    "WorkflowExecutionResult",
    "WorkflowPlan",
    "WorkflowPlanner",
    "load_workflow_plan",
    "workflow_plan_schema",
]
