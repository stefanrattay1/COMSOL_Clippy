"""Tests for the token-window chunker (page-span tracking, overlap, fragment skip).

Uses a fake decode so no embedding tokenizer is needed: tokens are just ints and
decode joins them, which is enough to verify the windowing math and metadata.
"""
from __future__ import annotations

from comsol_clippy.pdf import Chunk, _window_chunks


def _decode(ids):
    return " ".join(str(i) for i in ids)


def _chunks(token_ids, token_pages, *, chunk_tokens, overlap_tokens, min_chunk_tokens):
    return _window_chunks(
        token_ids,
        token_pages,
        "src.pdf",
        decode=_decode,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
    )


def test_empty_input_yields_no_chunks():
    assert _chunks([], [], chunk_tokens=4, overlap_tokens=1, min_chunk_tokens=1) == []


def test_window_step_respects_overlap():
    ids = list(range(10))
    pages = [1] * 10
    # chunk=4, overlap=1 -> step=3 -> starts at 0,3,6,9
    chunks = _chunks(ids, pages, chunk_tokens=4, overlap_tokens=1, min_chunk_tokens=1)
    assert [c.text.split()[0] for c in chunks] == ["0", "3", "6", "9"]
    # overlap: chunk0 ends at token 3, chunk1 starts at token 3
    assert chunks[0].text.split()[-1] == "3"
    assert chunks[1].text.split()[0] == "3"


def test_chunk_index_is_monotonic():
    ids = list(range(20))
    chunks = _chunks(ids, [1] * 20, chunk_tokens=5, overlap_tokens=0, min_chunk_tokens=1)
    assert [c.chunk_index for c in chunks] == list(range(len(chunks)))


def test_trailing_fragment_below_min_is_skipped():
    # 11 tokens, chunk=5 overlap=0 -> windows at 0,5,10. Last window has 1 token (<min).
    ids = list(range(11))
    chunks = _chunks(ids, [1] * 11, chunk_tokens=5, overlap_tokens=0, min_chunk_tokens=3)
    starts = [c.text.split()[0] for c in chunks]
    assert "10" not in starts  # trailing 1-token fragment dropped
    assert starts == ["0", "5"]


def test_first_chunk_below_min_is_kept():
    # The skip only applies to trailing fragments (chunk_index > 0); a lone short
    # document still produces its single chunk.
    ids = [1, 2]
    chunks = _chunks(ids, [1, 1], chunk_tokens=5, overlap_tokens=0, min_chunk_tokens=3)
    assert len(chunks) == 1
    assert chunks[0].chunk_index == 0


def test_page_span_tracking():
    # 6 tokens: first 3 on page 1, next 3 on page 2. chunk=4 overlap=0 -> step 4.
    ids = list(range(6))
    pages = [1, 1, 1, 2, 2, 2]
    chunks = _chunks(ids, pages, chunk_tokens=4, overlap_tokens=0, min_chunk_tokens=1)
    # chunk0 spans tokens 0..3 -> pages 1..2
    assert chunks[0].page == 1
    assert chunks[0].page_end == 2
    # chunk1 spans tokens 4..5 -> page 2 only
    assert chunks[1].page == 2
    assert chunks[1].page_end == 2


def test_chunk_id_and_metadata():
    c = Chunk(text="x", source="HeatTransfer.pdf", page=4, page_end=5, chunk_index=12)
    assert c.chunk_id == "HeatTransfer:00012"
    meta = c.metadata()
    assert meta == {
        "source": "HeatTransfer.pdf",
        "page": 4,
        "page_end": 5,
        "chunk_index": 12,
    }
