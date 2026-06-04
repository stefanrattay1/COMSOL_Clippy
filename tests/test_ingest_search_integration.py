"""Full end-to-end integration: ingest a tiny corpus, then search it.

This is the heaviest test in the suite — it loads the real embedding model
(torch + sentence-transformers + the ~1.5B model download/load) and a real
ChromaDB. So it is gated twice:

  * marked `integration` (deselected by default), and
  * additionally skipped unless `COMSOL_CLIPPY_MODEL_TESTS=1` is set, so even
    `pytest -m integration` won't pull the model unless you ask for it.

Run it explicitly:

    COMSOL_CLIPPY_MODEL_TESTS=1 pytest -m integration tests/test_ingest_search_integration.py

It builds its own tiny config.toml + a .txt source in a tmp dir, so it never
touches your real data/ or source/.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

if not os.environ.get("COMSOL_CLIPPY_MODEL_TESTS"):
    pytest.skip(
        "model-backed test: set COMSOL_CLIPPY_MODEL_TESTS=1 to run",
        allow_module_level=True,
    )

pytest.importorskip("chromadb")
pytest.importorskip("torch")
pytest.importorskip("sentence_transformers")

from comsol_clippy.config import load_config  # noqa: E402
from comsol_clippy.ingest import run_ingest  # noqa: E402
from comsol_clippy.server import Engine  # noqa: E402

# A small model keeps the test feasible; override via env if you want the real one.
TEST_MODEL = os.environ.get(
    "COMSOL_CLIPPY_TEST_MODEL", "sentence-transformers/all-MiniLM-L6-v2"
)
TEST_DIM = int(os.environ.get("COMSOL_CLIPPY_TEST_DIM", "384"))

CONFIG_TEMPLATE = """
[embedding]
model = "{model}"
dim = {dim}
max_seq_tokens = 256
batch_size = 4
query_instruction = "find relevant passages"
instruction_format = "none"

[chunking]
chunk_tokens = 64
chunk_overlap_tokens = 8
min_chunk_tokens = 4

[paths]
source_dir = "source"
data_dir = "data"
chroma_subdir = "chroma"
manifest_name = "manifest.json"

[store]
collection = "itest_docs"

[search]
min_relevance = 0.0
"""


def _build_corpus(root: Path) -> Path:
    src = root / "source"
    src.mkdir()
    (src / "thermal.txt").write_text(
        "Conjugate heat transfer couples conduction in a solid with convection "
        "in an adjacent fluid. COMSOL solves the energy equation across both.\n"
    )
    (src / "flow.txt").write_text(
        "Laminar flow is governed by the Navier-Stokes equations at low Reynolds "
        "number. Turbulence models such as k-epsilon apply at higher Reynolds.\n"
    )
    cfg_path = root / "config.toml"
    cfg_path.write_text(CONFIG_TEMPLATE.format(model=TEST_MODEL, dim=TEST_DIM))
    return cfg_path


def test_ingest_then_search_end_to_end(tmp_path: Path):
    cfg_path = _build_corpus(tmp_path)
    cfg = load_config(cfg_path)

    summary = run_ingest(cfg)
    assert summary["total_chunks"] > 0
    assert not summary["failed"]
    assert set(summary["added"]) == {"thermal.txt", "flow.txt"}

    engine = Engine(cfg)

    # Semantic search should surface the thermal passage for a thermal query.
    hits = engine.search("conjugate heat transfer between solid and fluid", top_k=3)
    assert hits, "expected at least one hit"
    top = hits[0]
    assert top["metadata"]["source"] == "thermal.txt"
    assert 0.0 <= top["relevance"] <= 1.0

    # The query-embedding cache must be transparent: the identical query a second
    # time (served from cache) yields identical results.
    hits_again = engine.search("conjugate heat transfer between solid and fluid", top_k=3)
    assert hits_again == hits

    # list_sources reflects what we ingested.
    sources = {s["source"] for s in engine.list_sources()}
    assert sources == {"thermal.txt", "flow.txt"}


def test_reingest_is_incremental_noop(tmp_path: Path):
    cfg_path = _build_corpus(tmp_path)
    cfg = load_config(cfg_path)

    first = run_ingest(cfg)
    # Nothing changed on disk, so a second run should add/update nothing.
    second = run_ingest(cfg)
    assert second["added"] == [] and second["updated"] == []
    assert second["total_chunks"] == first["total_chunks"]
