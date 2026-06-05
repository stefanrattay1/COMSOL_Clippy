from __future__ import annotations

import pytest

from comsol_clippy.workflow.offline_geometry import extract_bell_oven_args
from comsol_clippy.workflow.plan import WorkflowPlan


def _bell_oven_action() -> dict:
    return {
        "kind": "create_bell_oven_geometry",
        "geometry": "geom1",
        "coil_count": 2,
        "coil_inner_radius": 0.2,
        "coil_outer_radius": 0.45,
        "coil_height": 0.12,
        "coil_spacing": 0.03,
        "support_height": 0.02,
        "support_width": 0.08,
        "base_height": 0.15,
        "base_radius": 0.8,
        "inner_cover_thickness": 0.01,
        "inner_cover_clearance": 0.03,
        "inner_cover_headspace": 0.08,
        "bell_thickness": 0.015,
        "bell_clearance": 0.04,
        "bell_headspace": 0.12,
        "gas_domain_radius": 1.2,
        "gas_domain_height": 1.5,
    }


def test_extract_bell_oven_args_finds_geometry_action():
    plan = WorkflowPlan.from_dict({"actions": [_bell_oven_action(), {"kind": "build_geometry", "geometry": "geom1"}]})

    args = extract_bell_oven_args(plan)

    assert args["geometry"] == "geom1"
    assert args["coil_count"] == 2


def test_extract_bell_oven_args_rejects_missing_geometry_action():
    plan = WorkflowPlan.from_dict({"actions": [{"kind": "solve", "study": "std1"}]})

    with pytest.raises(ValueError, match="create_bell_oven_geometry"):
        extract_bell_oven_args(plan)