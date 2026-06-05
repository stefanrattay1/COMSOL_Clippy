"""Tests for Embedder's bounded LRU query-embedding cache.

Pure logic only: we build an Embedder via __new__ (bypassing the real model load,
the same trick tests/test_daemon.py uses for _Daemon) and stub out _encode, so no
torch / sentence-transformers / model download is involved. These run in the light
suite under a bare `pytest`.
"""
from __future__ import annotations

import threading
from collections import OrderedDict

from comsol_clippy.config import EmbeddingConfig
from comsol_clippy.embeddings import Embedder


def _make_embedder(cache_size: int = 256, instruction_format: str = "none") -> Embedder:
    """An Embedder with a stubbed _encode and a call counter — no model loads."""
    emb = Embedder.__new__(Embedder)
    emb.cfg = EmbeddingConfig(
        model="stub",
        dim=4,
        max_seq_tokens=128,
        batch_size=4,
        query_instruction="find relevant passages",
        instruction_format=instruction_format,
        cache_size=cache_size,
    )
    emb._qcache = OrderedDict()
    emb._qcache_lock = threading.Lock()
    emb._qcache_max = cache_size
    emb.encode_calls = 0

    emb.last_prompt_name = None
    emb.last_prompt = None

    def fake_encode(texts, *, prompt_name=None, prompt=None):
        emb.encode_calls += 1
        emb.last_prompt_name = prompt_name
        emb.last_prompt = prompt
        # Deterministic, query-dependent vector so distinct queries differ.
        return [[float(len(t)), float(sum(map(ord, t)) % 97), 0.0, 1.0] for t in texts]

    emb._encode = fake_encode  # type: ignore[method-assign]
    return emb


def test_repeat_query_hits_cache():
    emb = _make_embedder()
    v1 = emb.embed_query("conjugate heat transfer")
    v2 = emb.embed_query("conjugate heat transfer")
    assert v1 == v2
    assert emb.encode_calls == 1  # second call served from cache


def test_distinct_queries_recompute():
    emb = _make_embedder()
    a = emb.embed_query("heat transfer")
    b = emb.embed_query("laminar flow")
    assert emb.encode_calls == 2
    assert a != b


def test_lru_eviction_at_max():
    emb = _make_embedder(cache_size=2)
    emb.embed_query("one")
    emb.embed_query("two")
    emb.embed_query("three")  # evicts the least-recently-used ("one")
    assert set(emb._qcache) == {"two", "three"}
    assert emb.encode_calls == 3
    emb.embed_query("one")  # evicted -> recomputed
    assert emb.encode_calls == 4


def test_access_refreshes_recency():
    emb = _make_embedder(cache_size=2)
    emb.embed_query("one")
    emb.embed_query("two")
    emb.embed_query("one")  # touch "one" so "two" is now the LRU
    emb.embed_query("three")  # should evict "two", not "one"
    assert set(emb._qcache) == {"one", "three"}


def test_cache_size_zero_disables():
    emb = _make_embedder(cache_size=0)
    emb.embed_query("same")
    emb.embed_query("same")
    assert emb.encode_calls == 2  # never cached
    assert len(emb._qcache) == 0


def test_st_prompt_query_mode_uses_prompt_argument():
    emb = _make_embedder(instruction_format="st-prompt")
    emb.embed_query("same")
    assert emb.last_prompt == emb.cfg.query_instruction
    assert emb.last_prompt_name is None


def test_returned_vector_is_a_copy():
    emb = _make_embedder()
    v = emb.embed_query("mutate me")
    v[0] = 999.0  # caller mutation must not corrupt the cached vector
    again = emb.embed_query("mutate me")
    assert again[0] != 999.0
    assert emb.encode_calls == 1


def test_concurrent_access_is_safe():
    emb = _make_embedder(cache_size=8)
    queries = [f"q{i % 12}" for i in range(200)]
    errors: list[Exception] = []

    def worker(items):
        try:
            for q in items:
                emb.embed_query(q)
        except Exception as e:  # pragma: no cover - surfaced via assert below
            errors.append(e)

    threads = [
        threading.Thread(target=worker, args=(queries[i::4],)) for i in range(4)
    ]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert not errors
    assert len(emb._qcache) <= emb._qcache_max
