"""PDF text extraction and page-aware, token-aware chunking.

Uses PyMuPDF (fitz) for robust extraction on large multi-column COMSOL manuals.
Each chunk carries the source filename, its page span, and a deterministic index
so re-embedding upserts cleanly.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

# PyMuPDF (fitz) is imported lazily inside the functions that touch PDFs so that
# the pure-logic helpers (chunking, citations) — and CI — don't need it installed.


@dataclass
class Chunk:
    text: str
    source: str          # PDF filename (e.g. "HeatTransferModuleUsersGuide.pdf")
    page: int            # 1-based page where the chunk starts
    page_end: int        # 1-based page where the chunk ends (== page if single-page)
    chunk_index: int     # sequential index within the source

    @property
    def chunk_id(self) -> str:
        stem = Path(self.source).stem
        return f"{stem}:{self.chunk_index:05d}"

    def metadata(self) -> dict:
        return {
            "source": self.source,
            "page": self.page,
            "page_end": self.page_end,
            "chunk_index": self.chunk_index,
        }


_WS_RE = re.compile(r"[ \t]+")
_NL_RE = re.compile(r"\n{3,}")


def _normalize(text: str) -> str:
    text = text.replace("\r", "\n")
    text = _WS_RE.sub(" ", text)
    text = _NL_RE.sub("\n\n", text)
    return text.strip()


# Supported source file extensions (lower-case). PDFs are page-aware; the rest are
# plain text, chunked by token window and cited by chunk number instead of page.
PDF_EXTS = {".pdf"}
TEXT_EXTS = {".txt", ".md", ".markdown", ".rst", ".csv", ".text"}
SUPPORTED_EXTS = PDF_EXTS | TEXT_EXTS


def list_sources(source_dir: Path) -> list[str]:
    """Return supported source filenames in source_dir, case-insensitively.

    Handles both PDFs and plain-text files (.txt/.md/.rst/.csv...). Matching is
    case-insensitive (so Manual.PDF is found on Linux/WSL too); deduped and sorted.
    """
    names = {
        p.name
        for p in source_dir.iterdir()
        if p.is_file() and p.suffix.lower() in SUPPORTED_EXTS
    }
    return sorted(names)


# Backwards-compatible alias.
def list_pdfs(source_dir: Path) -> list[str]:
    return list_sources(source_dir)


def is_pdf(filename: str) -> bool:
    return Path(filename).suffix.lower() in PDF_EXTS


def extract_pages(pdf_path: Path) -> list[str]:
    """Return normalized text for each page (index 0 == page 1)."""
    import fitz  # PyMuPDF

    pages: list[str] = []
    with fitz.open(pdf_path) as doc:
        for page in doc:
            pages.append(_normalize(page.get_text("text")))
    return pages


def page_count(path: Path) -> int:
    """Page count for PDFs; 0 for text files (which have no pages)."""
    if not is_pdf(path.name):
        return 0
    import fitz  # PyMuPDF

    with fitz.open(path) as doc:
        return doc.page_count


def read_text_file(path: Path) -> str:
    """Read a plain-text source, tolerant of encoding issues."""
    raw = path.read_bytes()
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            return _normalize(raw.decode(enc))
        except UnicodeDecodeError:
            continue
    return _normalize(raw.decode("utf-8", errors="replace"))


def _window_chunks(
    token_ids: list[int],
    token_pages: list[int],
    source: str,
    *,
    decode: Callable[[list[int]], str],
    chunk_tokens: int,
    overlap_tokens: int,
    min_chunk_tokens: int,
) -> list[Chunk]:
    """Slide a token window over a flat token stream, tracking page spans.

    `token_pages[i]` is the 1-based page the token came from, or 0 for page-less
    text files (rendered as a chunk number in citations).
    """
    chunks: list[Chunk] = []
    if not token_ids:
        return chunks

    step = max(1, chunk_tokens - overlap_tokens)
    idx = 0
    chunk_index = 0
    n = len(token_ids)
    while idx < n:
        window_ids = token_ids[idx : idx + chunk_tokens]
        if len(window_ids) < min_chunk_tokens and chunk_index > 0:
            # Trailing fragment smaller than the floor: skip (covered by overlap).
            break
        window_pages = token_pages[idx : idx + chunk_tokens]
        text = decode(window_ids).strip()
        if text:
            chunks.append(
                Chunk(
                    text=text,
                    source=source,
                    page=window_pages[0],
                    page_end=window_pages[-1],
                    chunk_index=chunk_index,
                )
            )
            chunk_index += 1
        idx += step

    return chunks


def chunk_file(
    path: Path,
    *,
    encode: Callable[[str], list[int]],
    decode: Callable[[list[int]], str],
    chunk_tokens: int,
    overlap_tokens: int,
    min_chunk_tokens: int,
) -> list[Chunk]:
    """Chunk any supported source file (PDF or text) into token windows.

    PDFs carry real page numbers; text files use page=0 (cited by chunk number).
    `encode`/`decode` are the embedding tokenizer's id<->text functions so chunk
    sizes are measured in real model tokens.
    """
    source = path.name
    token_ids: list[int] = []
    token_pages: list[int] = []

    if is_pdf(source):
        for page_idx, page_text in enumerate(extract_pages(path), start=1):
            if not page_text:
                continue
            ids = encode(page_text)
            token_ids.extend(ids)
            token_pages.extend([page_idx] * len(ids))
    else:
        text = read_text_file(path)
        if text:
            ids = encode(text)
            token_ids.extend(ids)
            token_pages.extend([0] * len(ids))  # 0 == no page (text file)

    return _window_chunks(
        token_ids,
        token_pages,
        source,
        decode=decode,
        chunk_tokens=chunk_tokens,
        overlap_tokens=overlap_tokens,
        min_chunk_tokens=min_chunk_tokens,
    )


# Backwards-compatible alias.
def chunk_pdf(path: Path, **kwargs) -> list[Chunk]:
    return chunk_file(path, **kwargs)
