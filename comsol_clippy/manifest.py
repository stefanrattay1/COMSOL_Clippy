"""Manifest: links the vectorstore to its source files via sha256 hashes, and
computes the incremental work plan for re-embedding.
"""
from __future__ import annotations

import hashlib
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1


def sha256_file(path: Path, block_size: int = 1 << 20) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for block in iter(lambda: f.read(block_size), b""):
            h.update(block)
    return h.hexdigest()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Manifest:
    embedding_model: str = ""
    embedding_dim: int = 0
    chunk_params: dict = field(default_factory=dict)
    collection: str = ""
    updated_at: str = ""
    sources: dict = field(default_factory=dict)
    schema_version: int = SCHEMA_VERSION

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        if not path.exists():
            return cls()
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return cls(
            embedding_model=data.get("embedding_model", ""),
            embedding_dim=data.get("embedding_dim", 0),
            chunk_params=data.get("chunk_params", {}),
            collection=data.get("collection", ""),
            updated_at=data.get("updated_at", ""),
            sources=data.get("sources", {}),
            schema_version=data.get("schema_version", SCHEMA_VERSION),
        )

    def save(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.updated_at = _now()
        payload = {
            "schema_version": self.schema_version,
            "embedding_model": self.embedding_model,
            "embedding_dim": self.embedding_dim,
            "chunk_params": self.chunk_params,
            "collection": self.collection,
            "updated_at": self.updated_at,
            "sources": self.sources,
        }
        tmp = path.with_suffix(path.suffix + ".tmp")
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)
        os.replace(tmp, path)

    def set_source(self, filename: str, *, sha256: str, size: int, mtime: float,
                   page_count: int, chunk_ids: list[str]) -> None:
        self.sources[filename] = {
            "sha256": sha256,
            "size_bytes": size,
            "mtime": mtime,
            "page_count": page_count,
            "chunk_count": len(chunk_ids),
            "chunk_ids": chunk_ids,
            "embedded_at": _now(),
        }

    def drop_source(self, filename: str) -> None:
        self.sources.pop(filename, None)


@dataclass
class Plan:
    add: list[str] = field(default_factory=list)
    update: list[str] = field(default_factory=list)
    delete: list[str] = field(default_factory=list)
    rebuild_all: bool = False
    reason: str = ""

    def is_empty(self) -> bool:
        return not (self.add or self.update or self.delete or self.rebuild_all)


def compute_plan(
    source_dir: Path,
    manifest: Manifest,
    *,
    current_model: str,
    current_chunk_params: dict,
    collection_exists: bool,
    chunks_present: "callable",  # (chunk_ids) -> bool
) -> Plan:
    """Decide what to (re)embed. See plan doc for the algorithm."""
    from .pdf import list_sources

    present = list_sources(source_dir)  # PDFs and text files alike

    # Global invalidation -> full rebuild.
    if (
        manifest.embedding_model != current_model
        or manifest.chunk_params != current_chunk_params
        or not collection_exists
    ):
        reason = (
            "store/collection missing" if not collection_exists
            else "embedding model or chunk params changed"
        )
        return Plan(add=present, rebuild_all=True, reason=reason)

    add, update, delete = [], [], []
    for fname in present:
        path = source_dir / fname
        entry = manifest.sources.get(fname)
        if entry is None:
            add.append(fname)
            continue
        if entry.get("sha256") != sha256_file(path):
            update.append(fname)
        elif not chunks_present(entry.get("chunk_ids", [])):
            # Hash matches but chunks vanished from the store -> repair drift.
            update.append(fname)

    for fname in manifest.sources:
        if fname not in present:
            delete.append(fname)

    return Plan(add=add, update=update, delete=delete)
