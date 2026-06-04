"""Ingestion orchestration: compute the incremental plan, then chunk / embed /
upsert / delete to bring the vectorstore in sync with source/."""
from __future__ import annotations

import sys

from .config import Config
from .embeddings import Embedder
from .manifest import Manifest, Plan, compute_plan, sha256_file
from .pdf import chunk_file, list_sources, page_count
from .store import Store


def _embed_source(fname: str, cfg: Config, embedder: Embedder, store: Store,
                  manifest: Manifest) -> int:
    path = cfg.source_dir / fname
    print(f"[ingest]   chunking {fname} ...", file=sys.stderr)
    chunks = chunk_file(
        path,
        encode=embedder.encode_tokens,
        decode=embedder.decode_tokens,
        chunk_tokens=cfg.chunking.chunk_tokens,
        overlap_tokens=cfg.chunking.chunk_overlap_tokens,
        min_chunk_tokens=cfg.chunking.min_chunk_tokens,
    )
    print(f"[ingest]   embedding {len(chunks)} chunks from {fname} ...", file=sys.stderr)
    vectors = embedder.embed_documents([c.text for c in chunks])
    store.upsert_chunks(chunks, vectors)
    manifest.set_source(
        fname,
        sha256=sha256_file(path),
        size=path.stat().st_size,
        mtime=path.stat().st_mtime,
        page_count=page_count(path),
        chunk_ids=[c.chunk_id for c in chunks],
    )
    return len(chunks)


def plan_only(cfg: Config) -> Plan:
    manifest = Manifest.load(cfg.manifest_path)
    store = Store(cfg.chroma_dir, cfg.collection)
    return compute_plan(
        cfg.source_dir,
        manifest,
        current_model=cfg.embedding.model,
        current_chunk_params=cfg.chunk_params(),
        collection_exists=store.exists() and store.count() > 0,
        chunks_present=store.has_all,
    )


def run_ingest(cfg: Config, *, force_rebuild: bool = False, dry_run: bool = False) -> dict:
    manifest = Manifest.load(cfg.manifest_path)
    store = Store(cfg.chroma_dir, cfg.collection)

    plan = compute_plan(
        cfg.source_dir,
        manifest,
        current_model=cfg.embedding.model,
        current_chunk_params=cfg.chunk_params(),
        collection_exists=(not force_rebuild) and store.exists() and store.count() > 0,
        chunks_present=store.has_all,
    )

    present = list_sources(cfg.source_dir)
    unchanged = [f for f in present if f not in (plan.add + plan.update)]

    summary = {
        "added": plan.add,
        "updated": plan.update,
        "deleted": plan.delete,
        "unchanged": unchanged,
        "rebuild_all": plan.rebuild_all,
        "reason": plan.reason,
        "total_chunks": 0,
        "failed": [],
    }

    if dry_run:
        return summary

    if plan.is_empty():
        summary["total_chunks"] = store.count()
        return summary

    embedder = Embedder(cfg.embedding)

    # Deletions and updates: drop existing chunks for those sources first.
    for fname in plan.delete:
        print(f"[ingest] deleting removed source {fname}", file=sys.stderr)
        store.delete_by_source(fname)
        manifest.drop_source(fname)
    for fname in plan.update:
        store.delete_by_source(fname)

    to_embed = plan.add + plan.update
    if plan.rebuild_all:
        to_embed = present
        # Stale entries for files no longer present were handled via delete above.

    failed: list[str] = []
    for fname in to_embed:
        try:
            n = _embed_source(fname, cfg, embedder, store, manifest)
            if n == 0:
                print(
                    f"[ingest] WARNING: {fname} produced no text — it may be a scanned/"
                    "image-only PDF (no selectable text) or an empty file. Skipping.",
                    file=sys.stderr,
                )
                failed.append(fname)
        except Exception as e:  # one bad PDF must not abort the whole run
            print(
                f"[ingest] WARNING: could not process {fname} "
                f"({type(e).__name__}: {e}). It may be corrupt or password-protected. "
                "Skipping and continuing with the rest.",
                file=sys.stderr,
            )
            store.delete_by_source(fname)  # ensure no partial chunks linger
            manifest.drop_source(fname)
            failed.append(fname)

    summary["failed"] = failed

    manifest.embedding_model = cfg.embedding.model
    manifest.embedding_dim = cfg.embedding.dim
    manifest.chunk_params = cfg.chunk_params()
    manifest.collection = cfg.collection
    manifest.save(cfg.manifest_path)

    summary["total_chunks"] = store.count()
    return summary
