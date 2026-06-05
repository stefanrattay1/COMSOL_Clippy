"""Bell-oven geometry helpers for 2D axisymmetric COMSOL models."""
from __future__ import annotations

from typing import Any

from ..offline_geometry import build_bell_oven_layout


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
        built[shape.label] = _create_rectangle(
            model,
            geometry_node,
            label=shape.label,
            pos=(shape.x, shape.y),
            size=(shape.width, shape.height),
        )
        if shape.label not in {"inner_cover_outer", "bell_cover_outer"}:
            built_solids.append(built[shape.label])

    for shape in layout.voids:
        built[shape.label] = _create_rectangle(
            model,
            geometry_node,
            label=shape.label,
            pos=(shape.x, shape.y),
            size=(shape.width, shape.height),
        )

    inner_cover = _create_difference(
        model,
        geometry_node,
        label="inner_cover",
        primary=built["inner_cover_outer"],
        subtract=[built[shell_voids["inner_cover_void"].label]],
    )
    bell_cover = _create_difference(
        model,
        geometry_node,
        label="bell_cover",
        primary=built["bell_cover_outer"],
        subtract=[built[shell_voids["bell_cover_void"].label]],
    )
    built_solids.extend([inner_cover, bell_cover])

    gas_box = _create_rectangle(
        model,
        geometry_node,
        label=layout.gas_domain.label,
        pos=(layout.gas_domain.x, layout.gas_domain.y),
        size=(layout.gas_domain.width, layout.gas_domain.height),
    )
    gas_domain = _create_difference(model, geometry_node, label="gas_domain", primary=gas_box, subtract=built_solids)

    return {
        "geometry": geometry,
        "base": _feature_ref(built["bell_oven_base"]),
        "bell_cover": _feature_ref(bell_cover),
        "inner_cover": _feature_ref(inner_cover),
        "gas_domain": _feature_ref(gas_domain),
        "coil_targets": [_feature_ref(built[label]) for label in layout.coil_labels],
        "spacer_targets": [_feature_ref(built[label]) for label in layout.spacer_labels],
        "solid_targets": [_feature_ref(feature) for feature in built_solids],
    }


def _ensure_axisymmetric_geometry(model, geometry: str):
    geometry_path = f"geometries/{geometry}"
    geometries = set(_string_list(_safe_call(model, "geometries") or []))
    if geometry not in geometries:
        geom = model.create(geometry_path, 2)
        _try_set(model, geom, "axisymmetric", True)
        _try_set(model, geom, "lengthunit", "m")
        _set_label(geom, geometry)
        return geom
    _try_set(model, geometry_path, "axisymmetric", True)
    return geometry_path


def _create_rectangle(model, geometry_node, *, label: str, pos: tuple[float, float], size: tuple[float, float]):
    rect = model.create(geometry_node, "Rectangle")
    _set_label(rect, label)
    _try_set(model, rect, "pos", [float(pos[0]), float(pos[1])])
    _try_set(model, rect, "size", [float(size[0]), float(size[1])])
    _try_set(model, rect, "createselection", "on")
    return rect


def _create_difference(model, geometry_node, *, label: str, primary, subtract: list[Any]):
    diff = model.create(geometry_node, "Difference")
    _set_label(diff, label)
    _try_set(model, diff, "input", [_feature_ref(primary)])
    _try_set(model, diff, "input2", [_feature_ref(item) for item in subtract])
    _try_set(model, diff, "createselection", "on")
    return diff


def _set_label(node, label: str) -> None:
    rename = getattr(node, "rename", None)
    if callable(rename):
        try:
            rename(label)
            return
        except Exception:
            pass
    try:
        setattr(node, "label", label)
    except Exception:
        pass


def _feature_ref(node):
    java = getattr(node, "java", None)
    tag = getattr(java, "tag", None)
    if callable(tag):
        try:
            return tag()
        except Exception:
            pass
    name = getattr(node, "name", None)
    if callable(name):
        try:
            return name()
        except Exception:
            pass
    identifier = getattr(node, "identifier", None)
    if identifier is not None:
        return identifier
    return node


def _try_set(model, node, name: str, value: Any) -> None:
    try:
        model.property(node, name, value)
    except Exception:
        pass


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