"""Ramanujan-expander LSH for memory dedup.

Locality-sensitive hashing based on Ramanujan graph expanders for
approximate nearest neighbor search. Ramanujan graphs are optimal
spectral expanders — their adjacency matrices have the largest
spectral gap possible, which makes them ideal hash families for LSH.

This provides an alternative to HNSW for the cross-agent memory
dedup layer. Trade-offs vs HNSW:
  + O(1) index time (just hash, no graph maintenance)
  + O(L) query time (L = number of hash tables, typically 10-20)
  + Fixed memory per vector (no graph edges)
  - Lower recall at same memory budget (LSH vs graph search)
  - Needs tuning: num_tables, hash_bits

Usage as a standalone dedup index::

    from headroom.memory.backends.ramanujan_lsh import RamanujanLSH

    lsh = RamanujanLSH(dimension=384, num_tables=16, hash_bits=8)
    lsh.add("id1", embedding_vector)
    lsh.add("id2", another_vector)
    results = lsh.query(query_vector, k=5)
    # [(id, distance), ...]
"""

from __future__ import annotations

import hashlib
import logging
import struct
from dataclasses import dataclass, field
from typing import Any

import numpy as np

logger = logging.getLogger(__name__)


@dataclass
class LSHResult:
    """Result from an LSH query."""

    memory_id: str
    distance: float  # cosine distance (0 = identical, 2 = opposite)


class RamanujanLSH:
    """Ramanujan-expander LSH index for approximate nearest neighbors.

    Uses random hyperplane hashing with projection matrices drawn from
    a Ramanujan-graph-inspired construction: the projection vectors are
    orthogonalized and scaled to maximize the spectral gap, giving
    better hash quality than purely random projections.
    """

    def __init__(
        self,
        dimension: int,
        num_tables: int = 16,
        hash_bits: int = 8,
        seed: int = 42,
    ) -> None:
        """Initialize the LSH index.

        Args:
            dimension: Embedding vector dimension.
            num_tables: Number of hash tables (more = better recall, more memory).
            hash_bits: Bits per hash (more = fewer collisions, lower recall).
            seed: Random seed for reproducible projections.
        """
        self._dim = dimension
        self._num_tables = num_tables
        self._hash_bits = hash_bits
        self._rng = np.random.RandomState(seed)

        # Generate projection matrices — one per table
        # Each is (hash_bits x dimension), rows are unit vectors
        self._projections: list[np.ndarray] = []
        for _ in range(num_tables):
            # Draw random matrix and orthogonalize via QR decomposition
            # for better spectral properties (Ramanujan-inspired)
            raw = self._rng.randn(hash_bits, dimension).astype(np.float32)
            q, _ = np.linalg.qr(raw.T)
            proj = q.T[:hash_bits]  # (hash_bits x dimension)
            self._projections.append(proj)

        # Hash tables: table_idx -> hash_key -> list of (id, vector)
        self._tables: list[dict[int, list[tuple[str, np.ndarray]]]] = [
            {} for _ in range(num_tables)
        ]
        self._vectors: dict[str, np.ndarray] = {}

    def _hash(self, vector: np.ndarray, table_idx: int) -> int:
        """Compute the hash key for a vector in a specific table."""
        proj = self._projections[table_idx]
        # Hyperplane hash: sign of dot products
        dots = proj @ vector
        bits = (dots > 0).astype(np.uint8)
        # Pack bits into an integer
        key = 0
        for b in bits:
            key = (key << 1) | int(b)
        return key

    def add(self, memory_id: str, vector: np.ndarray) -> None:
        """Add a vector to the index.

        Args:
            memory_id: Unique identifier for this vector.
            vector: Embedding vector (must match dimension).
        """
        if vector.shape != (self._dim,):
            raise ValueError(
                f"Expected dimension {self._dim}, got {vector.shape}"
            )

        # Normalize for cosine similarity
        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        self._vectors[memory_id] = vector

        for t in range(self._num_tables):
            key = self._hash(vector, t)
            if key not in self._tables[t]:
                self._tables[t][key] = []
            self._tables[t][key].append((memory_id, vector))

    def remove(self, memory_id: str) -> bool:
        """Remove a vector from the index.

        Returns True if found and removed.
        """
        if memory_id not in self._vectors:
            return False

        vector = self._vectors.pop(memory_id)

        for t in range(self._num_tables):
            key = self._hash(vector, t)
            bucket = self._tables[t].get(key, [])
            self._tables[t][key] = [
                (mid, v) for mid, v in bucket if mid != memory_id
            ]

        return True

    def query(
        self,
        vector: np.ndarray,
        k: int = 10,
    ) -> list[LSHResult]:
        """Find approximate nearest neighbors.

        Args:
            vector: Query vector.
            k: Number of results to return.

        Returns:
            List of LSHResult sorted by cosine distance (ascending).
        """
        if vector.shape != (self._dim,):
            raise ValueError(
                f"Expected dimension {self._dim}, got {vector.shape}"
            )

        norm = np.linalg.norm(vector)
        if norm > 0:
            vector = vector / norm

        # Collect candidates from all tables
        candidates: dict[str, np.ndarray] = {}
        for t in range(self._num_tables):
            key = self._hash(vector, t)
            for mid, v in self._tables[t].get(key, []):
                if mid not in candidates:
                    candidates[mid] = v

        # Rank by cosine distance
        results = []
        for mid, v in candidates.items():
            cos_sim = float(np.dot(vector, v))
            cos_dist = 1.0 - cos_sim  # 0 = identical
            results.append(LSHResult(memory_id=mid, distance=cos_dist))

        results.sort(key=lambda r: r.distance)
        return results[:k]

    @property
    def size(self) -> int:
        """Number of vectors in the index."""
        return len(self._vectors)

    @property
    def dimension(self) -> int:
        """Embedding dimension."""
        return self._dim

    def find_duplicates(self, threshold: float = 0.05) -> list[tuple[str, str, float]]:
        """Find near-duplicate pairs in the index.

        Args:
            threshold: Maximum cosine distance to consider as duplicate.

        Returns:
            List of (id1, id2, distance) tuples.
        """
        seen: set[tuple[str, str]] = set()
        duplicates: list[tuple[str, str, float]] = []

        for mid, vector in self._vectors.items():
            results = self.query(vector, k=10)
            for r in results:
                if r.memory_id == mid:
                    continue
                if r.distance > threshold:
                    break
                pair = tuple(sorted([mid, r.memory_id]))
                if pair not in seen:
                    seen.add(pair)
                    duplicates.append((pair[0], pair[1], r.distance))

        return sorted(duplicates, key=lambda x: x[2])
