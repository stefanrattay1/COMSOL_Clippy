"""Geometry cleanup helpers for solver-friendly geometry preparation."""
from __future__ import annotations

from typing import Any


def apply_fillet(model, args: dict[str, Any], geometry_context: dict[str, Any] | None = None):
    feature = model.create(str(args["geometry"]), "Fillet")
    _set_label(feature, f"fillet_{str(args['geometry'])}")
    _try_set(model, feature, "radius", args["radius"])
    _apply_targets(model, feature, args["targets"], geometry_context=geometry_context)
    return feature


def apply_chamfer(model, args: dict[str, Any], geometry_context: dict[str, Any] | None = None):
    feature = model.create(str(args["geometry"]), "Chamfer")
    _set_label(feature, f"chamfer_{str(args['geometry'])}")
    _try_set(model, feature, "distance", args["distance"])
    _apply_targets(model, feature, args["targets"], geometry_context=geometry_context)
    return feature


def defeature_geometry(model, args: dict[str, Any], geometry_context: dict[str, Any] | None = None):
    feature = model.create(str(args["geometry"]), "Repair")
    _set_label(feature, f"repair_{str(args['geometry'])}")
    _try_set(model, feature, "repairtoltype", "absolute")
    _try_set(model, feature, "repairtol", args["min_feature_size"])
    targets = args.get("targets") or (geometry_context or {}).get("solid_targets")
    if targets:
        _apply_targets(model, feature, targets, geometry_context=geometry_context)
    return feature


def round_coil_edges(model, args: dict[str, Any], geometry_context: dict[str, Any] | None = None):
    targets = args.get("targets") or (geometry_context or {}).get("coil_targets")
    if not targets:
        raise ValueError(
            "round_coil_edges requires prior create_bell_oven_geometry metadata or explicit targets"
        )
    fillet_args = {
        "geometry": args["geometry"],
        "radius": args["radius"],
        "targets": targets,
    }
    return apply_fillet(model, fillet_args, geometry_context=geometry_context)


def _apply_targets(model, feature, targets, *, geometry_context: dict[str, Any] | None = None) -> None:
    values = _as_list(targets)
    for prop in ("input", "targets", "selection"):
        try:
            model.property(feature, prop, values)
            break
        except Exception:
            continue

    java = getattr(feature, "java", None)
    if java is None:
        return
    for selection_name in ("input", "point", "edge", "vertex"):
        try:
            java.selection(selection_name).set(values)
            return
        except Exception:
            continue


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


def _try_set(model, node, name: str, value: Any) -> None:
    try:
        model.property(node, name, value)
    except Exception:
        pass


def _as_list(value) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return [value]