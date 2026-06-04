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
    raw: dict = field(default_factory=dict, repr=False)

    def chunk_params(self) -> dict:
        """The subset of params that, if changed, invalidates the whole store."""
        return {
            "chunk_tokens": self.chunking.chunk_tokens,
            "chunk_overlap_tokens": self.chunking.chunk_overlap_tokens,
            "min_chunk_tokens": self.chunking.min_chunk_tokens,
        }


def _resolve(root: Path, value: str) -> Path:
    p = Path(value)
    return p if p.is_absolute() else (root / p)


def load_config(path: Path | None = None) -> Config:
    cfg_path = path or CONFIG_PATH
    with open(cfg_path, "rb") as f:
        raw = tomllib.load(f)

    root = cfg_path.resolve().parent
    emb = raw["embedding"]
    chunk = raw["chunking"]
    paths = raw["paths"]
    store = raw["store"]

    data_dir = _resolve(root, paths["data_dir"])
    return Config(
        embedding=EmbeddingConfig(
            model=emb["model"],
            dim=int(emb["dim"]),
            max_seq_tokens=int(emb["max_seq_tokens"]),
            batch_size=int(emb["batch_size"]),
            query_instruction=emb["query_instruction"],
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
        raw=raw,
    )
