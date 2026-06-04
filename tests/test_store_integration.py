"""Integration tests for the ChromaDB-backed Store.

These hit a *real* ChromaDB persistent client (in a tmp dir) but use hand-built
vectors instead of the embedding model, so they need `chromadb` installed but not
torch / sentence-transformers / the 1.5B model.

Opt-in: marked `integration` and deselected by default (see pyproject). Run with
`pytest -m integration`. They `importorskip("chromadb")` so they skip cleanly if
the dep isn't present.
"""
from __future__ import annotations

from pathlib import Path

import pytest

pytest.importorskip("chromadb")

from comsol_clippy.pdf import Chunk  # noqa: E402
from comsol_clippy.store import Store  # noqa: E402

pytestmark = pytest.mark.integration


def _chunk(source: str, idx: int, text: str, page: int = 1, page_end: int | None = None) -> Chunk:
    return Chunk(text=text, source=source, page=page, page_end=page_end or page, chunk_index=idx)


def _store(tmp_path: Path) -> Store:
    return Store(tmp_path / "chroma", "test_docs")


def test_exists_is_false_before_anything_is_written(tmp_path: Path):
    st = _store(tmp_path)
    # No collection has been created yet (the property is lazy), so exists() is False.
    assert st.exists() is False


def test_upsert_then_count_and_exists(tmp_path: Path):
    st = _store(tmp_path)
    chunks = [_chunk("A.pdf", 0, "alpha"), _chunk("A.pdf", 1, "beta")]
    st.upsert_chunks(chunks, [[1.0, 0.0], [0.0, 1.0]])
    assert st.count() == 2
    assert st.exists() is True
    assert st.has_all(["A:00000", "A:00001"]) is True
    assert st.has_all(["A:00000", "A:99999"]) is False


def test_query_returns_metadata_and_clamped_relevance(tmp_path: Path):
    st = _store(tmp_path)
    chunks = [
        _chunk("A.pdf", 0, "near", page=10, page_end=11),
        _chunk("A.pdf", 1, "far"),
    ]
    # Two orthogonal-ish unit vectors; query identical to the first.
    st.upsert_chunks(chunks, [[1.0, 0.0], [-1.0, 0.0]])
    hits = st.query([1.0, 0.0], top_k=2)

    assert len(hits) == 2
    top = hits[0]
    assert top["text"] == "near"
    assert top["metadata"]["source"] == "A.pdf"
    assert top["metadata"]["page"] == 10 and top["metadata"]["page_end"] == 11
    # Identical vector -> cosine distance ~0 -> relevance ~1.
    assert top["relevance"] == pytest.approx(1.0, abs=1e-3)
    # Opposed vector -> cosine distance ~2 -> relevance clamps to 0, never negative.
    assert all(0.0 <= h["relevance"] <= 1.0 for h in hits)
    assert hits[1]["relevance"] == pytest.approx(0.0, abs=1e-3)


def test_upsert_is_idempotent_on_same_ids(tmp_path: Path):
    st = _store(tmp_path)
    c = _chunk("A.pdf", 0, "v1")
    st.upsert_chunks([c], [[1.0, 0.0]])
    # Re-upsert the same id with new text/vector: count stays 1, content updates.
    c2 = _chunk("A.pdf", 0, "v2")
    st.upsert_chunks([c2], [[0.0, 1.0]])
    assert st.count() == 1
    hits = st.query([0.0, 1.0], top_k=1)
    assert hits[0]["text"] == "v2"


def test_delete_by_source_only_removes_that_source(tmp_path: Path):
    st = _store(tmp_path)
    st.upsert_chunks(
        [_chunk("A.pdf", 0, "a0"), _chunk("A.pdf", 1, "a1"), _chunk("B.pdf", 0, "b0")],
        [[1.0, 0.0], [0.9, 0.1], [0.0, 1.0]],
    )
    assert st.count() == 3
    st.delete_by_source("A.pdf")
    assert st.count() == 1
    remaining = st.query([0.0, 1.0], top_k=5)
    assert {h["metadata"]["source"] for h in remaining} == {"B.pdf"}


def test_persistence_across_client_reopen(tmp_path: Path):
    st = _store(tmp_path)
    st.upsert_chunks([_chunk("A.pdf", 0, "persisted")], [[1.0, 0.0]])
    # A fresh Store over the same dir must see the persisted data.
    st2 = Store(tmp_path / "chroma", "test_docs")
    assert st2.exists() is True
    assert st2.count() == 1


def test_empty_upsert_is_a_noop(tmp_path: Path):
    st = _store(tmp_path)
    st.upsert_chunks([], [])
    assert st.count() == 0
