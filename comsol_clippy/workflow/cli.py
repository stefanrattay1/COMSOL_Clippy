"""Typer commands for COMSOL ``.mph`` workflow automation."""
from __future__ import annotations

import json
from pathlib import Path

import typer

from .agent import WorkflowAgent
from .offline_geometry import (
    build_bell_oven_layout,
    export_bell_oven_layout_json,
    export_bell_oven_svg,
    extract_bell_oven_args,
)
from .plan import SaveTarget, load_workflow_plan
from .runtime import MPHRuntime

app = typer.Typer(
    add_completion=False,
    help="Inspect, edit, and save COMSOL .mph files with the optional mph package.",
)


@app.command("export-bell-oven")
def export_bell_oven(
    plan_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Workflow JSON plan containing create_bell_oven_geometry."),
    output_path: Path = typer.Argument(..., dir_okay=False, help="Offline output path (.svg or .json)."),
    layout_json: Path | None = typer.Option(None, "--layout-json", help="Optional path to also write the resolved offline layout JSON."),
):
    """Export the bell-oven geometry offline, without COMSOL or mph."""
    plan = load_workflow_plan(plan_path)
    args = extract_bell_oven_args(plan)
    layout = build_bell_oven_layout(args)

    suffix = output_path.suffix.lower()
    if suffix == ".svg":
        written = export_bell_oven_svg(layout, output_path)
    elif suffix == ".json":
        written = export_bell_oven_layout_json(layout, output_path)
    else:
        raise typer.BadParameter("output path must end in .svg or .json")

    typer.echo(f"Exported offline bell-oven geometry to {written}")
    if layout_json is not None:
        extra = export_bell_oven_layout_json(layout, layout_json)
        typer.echo(f"Exported layout JSON to {extra}")


@app.command("inspect")
def inspect_model(
    model_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to the .mph model."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Load a COMSOL model and print a structured snapshot."""
    runtime = MPHRuntime()
    model = runtime.load_model(model_path)
    try:
        snapshot = runtime.snapshot(model)
    finally:
        runtime.release_model(model)
        runtime.shutdown()

    if json_output:
        typer.echo(json.dumps(snapshot.to_dict(), indent=2, sort_keys=True))
        return

    typer.echo(f"Model: {snapshot.name}")
    typer.echo(f"File:  {snapshot.file or '(unsaved)'}")
    typer.echo(f"Version: {snapshot.version or '(unknown)'}")
    typer.echo(f"Parameters: {len(snapshot.parameters)}")
    typer.echo(f"Physics: {', '.join(snapshot.physics) or '(none)'}")
    typer.echo(f"Studies: {', '.join(snapshot.studies) or '(none)'}")
    typer.echo(f"Problems: {len(snapshot.problems)}")


@app.command("create")
def create_model(
    output_path: Path = typer.Argument(..., dir_okay=False, help="Where to write the new .mph file."),
    name: str | None = typer.Option(None, "--name", help="Optional initial model name."),
    format: str | None = typer.Option(None, "--format", help="Optional explicit save format."),
):
    """Create a blank COMSOL model and save it as a new file."""
    runtime = MPHRuntime()
    model = runtime.create_model(name=name or output_path.stem)
    try:
        result = runtime._save_model(
            model,
            SaveTarget(enabled=True, path=str(output_path), format=format),
            output_path.expanduser().resolve().parent,
        )
        typer.echo(f"Created model at {result}")
    finally:
        runtime.release_model(model)
        runtime.shutdown()


@app.command("apply-plan")
def apply_plan(
    model_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to the source .mph model."),
    plan_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="JSON workflow plan to apply."),
    output: Path | None = typer.Option(None, "--output", help="Optional output .mph path; defaults to in-place save."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the interpreted plan without mutating the model."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Apply a structured workflow JSON plan to a COMSOL model."""
    plan = load_workflow_plan(plan_path)
    save_target = SaveTarget(enabled=not dry_run, path=str(output) if output else None)
    agent = WorkflowAgent(MPHRuntime())
    try:
        result = agent.run_plan(
            model_path,
            plan,
            base_dir=plan_path.parent,
            save_target=save_target,
            dry_run=dry_run,
        )
    finally:
        agent.runtime.shutdown()

    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True, default=str))
        return

    for line in result.action_summaries:
        typer.echo(line)
    if result.saved_to:
        typer.echo(f"Saved to {result.saved_to}")
    elif dry_run:
        typer.echo("Dry run only; no changes were written.")


@app.command("agent-prompt")
def agent_prompt(
    model_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to the source .mph model."),
    request: str = typer.Argument(..., help="Natural-language editing request for the planner/AI agent."),
    top_k: int = typer.Option(3, "--top-k", help="How many COMSOL-manual passages to include."),
):
    """Build a grounded prompt for an external AI agent to plan COMSOL edits."""
    from ..config import load_config
    from ..server import Engine

    searcher = Engine(load_config()) if top_k > 0 else None
    agent = WorkflowAgent(MPHRuntime(), searcher=searcher)
    try:
        context = agent.build_context(model_path, request, top_k=top_k)
        typer.echo(agent.build_prompt(context))
    finally:
        agent.runtime.shutdown()


@app.command("apply-agent-response")
def apply_agent_response(
    model_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Path to the source .mph model."),
    response_path: Path = typer.Argument(..., exists=True, dir_okay=False, help="Text file containing the agent response."),
    output: Path | None = typer.Option(None, "--output", help="Optional output .mph path; defaults to in-place save."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Parse and preview the plan without mutating the model."),
    json_output: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
):
    """Parse an AI-agent response, extract its JSON plan, and apply it."""
    response = response_path.read_text(encoding="utf-8")
    agent = WorkflowAgent(MPHRuntime())
    save_target = SaveTarget(enabled=not dry_run, path=str(output) if output else None)
    try:
        result = agent.run_response(
            model_path,
            response,
            base_dir=response_path.parent,
            save_target=save_target,
            dry_run=dry_run,
        )
    finally:
        agent.runtime.shutdown()

    if json_output:
        typer.echo(json.dumps(result.to_dict(), indent=2, sort_keys=True, default=str))
        return

    for line in result.action_summaries:
        typer.echo(line)
    if result.saved_to:
        typer.echo(f"Saved to {result.saved_to}")
    elif dry_run:
        typer.echo("Dry run only; no changes were written.")