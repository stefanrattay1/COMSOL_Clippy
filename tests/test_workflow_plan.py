from __future__ import annotations

import json

import pytest

from comsol_clippy.workflow.plan import WorkflowPlan, load_workflow_plan, workflow_plan_schema


def test_workflow_plan_loads_shorthand_actions(tmp_path):
    plan_path = tmp_path / "plan.json"
    plan_path.write_text(
        json.dumps(
            {
                "goal": "Increase heater load",
                "actions": [
                    {"kind": "set_parameter", "name": "Q0", "value": "125[W]"},
                    {"kind": "solve", "study": "std1"},
                ],
                "save": {"path": "edited/model-out.mph"},
            }
        )
    )

    plan = load_workflow_plan(plan_path)

    assert plan.goal == "Increase heater load"
    assert plan.actions[0].args["name"] == "Q0"
    assert plan.actions[1].args["study"] == "std1"
    assert plan.save.requested is True


def test_workflow_plan_rejects_unknown_action_kind():
    with pytest.raises(ValueError, match="unsupported workflow action"):
        WorkflowPlan.from_dict({"actions": [{"kind": "teleport", "node": "geom1"}]})


def test_workflow_plan_rejects_missing_required_args():
    with pytest.raises(ValueError, match="missing required fields: value"):
        WorkflowPlan.from_dict({"actions": [{"kind": "set_parameter", "name": "Q0"}]})


def test_workflow_schema_lists_supported_actions():
    schema = workflow_plan_schema()
    kinds = schema["properties"]["actions"]["items"]["properties"]["kind"]["enum"]
    assert "create_bell_oven_geometry" in kinds
    assert "apply_fillet" in kinds
    assert "set_parameter" in kinds
    assert "solve" in kinds


def test_workflow_plan_loads_bell_oven_and_cleanup_actions():
    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {
                    "kind": "create_bell_oven_geometry",
                    "geometry": "geom1",
                    "coil_count": 3,
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
                },
                {"kind": "apply_fillet", "geometry": "geom1", "radius": 0.01, "targets": "coil_body_1"},
            ]
        }
    )

    assert plan.actions[0].kind == "create_bell_oven_geometry"
    assert plan.actions[0].args["coil_count"] == 3
    assert plan.actions[1].args["targets"] == ["coil_body_1"]

class _Snap:
    def __init__(self, **kw):
        self.geometries = kw.get("geometries", [])
        self.studies = kw.get("studies", [])
        self.meshes = kw.get("meshes", [])


def test_validate_plan_warns_on_unknown_references():
    from comsol_clippy.workflow.plan import validate_plan_against_snapshot

    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {"kind": "solve", "study": "std9"},
                {"kind": "run_mesh", "mesh": "mesh9"},
                {"kind": "build_geometry", "geometry": "geomX"},
            ]
        }
    )
    snap = _Snap(geometries=["geom1"], studies=["std1"], meshes=["mesh1"])

    warnings = validate_plan_against_snapshot(plan, snap)

    assert len(warnings) == 3
    assert any("std9" in w for w in warnings)


def test_validate_plan_accepts_known_and_plan_created_geometry():
    from comsol_clippy.workflow.plan import validate_plan_against_snapshot

    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {"kind": "solve", "study": "std1"},
                {"kind": "create_rectangle", "geometry": "geomNew", "label": "r", "pos": [0, 0], "size": [1, 1]},
                {"kind": "build_geometry", "geometry": "geomNew"},
            ]
        }
    )
    snap = _Snap(geometries=["geom1"], studies=["std1"])

    assert validate_plan_against_snapshot(plan, snap) == []
