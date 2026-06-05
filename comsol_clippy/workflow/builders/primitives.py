"""Low-level, composable geometry primitives for COMSOL geometry sequences.

These helpers are deliberately generic so a planner can compose unseen geometries
from rectangles and boolean differences without a bespoke high-level builder. The
high-level builders (e.g. ``bell_oven``) reuse the same helpers.
"""
from __future__ import annotations

from typing import Any


def create_rectangle(model, geometry_node, *, label: str, pos: tuple[float, float], size: tuple[float, float]):
    """Create a single labelled rectangle in a 2D geometry sequence."""
    rect = model.create(geometry_node, "Rectangle")
    set_label(rect, label)
    try_set(model, rect, "pos", [float(pos[0]), float(pos[1])])
    try_set(model, rect, "size", [float(size[0]), float(size[1])])
    try_set(model, rect, "createselection", "on")
    return rect


def create_difference(model, geometry_node, *, label: str, primary, subtract: list[Any]):
    """Create a boolean Difference of ``primary`` minus ``subtract`` features."""
    diff = model.create(geometry_node, "Difference")
    set_label(diff, label)
    try_set(model, diff, "input", [feature_ref(primary)])
    try_set(model, diff, "input2", [feature_ref(item) for item in subtract])
    try_set(model, diff, "createselection", "on")
    return diff


def set_label(node, label: str) -> None:
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


def feature_ref(node):
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


def try_set(model, node, name: str, value: Any) -> None:
    try:
        model.property(node, name, value)
    except Exception:
        pass
