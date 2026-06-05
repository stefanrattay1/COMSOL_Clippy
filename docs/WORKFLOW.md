# COMSOL Workflow Suite

This repository now includes an optional Python workflow layer for editing COMSOL `.mph` files with the [`mph`](https://mph.readthedocs.io/) package.

The workflow suite lives in `comsol_clippy/workflow/` and has three pieces:

- `runtime.py` — lazy `mph` wrapper for loading, creating, inspecting, editing, and saving models.
- `plan.py` — typed JSON workflow plans that are easy to author by hand or by an AI agent.
- `agent.py` — prompt builder, agent-response parser, and execution bridge that can combine model snapshots with COMSOL-manual RAG context.

## Installation

The base project does **not** require `mph`. Install the optional workflow extra in your project environment when you want `.mph` automation:

```bash
pip install -e ".[workflow]"
```

You still need a local COMSOL installation that `mph` can attach to.

## CLI commands

```bash
python main.py workflow inspect model.mph
python main.py workflow create output/new-model.mph --name DemoModel
python main.py workflow apply-plan model.mph plan.json --output edited/model.mph
python main.py workflow agent-prompt model.mph "Increase heater power and rerun the study"
python main.py workflow apply-agent-response model.mph agent-response.txt --output edited/model.mph
python main.py workflow export-bell-oven plan.json offline-bell-oven.svg --layout-json offline-bell-oven-layout.json
```

`apply-plan` defaults to saving in place when `--output` is omitted and the run is not a dry run.

## Workflow plan format

Example:

```json
{
  "goal": "Increase thermal load and rerun the study",
  "notes": [
    "Keep the geometry unchanged.",
    "Write the edited model to a new file."
  ],
  "actions": [
    {
      "kind": "set_parameter",
      "name": "Q0",
      "value": "125[W]",
      "description": "heater power"
    },
    {
      "kind": "solve",
      "study": "std1"
    },
    {
      "kind": "evaluate",
      "expression": "Q0",
      "alias": "heater_power"
    }
  ],
  "save": {
    "path": "edited/model-125W.mph"
  }
}
```

Supported action kinds:

- `set_parameter`
- `set_property`
- `create_node`
- `create_bell_oven_geometry`
- `remove_node`
- `import_file`
- `export_file`
- `build_geometry`
- `apply_fillet`
- `apply_chamfer`
- `defeature_geometry`
- `round_coil_edges`
- `run_mesh`
- `solve`
- `evaluate`
- `rename_model`
- `clear_results`
- `reset_history`

## Bell oven geometry example

For the new 2D axisymmetric bell-oven workflow, the intended first-pass geometry is a
solver-friendly cross-section for purge-gas studies: base/hearth, multiple coil annuli,
spacers/supports, inner cover, bell cover, and a gas domain around them.

```json
{
  "goal": "Create a multi-coil bell oven geometry for purge-gas flow",
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
      "gas_domain_height": 1.5
    },
    {
      "kind": "round_coil_edges",
      "geometry": "geom1",
      "radius": 0.01
    },
    {
      "kind": "defeature_geometry",
      "geometry": "geom1",
      "min_feature_size": 0.002
    },
    {
      "kind": "build_geometry",
      "geometry": "geom1"
    }
  ],
  "save": {
    "path": "edited/bell-oven-axisymmetric.mph"
  }
}
```

Notes:

- This first implementation is 2D axisymmetric, so a truly helical wound coil is approximated
  as a detailed annular cross-section.
- `round_coil_edges` is a convenience cleanup step for repeated coil corners after the geometry
  is generated.
- `apply_fillet` and `apply_chamfer` are available when you want explicit manual target control.

## Offline geometry export

If COMSOL is not installed, you can still generate the bell-oven geometry offline from the same workflow plan.

```bash
python main.py workflow export-bell-oven plan.json bell-oven.svg --layout-json bell-oven-layout.json
```

This path is pure Python and does not require `mph` or COMSOL. It exports:

- an SVG cross-section preview of the 2D axisymmetric geometry,
- an optional JSON file containing the resolved rectangle layout used by both the offline exporter and the COMSOL builder.

## AI-agent workflow

The intended AI loop is:

1. Run `python main.py workflow agent-prompt ...` to build a planner prompt that includes:
   - the user request,
   - a snapshot of the current `.mph` model,
   - optional COMSOL-manual passages from the existing RAG engine,
   - the exact JSON schema the workflow runner accepts.
2. Send that prompt to your preferred LLM/agent.
3. Save the LLM response to a text file.
4. Run `python main.py workflow apply-agent-response ...` to extract the JSON plan from the response and execute it.

This keeps the repo independent of any specific hosted LLM while still providing a concrete, agent-ready automation surface.