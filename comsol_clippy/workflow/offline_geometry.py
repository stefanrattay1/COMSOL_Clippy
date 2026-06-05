"""Pure-Python geometry layout and export helpers for offline workflow use."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class RectShape:
    label: str
    role: str
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class BellOvenLayout:
    geometry: str
    gas_domain: RectShape
    solids: list[RectShape] = field(default_factory=list)
    voids: list[RectShape] = field(default_factory=list)
    coil_labels: list[str] = field(default_factory=list)
    spacer_labels: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ROLE_STYLES: dict[str, tuple[str, str, float]] = {
    "gas_domain": ("#dff3ff", "#7aaed6", 0.45),
    "base": ("#7f6a5a", "#4f4037", 1.0),
    "support": ("#8a8f98", "#4c525b", 1.0),
    "spacer": ("#9ba3ad", "#4c525b", 1.0),
    "coil": ("#b96b2d", "#6c3b15", 1.0),
    "inner_cover": ("#cfd4db", "#68707b", 0.85),
    "bell_cover": ("#b7c4d3", "#5d6d7e", 0.65),
    "void": ("#f6fbff", "#f6fbff", 1.0),
}


def extract_bell_oven_args(plan) -> dict[str, Any]:
    for action in plan.actions:
        if action.kind == "create_bell_oven_geometry":
            return dict(action.args)
    raise ValueError("workflow plan does not contain a create_bell_oven_geometry action")


def build_bell_oven_layout(args: dict[str, Any]) -> BellOvenLayout:
    geometry = str(args["geometry"])

    coil_count = int(args["coil_count"])
    coil_inner_radius = float(args["coil_inner_radius"])
    coil_outer_radius = float(args["coil_outer_radius"])
    coil_height = float(args["coil_height"])
    coil_spacing = float(args["coil_spacing"])
    support_height = float(args["support_height"])
    support_width = float(args["support_width"])
    base_height = float(args["base_height"])
    base_radius = float(args["base_radius"])
    inner_cover_thickness = float(args["inner_cover_thickness"])
    inner_cover_clearance = float(args["inner_cover_clearance"])
    inner_cover_headspace = float(args["inner_cover_headspace"])
    bell_thickness = float(args["bell_thickness"])
    bell_clearance = float(args["bell_clearance"])
    bell_headspace = float(args["bell_headspace"])
    gas_domain_radius = float(args["gas_domain_radius"])
    gas_domain_height = float(args["gas_domain_height"])

    _validate_bell_oven_inputs(
        coil_count=coil_count,
        coil_inner_radius=coil_inner_radius,
        coil_outer_radius=coil_outer_radius,
        coil_height=coil_height,
        coil_spacing=coil_spacing,
        support_height=support_height,
        support_width=support_width,
        base_height=base_height,
        base_radius=base_radius,
        inner_cover_thickness=inner_cover_thickness,
        inner_cover_clearance=inner_cover_clearance,
        inner_cover_headspace=inner_cover_headspace,
        bell_thickness=bell_thickness,
        bell_clearance=bell_clearance,
        bell_headspace=bell_headspace,
        gas_domain_radius=gas_domain_radius,
        gas_domain_height=gas_domain_height,
    )

    gas_domain = RectShape(
        label="gas_domain_box",
        role="gas_domain",
        x=0.0,
        y=0.0,
        width=gas_domain_radius,
        height=gas_domain_height,
    )
    solids = [
        RectShape(
            label="bell_oven_base",
            role="base",
            x=0.0,
            y=0.0,
            width=base_radius,
            height=base_height,
        )
    ]

    coil_width = coil_outer_radius - coil_inner_radius
    spacer_inner_radius = max(0.0, ((coil_inner_radius + coil_outer_radius) / 2.0) - (support_width / 2.0))
    z_cursor = base_height

    support = RectShape(
        label="coil_support_1",
        role="support",
        x=spacer_inner_radius,
        y=z_cursor,
        width=support_width,
        height=support_height,
    )
    solids.append(support)
    z_cursor += support_height

    coil_labels: list[str] = []
    spacer_labels: list[str] = []
    for index in range(coil_count):
        label = f"coil_body_{index + 1}"
        solids.append(
            RectShape(
                label=label,
                role="coil",
                x=coil_inner_radius,
                y=z_cursor,
                width=coil_width,
                height=coil_height,
            )
        )
        coil_labels.append(label)
        z_cursor += coil_height
        if index < coil_count - 1:
            spacer_label = f"coil_spacer_{index + 1}"
            solids.append(
                RectShape(
                    label=spacer_label,
                    role="spacer",
                    x=spacer_inner_radius,
                    y=z_cursor,
                    width=support_width,
                    height=max(support_height, coil_spacing),
                )
            )
            spacer_labels.append(spacer_label)
            z_cursor += coil_spacing

    stack_top = z_cursor
    inner_cavity_radius = coil_outer_radius + inner_cover_clearance
    inner_cavity_height = stack_top + inner_cover_headspace
    inner_cover_outer_radius = inner_cavity_radius + inner_cover_thickness
    inner_cover_outer_height = inner_cavity_height + inner_cover_thickness

    solids.append(
        RectShape(
            label="inner_cover_outer",
            role="inner_cover",
            x=0.0,
            y=base_height,
            width=inner_cover_outer_radius,
            height=inner_cover_outer_height - base_height,
        )
    )

    bell_inner_radius = inner_cover_outer_radius + bell_clearance
    bell_inner_height = inner_cover_outer_height + bell_headspace
    bell_outer_radius = bell_inner_radius + bell_thickness
    bell_outer_height = bell_inner_height + bell_thickness

    solids.append(
        RectShape(
            label="bell_cover_outer",
            role="bell_cover",
            x=0.0,
            y=base_height,
            width=bell_outer_radius,
            height=bell_outer_height - base_height,
        )
    )

    voids = [
        RectShape(
            label="inner_cover_void",
            role="void",
            x=0.0,
            y=base_height,
            width=inner_cavity_radius,
            height=inner_cavity_height - base_height,
        ),
        RectShape(
            label="bell_cover_void",
            role="void",
            x=0.0,
            y=base_height,
            width=bell_inner_radius,
            height=bell_inner_height - base_height,
        ),
    ]

    return BellOvenLayout(
        geometry=geometry,
        gas_domain=gas_domain,
        solids=solids,
        voids=voids,
        coil_labels=coil_labels,
        spacer_labels=spacer_labels,
    )


def export_bell_oven_svg(layout: BellOvenLayout, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    width = layout.gas_domain.width
    height = layout.gas_domain.height
    scale = 1000.0
    padding = 40.0
    view_w = int(width * scale + padding * 2)
    view_h = int(height * scale + padding * 2)
    solids_by_label = {shape.label: shape for shape in layout.solids}
    rendered: set[str] = set()

    parts = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{view_w}" height="{view_h}" viewBox="0 0 {view_w} {view_h}">',
        '<defs>',
        '  <linearGradient id="gasGradient" x1="0%" y1="0%" x2="0%" y2="100%">',
        '    <stop offset="0%" stop-color="#eef9ff"/>',
        '    <stop offset="100%" stop-color="#d7eefb"/>',
        '  </linearGradient>',
        '  <linearGradient id="bellSteel" x1="0%" y1="0%" x2="100%" y2="100%">',
        '    <stop offset="0%" stop-color="#d9e3ed"/>',
        '    <stop offset="100%" stop-color="#9eb1c5"/>',
        '  </linearGradient>',
        '  <linearGradient id="innerSteel" x1="0%" y1="0%" x2="100%" y2="100%">',
        '    <stop offset="0%" stop-color="#e8ebef"/>',
        '    <stop offset="100%" stop-color="#b7c0c9"/>',
        '  </linearGradient>',
        '  <pattern id="coilWindings" patternUnits="userSpaceOnUse" width="18" height="12">',
        '    <rect width="18" height="12" fill="#b96b2d"/>',
        '    <path d="M 0 12 L 18 0" stroke="#8f4c17" stroke-width="1.5" opacity="0.55"/>',
        '    <path d="M -9 12 L 9 0" stroke="#d89557" stroke-width="1.2" opacity="0.4"/>',
        '    <path d="M 9 12 L 27 0" stroke="#d89557" stroke-width="1.2" opacity="0.4"/>',
        '  </pattern>',
        '</defs>',
        '<rect width="100%" height="100%" fill="#f6fbff"/>',
    ]
    parts.append(_svg_rect(layout.gas_domain, scale=scale, pad=padding, height=height, fill_override="url(#gasGradient)", stroke_override="#a7cadf", opacity_override=1.0))

    base = solids_by_label.get("bell_oven_base")
    if base is not None:
        parts.extend(_svg_base(base, scale=scale, pad=padding, height=height))
        rendered.add(base.label)

    for shape in layout.solids:
        if shape.role == "support":
            parts.append(_svg_round_rect(shape, scale=scale, pad=padding, height=height, corner=10.0))
            rendered.add(shape.label)
    for shape in layout.solids:
        if shape.role == "spacer":
            parts.append(_svg_round_rect(shape, scale=scale, pad=padding, height=height, corner=8.0))
            rendered.add(shape.label)
    for shape in layout.solids:
        if shape.role == "coil":
            parts.extend(_svg_coil(shape, scale=scale, pad=padding, height=height))
            rendered.add(shape.label)

    inner_outer = solids_by_label.get("inner_cover_outer")
    inner_void = next((shape for shape in layout.voids if shape.label == "inner_cover_void"), None)
    if inner_outer is not None and inner_void is not None:
        parts.append(
            _svg_cover_shell(
                outer=inner_outer,
                inner=inner_void,
                scale=scale,
                pad=padding,
                height=height,
                fill="url(#innerSteel)",
                stroke="#68707b",
                label="inner_cover",
            )
        )
        rendered.add(inner_outer.label)

    bell_outer = solids_by_label.get("bell_cover_outer")
    bell_void = next((shape for shape in layout.voids if shape.label == "bell_cover_void"), None)
    if bell_outer is not None and bell_void is not None:
        parts.append(
            _svg_cover_shell(
                outer=bell_outer,
                inner=bell_void,
                scale=scale,
                pad=padding,
                height=height,
                fill="url(#bellSteel)",
                stroke="#5d6d7e",
                label="bell_cover",
            )
        )
        rendered.add(bell_outer.label)

    for shape in layout.solids:
        if shape.label in rendered:
            continue
        parts.append(_svg_rect(shape, scale=scale, pad=padding, height=height))
    parts.append(
        f'<line x1="{padding:.1f}" y1="{padding:.1f}" x2="{padding:.1f}" y2="{view_h - padding:.1f}" '
        'stroke="#44576d" stroke-width="2" stroke-dasharray="8 6" opacity="0.7"/>'
    )
    parts.append(
        f'<text x="{padding + 16:.1f}" y="{padding + 32:.1f}" font-family="Arial, sans-serif" font-size="28" '
        'font-weight="700" fill="#203040">2D axisymmetric bell oven geometry</text>'
    )
    parts.append(
        f'<text x="{padding + 16:.1f}" y="{padding + 64:.1f}" font-family="Arial, sans-serif" font-size="16" '
        'fill="#40566f">Offline SVG export generated without COMSOL</text>'
    )
    parts.append('</svg>')

    out.write_text("\n".join(parts), encoding="utf-8")
    return out


def export_bell_oven_layout_json(layout: BellOvenLayout, output_path: str | Path) -> Path:
    out = Path(output_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(layout.to_dict(), indent=2), encoding="utf-8")
    return out


def _svg_rect(
    shape: RectShape,
    *,
    scale: float,
    pad: float,
    height: float,
    fill_override: str | None,
    stroke_override: str | None,
    opacity_override: float | None,
) -> str:
    fill, stroke, opacity = ROLE_STYLES.get(shape.role, ("#cccccc", "#444444", 1.0))
    x, y, width, rect_height = _svg_box(shape, scale=scale, pad=pad, height=height)
    fill = fill_override or fill
    stroke = stroke_override or stroke
    opacity = opacity_override if opacity_override is not None else opacity
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{rect_height:.1f}" '
        f'fill="{fill}" stroke="{stroke}" stroke-width="2" fill-opacity="{opacity:.3f}"/>'
    )


def _svg_round_rect(shape: RectShape, *, scale: float, pad: float, height: float, corner: float) -> str:
    fill, stroke, opacity = ROLE_STYLES.get(shape.role, ("#cccccc", "#444444", 1.0))
    x, y, width, rect_height = _svg_box(shape, scale=scale, pad=pad, height=height)
    radius = min(corner, width / 2.0, rect_height / 2.0)
    return (
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{rect_height:.1f}" '
        f'rx="{radius:.1f}" ry="{radius:.1f}" fill="{fill}" stroke="{stroke}" '
        f'stroke-width="2" fill-opacity="{opacity:.3f}"/>'
    )


def _svg_base(shape: RectShape, *, scale: float, pad: float, height: float) -> list[str]:
    fill, stroke, _ = ROLE_STYLES.get(shape.role, ("#7f6a5a", "#4f4037", 1.0))
    x, y, width, rect_height = _svg_box(shape, scale=scale, pad=pad, height=height)
    lip_height = min(rect_height * 0.14, 18.0)
    return [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{rect_height:.1f}" fill="{fill}" stroke="{stroke}" stroke-width="2"/>',
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{lip_height:.1f}" fill="#9a816b" opacity="0.45"/>',
    ]


def _svg_coil(shape: RectShape, *, scale: float, pad: float, height: float) -> list[str]:
    x, y, width, rect_height = _svg_box(shape, scale=scale, pad=pad, height=height)
    corner = min(14.0, width / 5.0, rect_height / 4.0)
    lines = [
        f'<rect x="{x:.1f}" y="{y:.1f}" width="{width:.1f}" height="{rect_height:.1f}" rx="{corner:.1f}" ry="{corner:.1f}" fill="url(#coilWindings)" stroke="#6c3b15" stroke-width="2.4"/>',
        f'<rect x="{x + width * 0.05:.1f}" y="{y + rect_height * 0.12:.1f}" width="{width * 0.90:.1f}" height="{rect_height * 0.10:.1f}" fill="#ebb27c" opacity="0.30" rx="8"/>',
    ]
    groove_count = max(3, int(shape.height / 0.025))
    for index in range(1, groove_count):
        line_y = y + rect_height * index / groove_count
        lines.append(
            f'<line x1="{x + 10:.1f}" y1="{line_y:.1f}" x2="{x + width - 10:.1f}" y2="{line_y:.1f}" stroke="#8f4c17" stroke-width="1.2" opacity="0.35"/>'
        )
    return lines


def _svg_cover_shell(
    *,
    outer: RectShape,
    inner: RectShape,
    scale: float,
    pad: float,
    height: float,
    fill: str,
    stroke: str,
    label: str,
) -> str:
    outer_path = _cover_profile_path(outer, scale=scale, pad=pad, height=height)
    inner_path = _cover_profile_path(inner, scale=scale, pad=pad, height=height)
    return (
        f'<path d="{outer_path} {inner_path}" fill="{fill}" stroke="{stroke}" stroke-width="2.4" '
        f'fill-rule="evenodd" data-label="{label}"/>'
    )


def _cover_profile_path(shape: RectShape, *, scale: float, pad: float, height: float) -> str:
    x0 = shape.x
    x1 = shape.x + shape.width
    y0 = shape.y
    y1 = shape.y + shape.height
    crown_depth = min(shape.height * 0.28, shape.width * 0.38)
    shoulder_y = max(y0 + shape.height * 0.42, y1 - crown_depth)

    p_axis_base = _svg_point(x0, y0, scale=scale, pad=pad, height=height)
    p_wall_base = _svg_point(x1, y0, scale=scale, pad=pad, height=height)
    p_wall_top = _svg_point(x1, shoulder_y, scale=scale, pad=pad, height=height)
    p_apex = _svg_point(x0, y1, scale=scale, pad=pad, height=height)
    cp1 = _svg_point(x1 * 0.98, y1 - crown_depth * 0.12, scale=scale, pad=pad, height=height)
    cp2 = _svg_point(x1 * 0.38, y1, scale=scale, pad=pad, height=height)

    return (
        f'M {p_axis_base} '
        f'L {p_wall_base} '
        f'L {p_wall_top} '
        f'C {cp1} {cp2} {p_apex} '
        'Z'
    )


def _svg_box(shape: RectShape, *, scale: float, pad: float, height: float) -> tuple[float, float, float, float]:
    x = pad + shape.x * scale
    y = pad + (height - (shape.y + shape.height)) * scale
    width = shape.width * scale
    rect_height = shape.height * scale
    return x, y, width, rect_height


def _svg_point(x: float, y: float, *, scale: float, pad: float, height: float) -> str:
    sx = pad + x * scale
    sy = pad + (height - y) * scale
    return f'{sx:.1f},{sy:.1f}'


def _validate_bell_oven_inputs(**values: float) -> None:
    if values["coil_count"] < 1:
        raise ValueError("create_bell_oven_geometry requires coil_count >= 1")
    for name, value in values.items():
        if name == "coil_count":
            continue
        if value <= 0:
            raise ValueError(f"create_bell_oven_geometry requires {name} > 0 (got {value})")
    if values["coil_outer_radius"] <= values["coil_inner_radius"]:
        raise ValueError("coil_outer_radius must be greater than coil_inner_radius")
    if values["base_radius"] < values["coil_outer_radius"]:
        raise ValueError("base_radius must be at least as large as coil_outer_radius")
    if values["gas_domain_radius"] <= values["bell_clearance"] + values["bell_thickness"]:
        raise ValueError("gas_domain_radius must leave room around the bell cover")