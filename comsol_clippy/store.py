"""ChromaDB persistent vectorstore wrapper."""
from __future__ import annotations

from pathlib import Path


class Store:
    def __init__(self, chroma_dir: Path, collection: str):
        import chromadb  # lazy: keeps pure-logic imports (and CI) free of chromadb

        chroma_dir.mkdir(parents=True, exist_ok=True)
        self.client = chromadb.PersistentClient(path=str(chroma_dir))
        self.collection_name = collection
        self._collection = None

    @property
    def collection(self):
        if self._collection is None:
            self._collection = self.client.get_or_create_collection(
                name=self.collection_name,
                metadata={"hnsw:space": "cosine"},
            )
        return self._collection

    def reset_collection(self) -> None:
        """Drop and recreate the collection from scratch.

        A Chroma collection's embedding dimension is fixed at creation, so a full
        rebuild after the embedding model changes (e.g. 1536-dim -> 2048-dim) must
        delete the old collection — otherwise upserts fail with "Collection expecting
        embedding with dimension of N". Deleting a missing collection is a no-op.
        """
        try:
            self.client.delete_collection(self.collection_name)
        except Exception:
            pass
        self._collection = None

    def exists(self) -> bool:
        try:
            self.client.get_collection(self.collection_name)
            return True
        except Exception:
            return False

    def count(self) -> int:
        return self.collection.count()

    def has_all(self, chunk_ids: list[str]) -> bool:
        if not chunk_ids:
            return False
        got = self.collection.get(ids=chunk_ids, include=[])
        return len(got.get("ids", [])) == len(chunk_ids)

    def upsert_chunks(self, chunks, vectors: list[list[float]]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[c.chunk_id for c in chunks],
            embeddings=vectors,
            documents=[c.text for c in chunks],
            metadatas=[c.metadata() for c in chunks],
        )

    def delete_by_source(self, source: str) -> None:
        self.collection.delete(where={"source": source})

    def query(self, vector: list[float], top_k: int) -> list[dict]:
        res = self.collection.query(
            query_embeddings=[vector],
            n_results=top_k,
            include=["documents", "metadatas", "distances"],
        )
        hits = []
        ids = res.get("ids", [[]])[0]
        docs = res.get("documents", [[]])[0]
        metas = res.get("metadatas", [[]])[0]
        dists = res.get("distances", [[]])[0]
        for i in range(len(ids)):
            hits.append(
                {
                    "id": ids[i],
                    "text": docs[i],
                    "metadata": metas[i],
                    "distance": dists[i],
                    # cosine distance -> similarity, clamped: cosine distance can exceed
                    # 1.0 for opposed vectors, which would otherwise yield a negative score.
                    "relevance": max(0.0, min(1.0, 1.0 - dists[i])),
                }
            )
        return hits
