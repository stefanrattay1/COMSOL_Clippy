"""Tests for citation formatting and hit rendering (pure string logic)."""
from __future__ import annotations

from comsol_clippy.server import _citation, format_hits


def test_citation_single_page():
    assert _citation({"source": "HT.pdf", "page": 412, "page_end": 412}) == "[HT.pdf p.412]"


def test_citation_page_range():
    cite = _citation({"source": "HT.pdf", "page": 412, "page_end": 413})
    assert cite == "[HT.pdf p.412–413]"


def test_citation_pageless_text_file_uses_chunk_number():
    # page == 0 (text file) -> cite by 1-based chunk number.
    assert _citation({"source": "notes.md", "page": 0, "chunk_index": 4}) == "[notes.md #5]"


def test_citation_missing_source_is_graceful():
    assert _citation({}) == "[? #1]"


def test_format_hits_empty():
    assert "No matching passages" in format_hits([])


def test_format_hits_renders_citation_and_relevance():
    hits = [
        {"text": "conjugate heat transfer ...",
         "metadata": {"source": "HT.pdf", "page": 10, "page_end": 10},
         "relevance": 0.873},
    ]
    out = format_hits(hits)
    assert "[HT.pdf p.10]" in out
    assert "relevance 0.87" in out
    assert "conjugate heat transfer" in out


def test_format_hits_separates_multiple_blocks():
    hits = [
        {"text": "a", "metadata": {"source": "X.pdf", "page": 1, "page_end": 1}, "relevance": 0.5},
        {"text": "b", "metadata": {"source": "Y.pdf", "page": 2, "page_end": 2}, "relevance": 0.4},
    ]
    out = format_hits(hits)
    assert "\n\n---\n\n" in out
