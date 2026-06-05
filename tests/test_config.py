"""Tests for config loading + validation.

Pure logic only: tomllib/tomli is stdlib, and load_config just resolves paths and
checks invariants — no embedding model, no ChromaDB. We write a temp config.toml
and load it.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from comsol_clippy.config import load_config

VALID = """
[embedding]
model = "test-model"
dim = 1536
max_seq_tokens = 8192
batch_size = 8
instruction_format = "st-prompt"
query_instruction = "find relevant passages"

[chunking]
chunk_tokens = 512
chunk_overlap_tokens = 64
min_chunk_tokens = 64

[paths]
source_dir = "source"
data_dir = "data"
chroma_subdir = "chroma"
manifest_name = "manifest.json"

[store]
collection = "comsol_docs"

[search]
min_relevance = 0.0
"""


def _write_config(d: Path, text: str) -> Path:
    p = d / "config.toml"
    p.write_text(text)
    return p


def test_loads_valid_config(tmp_path: Path):
    cfg = load_config(_write_config(tmp_path, VALID))
    assert cfg.embedding.model == "test-model"
    assert cfg.chunking.chunk_tokens == 512
    assert cfg.collection == "comsol_docs"
    # Relative paths resolve against the config's directory.
    assert cfg.chroma_dir == tmp_path / "data" / "chroma"
    assert cfg.manifest_path == tmp_path / "data" / "manifest.json"


def test_overlap_must_be_less_than_chunk_tokens(tmp_path: Path):
    bad = VALID.replace("chunk_overlap_tokens = 64", "chunk_overlap_tokens = 512")
    with pytest.raises(ValueError, match="chunk_overlap_tokens must be < chunk_tokens"):
        load_config(_write_config(tmp_path, bad))


def test_batch_size_must_be_positive(tmp_path: Path):
    bad = VALID.replace("batch_size = 8", "batch_size = 0")
    with pytest.raises(ValueError, match="batch_size must be >= 1"):
        load_config(_write_config(tmp_path, bad))


def test_cache_size_defaults_and_loads(tmp_path: Path):
    cfg = load_config(_write_config(tmp_path, VALID))
    assert cfg.embedding.cache_size == 256  # default when not in config.toml


def test_cache_size_must_be_non_negative(tmp_path: Path):
    bad = VALID.replace("batch_size = 8", "batch_size = 8\ncache_size = -1")
    with pytest.raises(ValueError, match="cache_size must be >= 0"):
        load_config(_write_config(tmp_path, bad))


def test_instruction_format_must_be_supported(tmp_path: Path):
    bad = VALID.replace('instruction_format = "st-prompt"', 'instruction_format = "bogus"')
    with pytest.raises(ValueError, match="instruction_format must be one of"):
        load_config(_write_config(tmp_path, bad))


def test_min_relevance_must_be_in_range(tmp_path: Path):
    bad = VALID.replace("min_relevance = 0.0", "min_relevance = 1.5")
    with pytest.raises(ValueError, match="min_relevance must be in"):
        load_config(_write_config(tmp_path, bad))


def test_missing_section_is_clear(tmp_path: Path):
    bad = VALID.replace("[store]\ncollection = \"comsol_docs\"\n", "")
    with pytest.raises(ValueError, match=r"missing the required \[store\] section"):
        load_config(_write_config(tmp_path, bad))


def test_aggregates_multiple_problems(tmp_path: Path):
    bad = VALID.replace("batch_size = 8", "batch_size = 0").replace(
        "chunk_overlap_tokens = 64", "chunk_overlap_tokens = 999"
    )
    with pytest.raises(ValueError) as exc:
        load_config(_write_config(tmp_path, bad))
    msg = str(exc.value)
    assert "batch_size" in msg and "chunk_overlap_tokens" in msg
