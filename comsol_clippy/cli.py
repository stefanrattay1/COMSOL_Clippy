"""CLI surface: serve | ingest | query | status."""
from __future__ import annotations

import sys

import typer

from .config import load_config

app = typer.Typer(add_completion=False, help="COMSOL Clippy — RAG over COMSOL manuals.")


@app.command()
def serve():
    """Start the MCP server over stdio (launched by the MCP client)."""
    from .server import serve as _serve

    _serve()


@app.command()
def ingest(
    rebuild: bool = typer.Option(False, "--rebuild", help="Force a full re-embed of all PDFs."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Print the plan without embedding."),
):
    """Build or repair the vectorstore incrementally (only new/changed files)."""
    from .ingest import run_ingest
    from .pdf import list_sources

    cfg = load_config()

    if not cfg.source_dir.exists() or not list_sources(cfg.source_dir):
        typer.echo(
            f"\nNo source documents found in:\n  {cfg.source_dir}\n\n"
            "Add your COMSOL manuals (PDF) or notes (.txt, .md) to that 'source' "
            "folder, then run setup again.\n"
            "(Word .docx won't work yet — export to PDF or paste into a .txt/.md file.)"
        )
        raise typer.Exit(code=0)

    summary = run_ingest(cfg, force_rebuild=rebuild, dry_run=dry_run)

    def names(x):
        return ", ".join(x) if x else "(none)"

    typer.echo("=== Ingest plan ===")
    if summary["rebuild_all"]:
        typer.echo(f"Full rebuild: {summary['reason']}")
    typer.echo(f"  added:     {names(summary['added'])}")
    typer.echo(f"  updated:   {names(summary['updated'])}")
    typer.echo(f"  deleted:   {names(summary['deleted'])}")
    typer.echo(f"  unchanged: {names(summary['unchanged'])}")
    if summary.get("failed"):
        typer.echo(f"  SKIPPED (could not read): {names(summary['failed'])}")
    if not dry_run:
        typer.echo(f"Vectorstore now holds {summary['total_chunks']} chunks.")
    else:
        typer.echo("(dry run — nothing embedded)")


@app.command()
def query(
    text: str = typer.Argument(..., help="The question to search the manuals for."),
    top_k: int = typer.Option(5, "--top-k", "-k", help="Number of passages to return."),
):
    """Search the COMSOL manuals from the command line (standalone test path)."""
    from .server import Engine, format_hits

    engine = Engine(load_config())
    hits = engine.search(text, top_k=top_k)
    typer.echo(format_hits(hits))


@app.command()
def status():
    """Environment + vectorstore health check, with a smoke query."""
    from .embeddings import detect_device
    from .manifest import Manifest
    from .store import Store

    cfg = load_config()
    ok = True

    device = detect_device()
    typer.echo(f"[status] embedding device: {device}")
    typer.echo(f"[status] model:            {cfg.embedding.model} (dim {cfg.embedding.dim})")

    store = Store(cfg.chroma_dir, cfg.collection)
    if store.exists():
        count = store.count()
        typer.echo(f"[status] vectorstore:      {count} chunks in '{cfg.collection}'")
        if count == 0:
            typer.echo("[status] WARNING: collection is empty — run `ingest`.")
            ok = False
    else:
        typer.echo("[status] vectorstore:      MISSING — run `ingest`.")
        ok = False

    manifest = Manifest.load(cfg.manifest_path)
    typer.echo(f"[status] manifest sources: {len(manifest.sources)}")
    from .pdf import list_sources

    present = set(list_sources(cfg.source_dir))
    missing = present - set(manifest.sources)
    if missing:
        typer.echo(f"[status] not yet embedded: {', '.join(sorted(missing))}")
        ok = False

    if ok:
        from .server import Engine, format_hits

        typer.echo("[status] smoke query: 'conjugate heat transfer'")
        engine = Engine(cfg)
        hits = engine.search("conjugate heat transfer", top_k=3)
        if hits:
            first = hits[0]["metadata"]
            typer.echo(f"[status] OK — top hit: {first.get('source')} p.{first.get('page')}")
        else:
            typer.echo("[status] WARNING: smoke query returned no hits.")
            ok = False

    if not ok:
        raise typer.Exit(code=1)
    typer.echo("[status] all checks passed.")


def main():  # convenience for `python -m comsol_clippy.cli`
    app()


if __name__ == "__main__":
    main()
