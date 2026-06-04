"""FastMCP server exposing COMSOL doc search over stdio.

The embedding model and store are loaded lazily on first tool call so the stdio
handshake isn't blocked by the 1.5B model load.
"""
from __future__ import annotations

import sys
import threading

from .config import Config, load_config
from .embeddings import Embedder
from .manifest import Manifest
from .store import Store


class Engine:
    """Lazily-initialized search engine shared by the MCP server and the CLI.

    Loading is guarded by a lock so a background pre-warm and the first real query
    can't load the 1.5B model twice; whichever arrives second just waits.
    """

    def __init__(self, cfg: Config | None = None):
        self.cfg = cfg or load_config()
        self._embedder: Embedder | None = None
        self._store: Store | None = None
        self._lock = threading.Lock()

    @property
    def store(self) -> Store:
        if self._store is None:
            with self._lock:
                if self._store is None:
                    self._store = Store(self.cfg.chroma_dir, self.cfg.collection)
        return self._store

    @property
    def embedder(self) -> Embedder:
        if self._embedder is None:
            with self._lock:
                if self._embedder is None:
                    self._embedder = Embedder(self.cfg.embedding)
        return self._embedder

    def prewarm(self) -> None:
        """Load the model + store now (so the user's first question isn't slow)."""
        try:
            _ = self.store
            _ = self.embedder
            print("[server] model pre-warmed; ready for queries.", file=sys.stderr)
        except Exception as e:  # never let pre-warm kill the server
            print(f"[server] pre-warm skipped ({type(e).__name__}: {e})", file=sys.stderr)

    def prewarm_async(self) -> None:
        threading.Thread(target=self.prewarm, name="prewarm", daemon=True).start()

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        vec = self.embedder.embed_query(query)
        return self.store.query(vec, top_k)

    def list_sources(self) -> list[dict]:
        manifest = Manifest.load(self.cfg.manifest_path)
        out = []
        for name, e in sorted(manifest.sources.items()):
            out.append(
                {
                    "source": name,
                    "pages": e.get("page_count", 0),
                    "chunks": e.get("chunk_count", 0),
                }
            )
        return out


def _citation(meta: dict) -> str:
    src = meta.get("source", "?")
    page = meta.get("page")
    page_end = meta.get("page_end", page)
    chunk_index = meta.get("chunk_index", 0)
    # page == 0 (or None) means a page-less text file: cite by chunk number instead.
    if not page:
        return f"[{src} #{chunk_index + 1}]"
    if page_end and page_end != page:
        return f"[{src} p.{page}–{page_end}]"
    return f"[{src} p.{page}]"


def format_hits(hits: list[dict]) -> str:
    if not hits:
        return "No matching passages found in the COMSOL manuals."
    blocks = []
    for h in hits:
        cite = _citation(h["metadata"])
        rel = h.get("relevance", 0.0)
        blocks.append(f"{cite} (relevance {rel:.2f})\n{h['text']}")
    return "\n\n---\n\n".join(blocks)


def build_server(cfg: Config | None = None):
    from mcp.server.fastmcp import FastMCP

    engine = Engine(cfg)
    mcp = FastMCP("comsol-clippy")

    @mcp.tool()
    def search_comsol_docs(query: str, top_k: int = 5) -> str:
        """Search the COMSOL Multiphysics manuals for passages relevant to a question.

        Returns the most relevant passages, each prefixed with a citation of the
        source manual and page number, e.g. [HeatTransferModuleUsersGuide.pdf p.412].
        """
        hits = engine.search(query, top_k=top_k)
        return format_hits(hits)

    @mcp.tool()
    def list_sources() -> str:
        """List the indexed COMSOL documents with their page and chunk counts.

        Useful as a first call so you know what material is available to search.
        """
        rows = engine.list_sources()
        if not rows:
            return "No sources indexed yet. Run `python main.py ingest`."
        lines = []
        for r in rows:
            extent = f"{r['pages']} pages" if r["pages"] else "text"
            lines.append(f"- {r['source']}: {extent}, {r['chunks']} chunks")
        return "Indexed COMSOL documents:\n" + "\n".join(lines)

    # Start loading the model in the background so the first user query is fast.
    engine.prewarm_async()
    return mcp


def serve(cfg: Config | None = None) -> None:
    build_server(cfg).run()  # stdio transport by default
