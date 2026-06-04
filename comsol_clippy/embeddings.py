"""Embedding model wrapper around sentence-transformers / gte-Qwen2-1.5B-instruct.

- GPU (fp16) when CUDA is available, else CPU.
- Documents are embedded as plain text; queries get the instruction prefix.
- Batch size auto-halves on CUDA OOM.
"""
from __future__ import annotations

import sys

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
            model_kwargs["torch_dtype"] = torch.float16

        print(f"[embeddings] loading {cfg.model} on {self.device} ...", file=sys.stderr)
        self.model = SentenceTransformer(
            cfg.model,
            trust_remote_code=True,
            device=self.device,
            model_kwargs=model_kwargs or None,
        )
        self.model.max_seq_length = min(cfg.max_seq_tokens, self.model.max_seq_length or cfg.max_seq_tokens)
        self.tokenizer = self.model.tokenizer

    # --- tokenizer helpers used by the chunker ---
    def encode_tokens(self, text: str) -> list[int]:
        return self.tokenizer.encode(text, add_special_tokens=False)

    def decode_tokens(self, ids: list[int]) -> str:
        return self.tokenizer.decode(ids, skip_special_tokens=True)

    # --- embedding ---
    def _encode(self, texts: list[str], *, prompt_name: str | None) -> list[list[float]]:
        import torch

        batch = self.cfg.batch_size
        while True:
            try:
                vecs = self.model.encode(
                    texts,
                    prompt_name=prompt_name,
                    batch_size=batch,
                    normalize_embeddings=True,
                    convert_to_numpy=True,
                    show_progress_bar=len(texts) > 32,
                )
                return [v.tolist() for v in vecs]
            except torch.cuda.OutOfMemoryError:
                torch.cuda.empty_cache()
                if batch <= 1:
                    raise
                batch = max(1, batch // 2)
                print(f"[embeddings] CUDA OOM, retrying with batch_size={batch}", file=sys.stderr)

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

    def embed_query(self, query: str) -> list[float]:
        # gte-Qwen2 ships a "query" prompt = "Instruct: <task>\nQuery: ".
        # We pass our own instruction explicitly to control the task description.
        prompted = f"Instruct: {self.cfg.query_instruction}\nQuery: {query}"
        vecs = self._encode([prompted], prompt_name=None)
        return vecs[0]
