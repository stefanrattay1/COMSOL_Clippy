from __future__ import annotations

from pathlib import Path

import pytest

from comsol_clippy.workflow.plan import SaveTarget, WorkflowPlan
from comsol_clippy.workflow.runtime import MPHRuntime


class FakeNode:
    def __init__(self, identifier: str, feature_type: str, parent: str):
        self.identifier = identifier
        self.feature_type = feature_type
        self.parent = parent
        self.label = identifier

    def rename(self, label: str):
        self.label = label


class FakeModel:
    def __init__(self, file_path: str):
        self._file = file_path
        self._name = "Thermal demo"
        self._version = "6.3"
        self.parameters_map = {"Q0": "50[W]"}
        self.descriptions_map = {}
        self.properties_map = {}
        self.created = []
        self.removed = []
        self.imports = []
        self.exports = []
        self.built = []
        self.meshed = []
        self.solved = []
        self.evaluations = []
        self.saved = []
        self.renamed_to = None
        self.cleared = 0
        self.reset_count = 0
        self.properties_set = []
        self.created_nodes = []

    def name(self):
        return self._name

    def file(self):
        return self._file

    def version(self):
        return self._version

    def parameters(self):
        return dict(self.parameters_map)

    def descriptions(self):
        return dict(self.descriptions_map)

    def components(self):
        return ["comp1"]

    def geometries(self):
        return ["geom1"]

    def physics(self):
        return ["ht"]

    def multiphysics(self):
        return []

    def materials(self):
        return ["mat1"]

    def meshes(self):
        return ["mesh1"]

    def studies(self):
        return ["std1"]

    def solutions(self):
        return ["sol1"]

    def datasets(self):
        return ["dset1"]

    def exports(self):
        return ["data1"]

    def modules(self):
        return ["HeatTransferModule"]

    def problems(self):
        return []

    def parameter(self, name, value=None, *, evaluate=False):
        if value is None:
            return self.parameters_map[name]
        self.parameters_map[name] = value

    def description(self, name, text=None):
        if text is None:
            return self.descriptions_map.get(name)
        self.descriptions_map[name] = text

    def property(self, node, name, value=None):
        key = (node, name)
        if value is None:
            return self.properties_map[key]
        self.properties_map[key] = value
        self.properties_set.append((node, name, value))

    def create(self, node, *arguments):
        self.created.append((node, list(arguments)))
        created = FakeNode(f"feature_{len(self.created)}", arguments[0] if arguments else "", str(node))
        self.created_nodes.append(created)
        return created

    def remove(self, node):
        self.removed.append(node)

    def import_(self, node, file):
        self.imports.append((node, file))

    def export(self, node=None, file=None):
        self.exports.append((node, file))

    def build(self, geometry=None):
        self.built.append(geometry)

    def mesh(self, mesh=None):
        self.meshed.append(mesh)

    def solve(self, study=None):
        self.solved.append(study)

    def evaluate(self, expression, **kwargs):
        self.evaluations.append((expression, kwargs))
        return 42.0

    def rename(self, name):
        self.renamed_to = name

    def clear(self):
        self.cleared += 1

    def reset(self):
        self.reset_count += 1

    def save(self, path=None, format=None):
        self.saved.append((path, format))
        if path:
            self._file = path


class FakeClient:
    def __init__(self, model: FakeModel):
        self.model = model
        self.loaded = []
        self.removed = []
        self.caching_state = None
        self.cleared = 0

    def load(self, path: str):
        self.loaded.append(path)
        return self.model

    def create(self, name=None):
        self.model._name = name or self.model._name
        return self.model

    def remove(self, model):
        self.removed.append(model)

    def clear(self):
        self.cleared += 1

    def caching(self, state=None):
        self.caching_state = state


def test_snapshot_reads_model_inventory(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("placeholder")
    model = FakeModel(str(model_path))
    client = FakeClient(model)
    runtime = MPHRuntime(client_factory=lambda cores, version: client)

    loaded = runtime.load_model(model_path)
    snapshot = runtime.snapshot(loaded)

    assert snapshot.name == "Thermal demo"
    assert snapshot.physics == ["ht"]
    assert snapshot.parameters["Q0"] == "50[W]"


def test_apply_plan_updates_model_and_saves_relative_paths(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("placeholder")
    data_file = tmp_path / "tables" / "load.csv"
    data_file.parent.mkdir()
    data_file.write_text("x,y\n0,1\n")

    model = FakeModel(str(model_path))
    client = FakeClient(model)
    runtime = MPHRuntime(client_factory=lambda cores, version: client)
    loaded = runtime.load_model(model_path)
    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {
                    "kind": "set_parameter",
                    "name": "Q0",
                    "value": "125[W]",
                    "description": "heater power",
                },
                {"kind": "set_property", "node": "ht", "name": "T0", "value": "293.15[K]"},
                {"kind": "create_node", "node": "geom1", "arguments": ["Block"]},
                {"kind": "import_file", "node": "func1", "path": "tables/load.csv"},
                {"kind": "build_geometry", "geometry": "geom1"},
                {"kind": "run_mesh", "mesh": "mesh1"},
                {"kind": "solve", "study": "std1"},
                {"kind": "evaluate", "expression": "Q0", "alias": "heater_power"},
            ],
            "save": {"path": "outputs/demo-edited.mph"},
        }
    )

    result = runtime.apply_plan(loaded, plan, base_dir=tmp_path)

    assert model.parameters_map["Q0"] == "125[W]"
    assert model.descriptions_map["Q0"] == "heater power"
    assert model.properties_map[("ht", "T0")] == "293.15[K]"
    assert model.created == [("geom1", ["Block"])]
    assert model.imports == [("func1", str(data_file.resolve()))]
    assert model.built == ["geom1"]
    assert model.meshed == ["mesh1"]
    assert model.solved == ["std1"]
    assert result.evaluations["heater_power"] == 42.0
    assert result.saved_to == str((tmp_path / "outputs" / "demo-edited.mph").resolve())


