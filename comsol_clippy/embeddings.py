"""Embedding model wrapper around sentence-transformers / Qwen3-VL-Embedding.

- GPU (fp16) when CUDA is available, else CPU.
- Documents are embedded as plain text; queries use the configured prompt strategy.
- Batch size auto-halves on CUDA OOM.
"""
from __future__ import annotations

import sys
import threading
from collections import OrderedDict

from .config import EmbeddingConfig


def detect_device() -> str:
    import torch

    return "cuda" if torch.cuda.is_available() else "cpu"


class Embedder:
    def __init__(self, cfg: EmbeddingConfig, device: str | None = None):
        import torch
        from sentence_transformers import SentenceTransformer

        self.cfg = cfg
        self.device = device or detect_device()
        model_kwargs = {}
        if self.device == "cuda":
            # transformers 5.x renamed `torch_dtype` -> `dtype` (the old name warns).
            model_kwargs["dtype"] = torch.float16

        print(f"[embeddings] loading {cfg.model} on {self.device} ...", file=sys.stderr)
        self.model = SentenceTransformer(
            cfg.model,
            trust_remote_code=True,
            device=self.device,
            model_kwargs=model_kwargs or None,
        )
        self.model.max_seq_length = min(cfg.max_seq_tokens, self.model.max_seq_length or cfg.max_seq_tokens)
        self.tokenizer = self.model.tokenizer

        # Bounded LRU of raw-query-text -> embedding vector. The instruction wrapper is
        # built from frozen per-process cfg, so the raw query determines the embedding
        # uniquely; the daemon respawns on config change, so the cache can't go stale.
        self._qcache: OrderedDict[str, list[float]] = OrderedDict()
        self._qcache_lock = threading.Lock()
        self._qcache_max = cfg.cache_size

    # --- tokenizer helpers used by the chunker ---
    def encode_tokens(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def decode_tokens(self, ids: list[int]) -> str:
        return self.tokenizer.decode(ids, skip_special_tokens=True)

    # --- embedding ---
    def _encode(
        self,
        texts: list[str],
        *,
        prompt_name: str | None = None,
        prompt: str | None = None,
    ) -> list[list[float]]:
        import torch

        batch = self.cfg.batch_size
        while True:
            try:
                vecs = self.model.encode(
                    texts,
                    prompt_name=prompt_name,
                    prompt=prompt,
                    batch_size=batch,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=len(texts) > 32,
                )
                return [v.tolist() for v in vecs]
            except (torch.cuda.OutOfMemoryError, MemoryError, RuntimeError) as e:
                # Catch CUDA OOM, host MemoryError, and the CPU path's
                # RuntimeError("[...] out of memory"). Anything else re-raises.
                if isinstance(e, RuntimeError) and "out of memory" not in str(e).lower():
                    raise
                if self.device == "cuda":
                    torch.cuda.empty_cache()
                if batch <= 1:
                    raise
                batch = max(1, batch // 2)
                print(f"[embeddings] OOM, retrying with batch_size={batch}", file=sys.stderr)

    def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._encode(texts, prompt_name=None)
        if len(vecs[0]) != self.cfg.dim:
            raise ValueError(
                f"Embedding dim {len(vecs[0])} != configured {self.cfg.dim}. "
                "Check the model or update config.toml [embedding].dim."
            )
        return vecs

    def _embed_query_uncached(self, query: str) -> list[float]:
        # Newer Qwen3 VL models accept task steering through SentenceTransformers'
        # prompt=... argument. Older Qwen/GTE instruct models expect the literal
        # "Instruct: <task>\nQuery: <q>" wrapper. Plain models just get the raw text.
        if self.cfg.instruction_format == "st-prompt":
            return self._encode([query], prompt=self.cfg.query_instruction)[0]
        if self.cfg.instruction_format == "qwen-instruct":
            text = f"Instruct: {self.cfg.query_instruction}\nQuery: {query}"
        else:
            text = query
        return self._encode([text], prompt_name=None)[0]

    def embed_query(self, query: str) -> list[float]:
        if self._qcache_max <= 0:
            return self._embed_query_uncached(query)

        # Hit: refresh recency and hand back a copy so callers can't mutate the cache.
        with self._qcache_lock:
            cached = self._qcache.get(query)
            if cached is not None:
                self._qcache.move_to_end(query)
                return list(cached)

        # Miss: compute outside the lock so concurrent queries don't serialize behind
        # one inference. A rare duplicate concurrent miss just recomputes once; the
        # second insert overwrites harmlessly. An OOM that raises never reaches the
        # insert below, so failed embeddings never poison the cache.
        vec = self._embed_query_uncached(query)
        with self._qcache_lock:
            self._qcache[query] = vec
            self._qcache.move_to_end(query)
            while len(self._qcache) > self._qcache_max:
                self._qcache.popitem(last=False)
        return list(vec)
