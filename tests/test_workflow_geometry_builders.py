from __future__ import annotations

from pathlib import Path

from comsol_clippy.workflow.builders import (
    apply_chamfer,
    apply_fillet,
    build_bell_oven_geometry,
    defeature_geometry,
)
from comsol_clippy.workflow.offline_geometry import build_bell_oven_layout, export_bell_oven_svg


class FakeNode:
    def __init__(self, identifier: str, feature_type: str, parent):
        self.identifier = identifier
        self.feature_type = feature_type
        self.parent = parent
        self.label = identifier

    def rename(self, label: str):
        self.label = label


class FakeModel:
    def __init__(self):
        self.created = []
        self.properties = []

    def geometries(self):
        return ["geom1"]

    def create(self, node, *arguments):
        feature_type = arguments[0] if arguments else ""
        created = FakeNode(f"node_{len(self.created) + 1}", feature_type, node)
        self.created.append(created)
        return created

    def property(self, node, name, value=None):
        if value is None:
            raise KeyError(name)
        self.properties.append((node, name, value))


def test_build_bell_oven_geometry_creates_expected_feature_types():
    model = FakeModel()
    metadata = build_bell_oven_geometry(
        model,
        {
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
    )

    created_feature_types = [node.feature_type for node in model.created]
    assert created_feature_types.count("Rectangle") >= 7
    assert created_feature_types.count("Difference") >= 3
    assert len(metadata["coil_targets"]) == 3
    assert metadata["geometry"] == "geom1"


def test_cleanup_builders_create_expected_features():
    model = FakeModel()
    apply_fillet(model, {"geometry": "geom1", "radius": 0.01, "targets": ["coil1"]})
    apply_chamfer(model, {"geometry": "geom1", "distance": 0.005, "targets": ["coil2"]})
    defeature_geometry(model, {"geometry": "geom1", "min_feature_size": 0.002})

    created_feature_types = [node.feature_type for node in model.created]
    assert created_feature_types == ["Fillet", "Chamfer", "Repair"]


def test_build_bell_oven_layout_exports_svg(tmp_path: Path):
    layout = build_bell_oven_layout(
        {
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
    )

    output = export_bell_oven_svg(layout, tmp_path / "bell_oven.svg")

    assert output.exists()
    text = output.read_text(encoding="utf-8")
    assert "<svg" in text
    assert "Offline SVG export generated without COMSOL" in text
    assert "fill-rule=\"evenodd\"" in text
    assert "coilWindings" in text
    assert len(layout.coil_labels) == 2


def test_primitives_create_rectangle_and_difference():
    from comsol_clippy.workflow.builders import create_difference, create_rectangle

    model = FakeModel()
    outer = create_rectangle(model, "geometries/geom1", label="outer", pos=(0, 0), size=(1.0, 2.0))
    hole = create_rectangle(model, "geometries/geom1", label="hole", pos=(0.2, 0.2), size=(0.3, 0.3))
    create_difference(model, "geometries/geom1", label="ring", primary=outer, subtract=[hole])

    types = [node.feature_type for node in model.created]
    assert types == ["Rectangle", "Rectangle", "Difference"]
    assert ("node_1", "size", [1.0, 2.0]) in model.properties or any(
        name == "size" and value == [1.0, 2.0] for (_, name, value) in model.properties
    )
