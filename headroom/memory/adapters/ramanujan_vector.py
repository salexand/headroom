"""Ramanujan-expander LSH VectorIndex adapter.

Wraps the standalone RamanujanLSH as a full VectorIndex implementation
that plugs into the memory system alongside HNSW and sqlite-vec.

Trade-offs vs HNSW:
  + O(1) index time (hash, no graph maintenance)
  + Fixed memory per vector (no graph edges)
  + No native library dependency (pure Python + numpy)
  - Lower recall at same memory budget
  - No persistence (in-memory only for now)
"""

from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np

from headroom.memory.backends.ramanujan_lsh import RamanujanLSH
from headroom.memory.models import Memory
from headroom.memory.ports import VectorFilter, VectorSearchResult

logger = logging.getLogger(__name__)


@dataclass
class _IndexedMeta:
    """Metadata stored alongside vectors for post-filtering."""

    memory_id: str
    user_id: str
    session_id: str | None
    agent_id: str | None
    entity_refs: list[str]
    content: str
    created_at: datetime
    importance: float
    embedding: np.ndarray


class RamanujanVectorIndex:
    """VectorIndex implementation using Ramanujan-expander LSH.

    Usage::

        index = RamanujanVectorIndex(dimension=384, num_tables=16)
        await index.index(memory_with_embedding)
        results = await index.search(VectorFilter(
            query_vector=query_embedding,
            top_k=10,
        ))
    """

    def __init__(
        self,
        dimension: int = 384,
        num_tables: int = 16,
        hash_bits: int = 8,
        num_probes: int = 0,
        seed: int = 42,
    ) -> None:
        self._lsh = RamanujanLSH(
            dimension=dimension,
            num_tables=num_tables,
            hash_bits=hash_bits,
            seed=seed,
        )
        self._num_probes = num_probes
        self._metadata: dict[str, _IndexedMeta] = {}
        self._lock = threading.Lock()

    @property
    def dimension(self) -> int:
        return self._lsh.dimension

    @property
    def size(self) -> int:
        return self._lsh.size

    async def index(self, memory: Memory) -> None:
        if memory.embedding is None:
            raise ValueError(f"Memory {memory.id} has no embedding")

        embedding = np.asarray(memory.embedding, dtype=np.float32)
        if embedding.shape[0] != self._lsh.dimension:
            raise ValueError(
                f"Embedding dimension {embedding.shape[0]} does not match "
                f"index dimension {self._lsh.dimension}"
            )

        with self._lock:
            self._lsh.add(memory.id, embedding)
            self._metadata[memory.id] = _IndexedMeta(
                memory_id=memory.id,
                user_id=memory.user_id,
                session_id=memory.session_id,
                agent_id=memory.agent_id,
                entity_refs=list(memory.entity_refs),
                content=memory.content,
                created_at=memory.created_at,
                importance=memory.importance,
                embedding=embedding,
            )

    async def index_batch(self, memories: list[Memory]) -> int:
        count = 0
        for m in memories:
            if m.embedding is not None:
                await self.index(m)
                count += 1
        return count

    async def remove(self, memory_id: str) -> bool:
        with self._lock:
            ok = self._lsh.remove(memory_id)
            self._metadata.pop(memory_id, None)
            return ok

    async def remove_batch(self, memory_ids: list[str]) -> int:
        count = 0
        for mid in memory_ids:
            if await self.remove(mid):
                count += 1
        return count

    async def search(self, filter: VectorFilter) -> list[VectorSearchResult]:
        if filter.query_vector is None:
            if filter.query_text is not None:
                raise ValueError(
                    "query_text provided but RamanujanVectorIndex does not "
                    "embed text. Provide query_vector directly."
                )
            raise ValueError("Either query_vector or query_text must be provided")

        query = np.asarray(filter.query_vector, dtype=np.float32)

        with self._lock:
            if self._lsh.size == 0:
                return []

            # Get more candidates than needed to account for filtering
            raw_results = self._lsh.query(
                query, k=filter.top_k * 10, num_probes=self._num_probes,
            )

        results: list[VectorSearchResult] = []
        for r in raw_results:
            meta = self._metadata.get(r.memory_id)
            if meta is None:
                continue

            similarity = 1.0 - r.distance
            if similarity < filter.min_similarity:
                continue

            if not self._passes_filter(meta, filter):
                continue

            memory = Memory(
                id=meta.memory_id,
                content=meta.content,
                user_id=meta.user_id,
                session_id=meta.session_id,
                agent_id=meta.agent_id,
                entity_refs=meta.entity_refs,
                created_at=meta.created_at,
                importance=meta.importance,
                embedding=meta.embedding,
            )

            results.append(VectorSearchResult(
                memory=memory,
                similarity=float(similarity),
                rank=len(results) + 1,
            ))

            if len(results) >= filter.top_k:
                break

        return results

    async def update_embedding(self, memory_id: str, embedding: np.ndarray) -> bool:
        with self._lock:
            if memory_id not in self._metadata:
                return False
            self._lsh.remove(memory_id)
            self._lsh.add(memory_id, embedding)
            self._metadata[memory_id].embedding = embedding
            return True

    def _passes_filter(self, meta: _IndexedMeta, filter: VectorFilter) -> bool:
        if filter.user_id and meta.user_id != filter.user_id:
            return False
        if filter.session_id and meta.session_id != filter.session_id:
            return False
        if filter.agent_id and meta.agent_id != filter.agent_id:
            return False
        if filter.entity_refs:
            if not any(ref in meta.entity_refs for ref in filter.entity_refs):
                return False
        return True
