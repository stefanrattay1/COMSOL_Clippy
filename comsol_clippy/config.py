"""Configuration loading and path resolution.

All generated/source paths resolve relative to the project root (the directory
containing this package), so a WSL launch and a Windows launch of the same code
agree on where the vectorstore and manifest live.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:  # pragma: no cover
    import tomli as tomllib  # type: ignore

# Project root = parent of this package directory.
PROJECT_ROOT = Path(__file__).resolve().parent.parent
CONFIG_PATH = PROJECT_ROOT / "config.toml"


@dataclass(frozen=True)
class EmbeddingConfig:
    model: str
    dim: int
    max_seq_tokens: int
    batch_size: int
    query_instruction: str
    instruction_format: str = "qwen-instruct"  # "st-prompt" | "qwen-instruct" | "none"
    cache_size: int = 256  # bounded LRU of query->embedding; 0 disables caching


@dataclass(frozen=True)
class ChunkingConfig:
    chunk_tokens: int
    chunk_overlap_tokens: int
    min_chunk_tokens: int


@dataclass(frozen=True)
class Config:
    embedding: EmbeddingConfig
    chunking: ChunkingConfig
    source_dir: Path
    data_dir: Path
    chroma_dir: Path
    manifest_path: Path
    collection: str
    min_relevance: float = 0.0
    raw: dict = field(default_factory=dict, repr=False)

    def chunk_params(self) -> dict:
        """The subset of params that, if changed, invalidates the whole store."""
        return {
            "chunk_tokens": self.chunking.chunk_tokens,
            "chunk_overlap_tokens": self.chunking.chunk_overlap_tokens,
            "min_chunk_tokens": self.chunking.min_chunk_tokens,
        }

    def validate(self) -> None:
        """Check cross-field invariants and fail loudly at load time.

        Without this, a bad value (e.g. overlap >= chunk size) surfaces deep in
        ingest or the first query as an obscure error. Aggregate every problem so
        the user fixes them in one pass.
        """
        e, c = self.embedding, self.chunking
        problems: list[str] = []
        if c.chunk_tokens < 1:
            problems.append(f"[chunking].chunk_tokens must be >= 1 (got {c.chunk_tokens})")
        if c.chunk_overlap_tokens < 0:
            problems.append(
                f"[chunking].chunk_overlap_tokens must be >= 0 (got {c.chunk_overlap_tokens})"
            )
        if c.chunk_overlap_tokens >= c.chunk_tokens:
            problems.append(
                "[chunking].chunk_overlap_tokens must be < chunk_tokens "
                f"(got {c.chunk_overlap_tokens} >= {c.chunk_tokens})"
            )
        if c.min_chunk_tokens < 0:
            problems.append(f"[chunking].min_chunk_tokens must be >= 0 (got {c.min_chunk_tokens})")
        if e.batch_size < 1:
            problems.append(f"[embedding].batch_size must be >= 1 (got {e.batch_size})")
        if e.dim < 1:
            problems.append(f"[embedding].dim must be >= 1 (got {e.dim})")
        if e.max_seq_tokens < 1:
            problems.append(f"[embedding].max_seq_tokens must be >= 1 (got {e.max_seq_tokens})")
        if e.cache_size < 0:
            problems.append(f"[embedding].cache_size must be >= 0 (got {e.cache_size})")
        if e.instruction_format not in {"st-prompt", "qwen-instruct", "none"}:
            problems.append(
                "[embedding].instruction_format must be one of "
                f"st-prompt, qwen-instruct, none (got {e.instruction_format!r})"
            )
        if not 0.0 <= self.min_relevance <= 1.0:
            problems.append(
                f"[search].min_relevance must be in [0.0, 1.0] (got {self.min_relevance})"
            )
        if problems:
            raise ValueError("invalid config.toml:\n  - " + "\n  - ".join(problems))


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or CONFIG_PATH
    with open(cfg_path, "rb") as f:
        raw = tomllib.load(f)

    root = cfg_path.resolve().parent
    for section in ("embedding", "chunking", "paths", "store"):
        if section not in raw:
            raise ValueError(f"config.toml is missing the required [{section}] section")
    emb = raw["embedding"]
    chunk = raw["chunking"]
    paths = raw["paths"]
    store = raw["store"]
    search = raw.get("search", {})  # optional section; defaults below

    data_dir = _resolve(root, paths["data_dir"])
    cfg = Config(
        embedding=EmbeddingConfig(
            model=emb["model"],
            dim=int(emb["dim"]),
            max_seq_tokens=int(emb["max_seq_tokens"]),
            batch_size=int(emb["batch_size"]),
            query_instruction=emb["query_instruction"],
            instruction_format=emb.get("instruction_format", "qwen-instruct"),
            cache_size=int(emb.get("cache_size", 256)),
        ),
        chunking=ChunkingConfig(
            chunk_tokens=int(chunk["chunk_tokens"]),
            chunk_overlap_tokens=int(chunk["chunk_overlap_tokens"]),
            min_chunk_tokens=int(chunk["min_chunk_tokens"]),
        ),
        source_dir=_resolve(root, paths["source_dir"]),
        data_dir=data_dir,
        chroma_dir=data_dir / paths["chroma_subdir"],
        manifest_path=data_dir / paths["manifest_name"],
        collection=store["collection"],
        min_relevance=float(search.get("min_relevance", 0.0)),
        raw=raw,
    )
    cfg.validate()
    return cfg
