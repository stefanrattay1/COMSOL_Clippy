"""Bell-oven geometry helpers for 2D axisymmetric COMSOL models."""
from __future__ import annotations

from typing import Any

from ..offline_geometry import build_bell_oven_layout
from .primitives import create_difference, create_rectangle, feature_ref, set_label, try_set


def build_bell_oven_geometry(model, args: dict[str, Any]) -> dict[str, Any]:
    """Create a 2D axisymmetric bell oven with multiple annular coil bodies.

    The first implementation intentionally targets a solver-friendly cross-section
    for purge-gas studies: repeated coil annuli, a hearth/base, inner cover,
    bell cover, support/spacer rings, and a gas domain obtained by subtracting
    solids from an enclosing rectangle.
    """
    geometry = str(args["geometry"])
    geometry_node = _ensure_axisymmetric_geometry(model, geometry)

    layout = build_bell_oven_layout(args)
    built: dict[str, Any] = {}
    built_solids = []
    shell_voids = {shape.label: shape for shape in layout.voids}
    for shape in layout.solids:
        built[shape.label] = create_rectangle(
            model,
            geometry_node,
            label=shape.label,
            pos=(shape.x, shape.y),
            size=(shape.width, shape.height),
        )
        if shape.label not in {"inner_cover_outer", "bell_cover_outer"}:
            built_solids.append(built[shape.label])

    for shape in layout.voids:
        built[shape.label] = create_rectangle(
            model,
            geometry_node,
            label=shape.label,
            pos=(shape.x, shape.y),
            size=(shape.width, shape.height),
        )

    inner_cover = create_difference(
        model,
        geometry_node,
        label="inner_cover",
        primary=built["inner_cover_outer"],
        subtract=[built[shell_voids["inner_cover_void"].label]],
    )
    bell_cover = create_difference(
        model,
        geometry_node,
        label="bell_cover",
        primary=built["bell_cover_outer"],
        subtract=[built[shell_voids["bell_cover_void"].label]],
    )
    built_solids.extend([inner_cover, bell_cover])

    gas_box = create_rectangle(
        model,
        geometry_node,
        label=layout.gas_domain.label,
        pos=(layout.gas_domain.x, layout.gas_domain.y),
        size=(layout.gas_domain.width, layout.gas_domain.height),
    )
    gas_domain = create_difference(model, geometry_node, label="gas_domain", primary=gas_box, subtract=built_solids)

    return {
        "geometry": geometry,
        "base": feature_ref(built["bell_oven_base"]),
        "bell_cover": feature_ref(bell_cover),
        "inner_cover": feature_ref(inner_cover),
        "gas_domain": feature_ref(gas_domain),
        "coil_targets": [feature_ref(built[label]) for label in layout.coil_labels],
        "spacer_targets": [feature_ref(built[label]) for label in layout.spacer_labels],
        "solid_targets": [feature_ref(feature) for feature in built_solids],
    }


def _ensure_axisymmetric_geometry(model, geometry: str):
    geometry_path = f"geometries/{geometry}"
    geometries = set(_string_list(_safe_call(model, "geometries") or []))
    if geometry not in geometries:
        geom = model.create(geometry_path, 2)
        try_set(model, geom, "axisymmetric", True)
        try_set(model, geom, "lengthunit", "m")
        set_label(geom, geometry)
        return geom
    try_set(model, geometry_path, "axisymmetric", True)
    return geometry_path


def _safe_call(model, name: str):
    fn = getattr(model, name, None)
    if not callable(fn):
        return None
    try:
        return fn()
    except Exception:
        return None


def _string_list(items: list[Any]) -> list[str]:
    return [str(item) for item in items]