"""Tests for the incremental ingest plan and manifest persistence.

Pure logic only: no embedding model, no ChromaDB. `compute_plan` takes a
`chunks_present` callable we fake, and `sha256_file` just hashes file bytes, so a
temp dir with dummy files is enough.
"""
from __future__ import annotations

from pathlib import Path

from comsol_clippy.manifest import Manifest, compute_plan, sha256_file

MODEL = "test-model"
CHUNK_PARAMS = {"chunk_tokens": 512, "chunk_overlap_tokens": 64, "min_chunk_tokens": 64}


def _write(d: Path, name: str, body: bytes = b"hello") -> Path:
    p = d / name
    p.write_bytes(body)
    return p


def _manifest_for(d: Path, names: list[str]) -> Manifest:
    """A manifest that already knows about `names` with their current hashes."""
    m = Manifest(embedding_model=MODEL, chunk_params=dict(CHUNK_PARAMS))
    for n in names:
        m.set_source(
            n,
            sha256=sha256_file(d / n),
            size=(d / n).stat().st_size,
            mtime=(d / n).stat().st_mtime,
            page_count=1,
            chunk_ids=[f"{Path(n).stem}:00000"],
        )
    return m


def _plan(d: Path, manifest: Manifest, *, collection_exists=True, chunks_present=lambda ids: True):
    return compute_plan(
        d,
        manifest,
        current_model=MODEL,
        current_chunk_params=CHUNK_PARAMS,
        collection_exists=collection_exists,
        chunks_present=chunks_present,
    )


def test_fresh_store_is_full_rebuild(tmp_path):
    _write(tmp_path, "a.pdf")
    plan = _plan(tmp_path, Manifest(), collection_exists=False)
    assert plan.rebuild_all
    assert plan.add == ["a.pdf"]


def test_model_change_forces_rebuild(tmp_path):
    _write(tmp_path, "a.pdf")
    m = _manifest_for(tmp_path, ["a.pdf"])
    m.embedding_model = "different-model"
    plan = _plan(tmp_path, m)
    assert plan.rebuild_all
    assert "model" in plan.reason


def test_chunk_param_change_forces_rebuild(tmp_path):
    _write(tmp_path, "a.pdf")
    m = _manifest_for(tmp_path, ["a.pdf"])
    m.chunk_params = {"chunk_tokens": 256}  # differs from CHUNK_PARAMS
    plan = _plan(tmp_path, m)
    assert plan.rebuild_all


def test_new_file_is_added(tmp_path):
    _write(tmp_path, "a.pdf")
    _write(tmp_path, "b.pdf")
    m = _manifest_for(tmp_path, ["a.pdf"])  # b is new
    plan = _plan(tmp_path, m)
    assert plan.add == ["b.pdf"]
    assert plan.update == []
    assert plan.delete == []


def test_changed_hash_is_update(tmp_path):
    _write(tmp_path, "a.pdf", b"original")
    m = _manifest_for(tmp_path, ["a.pdf"])
    _write(tmp_path, "a.pdf", b"changed contents")  # rewrite -> new hash
    plan = _plan(tmp_path, m)
    assert plan.update == ["a.pdf"]
    assert plan.add == []


def test_drift_repair_when_chunks_missing(tmp_path):
    """Hash matches but the store lost the chunks -> re-embed (update)."""
    _write(tmp_path, "a.pdf")
    m = _manifest_for(tmp_path, ["a.pdf"])
    plan = _plan(tmp_path, m, chunks_present=lambda ids: False)
    assert plan.update == ["a.pdf"]


def test_removed_file_is_deleted(tmp_path):
    _write(tmp_path, "a.pdf")
    _write(tmp_path, "gone.pdf")
    m = _manifest_for(tmp_path, ["a.pdf", "gone.pdf"])
    (tmp_path / "gone.pdf").unlink()  # now in the manifest but no longer on disk
    plan = _plan(tmp_path, m)
    assert plan.delete == ["gone.pdf"]
    assert plan.add == []


def test_no_op_plan_is_empty(tmp_path):
    _write(tmp_path, "a.pdf")
    m = _manifest_for(tmp_path, ["a.pdf"])
    plan = _plan(tmp_path, m)
    assert plan.is_empty()


def test_text_files_participate_in_plan(tmp_path):
    """Plan covers .md/.txt sources, not just PDFs."""
    _write(tmp_path, "notes.md")
    plan = _plan(tmp_path, Manifest(), collection_exists=False)
    assert "notes.md" in plan.add


def test_manifest_roundtrip_and_atomic_save(tmp_path):
    path = tmp_path / "manifest.json"
    m = Manifest(embedding_model=MODEL, embedding_dim=1536, chunk_params=dict(CHUNK_PARAMS),
                 collection="c")
    m.set_source("a.pdf", sha256="abc", size=10, mtime=1.0, page_count=3,
                 chunk_ids=["a:00000", "a:00001"])
    m.save(path)

    assert not path.with_suffix(path.suffix + ".tmp").exists()  # tmp cleaned up

    loaded = Manifest.load(path)
    assert loaded.embedding_model == MODEL
    assert loaded.embedding_dim == 1536
    assert loaded.chunk_params == CHUNK_PARAMS
    assert loaded.collection == "c"
    assert loaded.sources["a.pdf"]["chunk_count"] == 2
    assert loaded.updated_at  # stamped on save


def test_manifest_load_missing_returns_empty(tmp_path):
    m = Manifest.load(tmp_path / "nope.json")
    assert m.sources == {}
    assert m.embedding_model == ""
