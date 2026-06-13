"""Tests for Ramanujan-expander LSH index."""

from __future__ import annotations

import numpy as np
import pytest

from headroom.memory.backends.ramanujan_lsh import LSHResult, RamanujanLSH


@pytest.fixture()
def lsh() -> RamanujanLSH:
    return RamanujanLSH(dimension=32, num_tables=8, hash_bits=6, seed=42)


class TestRamanujanLSH:
    def test_add_and_query_exact(self, lsh: RamanujanLSH) -> None:
        vec = np.random.RandomState(1).randn(32).astype(np.float32)
        lsh.add("a", vec)
        results = lsh.query(vec, k=1)
        assert len(results) >= 1
        assert results[0].memory_id == "a"
        assert results[0].distance < 0.01  # near-zero for exact match

    def test_add_multiple_find_nearest(self, lsh: RamanujanLSH) -> None:
        rng = np.random.RandomState(42)
        base = rng.randn(32).astype(np.float32)
        # Add a similar vector and a dissimilar one
        similar = base + rng.randn(32).astype(np.float32) * 0.1
        dissimilar = -base  # opposite direction

        lsh.add("base", base)
        lsh.add("similar", similar)
        lsh.add("dissimilar", dissimilar)

        results = lsh.query(base, k=3)
        # Base should be closest to itself, then similar
        ids = [r.memory_id for r in results]
        assert ids[0] == "base"
        if "similar" in ids and "dissimilar" in ids:
            sim_idx = ids.index("similar")
            dis_idx = ids.index("dissimilar")
            assert sim_idx < dis_idx

    def test_remove(self, lsh: RamanujanLSH) -> None:
        vec = np.random.RandomState(1).randn(32).astype(np.float32)
        lsh.add("a", vec)
        assert lsh.size == 1
        assert lsh.remove("a")
        assert lsh.size == 0
        assert not lsh.remove("a")  # already removed

    def test_remove_not_found(self, lsh: RamanujanLSH) -> None:
        assert not lsh.remove("nonexistent")

    def test_size_and_dimension(self, lsh: RamanujanLSH) -> None:
        assert lsh.size == 0
        assert lsh.dimension == 32
        lsh.add("a", np.zeros(32, dtype=np.float32))
        assert lsh.size == 1

    def test_wrong_dimension_raises(self, lsh: RamanujanLSH) -> None:
        with pytest.raises(ValueError, match="dimension"):
            lsh.add("a", np.zeros(64, dtype=np.float32))

    def test_query_wrong_dimension_raises(self, lsh: RamanujanLSH) -> None:
        with pytest.raises(ValueError, match="dimension"):
            lsh.query(np.zeros(64, dtype=np.float32))

    def test_empty_query(self, lsh: RamanujanLSH) -> None:
        results = lsh.query(np.zeros(32, dtype=np.float32))
        assert results == []

    def test_find_duplicates(self, lsh: RamanujanLSH) -> None:
        rng = np.random.RandomState(42)
        vec1 = rng.randn(32).astype(np.float32)
        vec2 = vec1 + rng.randn(32).astype(np.float32) * 0.01  # near-duplicate
        vec3 = rng.randn(32).astype(np.float32)  # different

        lsh.add("a", vec1)
        lsh.add("b", vec2)
        lsh.add("c", vec3)

        dupes = lsh.find_duplicates(threshold=0.05)
        # a and b should be duplicates
        dupe_pairs = {(d[0], d[1]) for d in dupes}
        assert ("a", "b") in dupe_pairs or ("b", "a") in dupe_pairs

    def test_many_vectors_recall(self) -> None:
        """With enough tables, LSH should find near neighbors reliably."""
        dim = 64
        lsh = RamanujanLSH(dimension=dim, num_tables=20, hash_bits=8, seed=42)
        rng = np.random.RandomState(42)

        # Add 100 random vectors
        vectors = {}
        for i in range(100):
            v = rng.randn(dim).astype(np.float32)
            lsh.add(f"v{i}", v)
            vectors[f"v{i}"] = v / np.linalg.norm(v)

        # Query with one of them — it should find itself
        query = vectors["v50"]
        results = lsh.query(query, k=5)
        found_ids = {r.memory_id for r in results}
        assert "v50" in found_ids