def test_apply_plan_honors_dry_run(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("placeholder")
    model = FakeModel(str(model_path))
    client = FakeClient(model)
    runtime = MPHRuntime(client_factory=lambda cores, version: client)
    loaded = runtime.load_model(model_path)
    plan = WorkflowPlan.from_dict({"actions": [{"kind": "set_parameter", "name": "Q0", "value": "5[W]"}]})

    result = runtime.apply_plan(
        loaded,
        plan,
        base_dir=tmp_path,
        save_target=SaveTarget(enabled=True),
        dry_run=True,
    )

    assert model.parameters_map["Q0"] == "50[W]"
    assert model.saved == []
    assert result.dry_run is True


def test_apply_plan_builds_bell_oven_geometry_and_cleanup(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("placeholder")
    model = FakeModel(str(model_path))
    client = FakeClient(model)
    runtime = MPHRuntime(client_factory=lambda cores, version: client)
    loaded = runtime.load_model(model_path)
    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {
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
                },
                {"kind": "round_coil_edges", "geometry": "geom1", "radius": 0.01},
                {"kind": "defeature_geometry", "geometry": "geom1", "min_feature_size": 0.002},
            ]
        }
    )

    runtime.apply_plan(loaded, plan, base_dir=tmp_path)

    created_feature_types = [node.feature_type for node in model.created_nodes]
    assert "Rectangle" in created_feature_types
    assert "Difference" in created_feature_types
    assert "Fillet" in created_feature_types
    assert "Repair" in created_feature_types
    assert any(name == "radius" and value == 0.01 for (_, name, value) in model.properties_set)


def _runtime_with_loaded_model(tmp_path: Path):
    model_path = tmp_path / "demo.mph"
    model_path.write_text("placeholder")
    model = FakeModel(str(model_path))
    client = FakeClient(model)
    runtime = MPHRuntime(client_factory=lambda cores, version: client)
    return runtime, runtime.load_model(model_path), model


def test_apply_plan_composes_primitives(tmp_path: Path):
    runtime, loaded, model = _runtime_with_loaded_model(tmp_path)
    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {"kind": "create_rectangle", "geometry": "geom1", "label": "outer", "pos": [0, 0], "size": [1, 2]},
                {"kind": "create_rectangle", "geometry": "geom1", "label": "hole", "pos": [0.2, 0.2], "size": [0.3, 0.3]},
                {"kind": "create_difference", "geometry": "geom1", "label": "ring", "primary": "outer", "subtract": "hole"},
            ]
        }
    )

    runtime.apply_plan(loaded, plan, base_dir=tmp_path)

    types = [node.feature_type for node in model.created_nodes]
    assert types == ["Rectangle", "Rectangle", "Difference"]
    assert any(name == "size" and value == [1.0, 2.0] for (_, name, value) in model.properties_set)


def test_apply_plan_validation_warns_on_unknown_study(tmp_path: Path):
    runtime, loaded, _model = _runtime_with_loaded_model(tmp_path)
    plan = WorkflowPlan.from_dict({"actions": [{"kind": "solve", "study": "std9"}]})

    result = runtime.apply_plan(loaded, plan, base_dir=tmp_path)

    assert any("std9" in w for w in result.validation_warnings)


def test_apply_plan_strict_raises_on_unknown_study(tmp_path: Path):
    from comsol_clippy.workflow.runtime import WorkflowRuntimeError

    runtime, loaded, _model = _runtime_with_loaded_model(tmp_path)
    plan = WorkflowPlan.from_dict({"actions": [{"kind": "solve", "study": "std9"}]})

    with pytest.raises(WorkflowRuntimeError):
        runtime.apply_plan(loaded, plan, base_dir=tmp_path, strict=True)


def test_dry_run_is_a_preflight_with_warnings_and_no_mutation(tmp_path: Path):
    runtime, loaded, model = _runtime_with_loaded_model(tmp_path)
    plan = WorkflowPlan.from_dict(
        {
            "actions": [
                {"kind": "set_parameter", "name": "Q0", "value": "9[W]"},
                {"kind": "solve", "study": "std9"},
            ]
        }
    )

    result = runtime.apply_plan(loaded, plan, base_dir=tmp_path, dry_run=True)

    assert result.dry_run is True
    assert model.parameters_map["Q0"] == "50[W]"  # unchanged
    assert model.saved == []
    assert any("std9" in w for w in result.validation_warnings)