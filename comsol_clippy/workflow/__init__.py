"""Workflow automation for COMSOL ``.mph`` files via the optional ``mph`` package."""

from .agent import ManualExcerpt, WorkflowAgent, WorkflowContext
from .builders import (
    apply_chamfer,
    apply_fillet,
    build_bell_oven_geometry,
    defeature_geometry,
    round_coil_edges,
)
from .offline_geometry import (
    BellOvenLayout,
    build_bell_oven_layout,
    export_bell_oven_layout_json,
    export_bell_oven_svg,
)
from .plan import SaveTarget, WorkflowAction, WorkflowPlan, load_workflow_plan, workflow_plan_schema
from .runtime import ModelSnapshot, MPHRuntime, WorkflowExecutionResult

__all__ = [
    "MPHRuntime",
    "BellOvenLayout",
    "apply_chamfer",
    "apply_fillet",
    "build_bell_oven_geometry",
    "build_bell_oven_layout",
    "defeature_geometry",
    "export_bell_oven_layout_json",
    "export_bell_oven_svg",
    "ManualExcerpt",
    "ModelSnapshot",
    "round_coil_edges",
    "SaveTarget",
    "WorkflowAction",
    "WorkflowAgent",
    "WorkflowContext",
    "WorkflowExecutionResult",
    "WorkflowPlan",
    "load_workflow_plan",
    "workflow_plan_schema",
]
