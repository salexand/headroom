"""Tests for RamanujanVectorIndex — VectorIndex protocol adapter."""

from __future__ import annotations

import asyncio

import numpy as np
import pytest

from headroom.memory.adapters.ramanujan_vector import RamanujanVectorIndex
from headroom.memory.models import Memory
from headroom.memory.ports import VectorFilter


def _run(coro):
    """Run an async function synchronously."""
    return asyncio.get_event_loop().run_until_complete(coro)


@pytest.fixture()
def index() -> RamanujanVectorIndex:
    return RamanujanVectorIndex(dimension=32, num_tables=12, hash_bits=6)


def _make_memory(mid: str, embedding: np.ndarray, user_id: str = "u1") -> Memory:
    return Memory(id=mid, content=f"content-{mid}", user_id=user_id, embedding=embedding)


class TestRamanujanVectorIndex:
    def test_index_and_search(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        vec = rng.randn(32).astype(np.float32)
        mem = _make_memory("m1", vec)
        _run(index.index(mem))

        assert index.size == 1

        results = _run(index.search(VectorFilter(query_vector=vec, top_k=1)))
        assert len(results) >= 1
        assert results[0].memory.id == "m1"
        assert results[0].similarity > 0.99

    def test_search_nearest(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        base = rng.randn(32).astype(np.float32)
        similar = base + rng.randn(32).astype(np.float32) * 0.05
        different = rng.randn(32).astype(np.float32)

        _run(index.index(_make_memory("base", base)))
        _run(index.index(_make_memory("similar", similar)))
        _run(index.index(_make_memory("different", different)))

        results = _run(index.search(VectorFilter(query_vector=base, top_k=3)))
        assert results[0].memory.id == "base"

    def test_remove(self, index: RamanujanVectorIndex) -> None:
        vec = np.random.RandomState(1).randn(32).astype(np.float32)
        _run(index.index(_make_memory("m1", vec)))
        assert index.size == 1

        assert _run(index.remove("m1"))
        assert index.size == 0
        assert not _run(index.remove("m1"))

    def test_index_batch(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        memories = [_make_memory(f"m{i}", rng.randn(32).astype(np.float32)) for i in range(10)]
        count = _run(index.index_batch(memories))
        assert count == 10
        assert index.size == 10

    def test_remove_batch(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        for i in range(5):
            _run(index.index(_make_memory(f"m{i}", rng.randn(32).astype(np.float32))))
        removed = _run(index.remove_batch(["m0", "m1", "m99"]))
        assert removed == 2
        assert index.size == 3

    def test_filter_by_user_id(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        vec = rng.randn(32).astype(np.float32)
        _run(index.index(_make_memory("m1", vec, user_id="alice")))
        _run(index.index(_make_memory("m2", vec + 0.01, user_id="bob")))

        results = _run(index.search(VectorFilter(
            query_vector=vec, top_k=10, user_id="alice",
        )))
        assert all(r.memory.user_id == "alice" for r in results)

    def test_min_similarity_filter(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        vec = rng.randn(32).astype(np.float32)
        _run(index.index(_make_memory("m1", vec)))
        _run(index.index(_make_memory("m2", -vec)))  # opposite

        results = _run(index.search(VectorFilter(
            query_vector=vec, top_k=10, min_similarity=0.5,
        )))
        for r in results:
            assert r.similarity >= 0.5

    def test_update_embedding(self, index: RamanujanVectorIndex) -> None:
        rng = np.random.RandomState(42)
        old = rng.randn(32).astype(np.float32)
        new = rng.randn(32).astype(np.float32)
        _run(index.index(_make_memory("m1", old)))

        assert _run(index.update_embedding("m1", new))
        results = _run(index.search(VectorFilter(query_vector=new, top_k=1)))
        assert results[0].memory.id == "m1"
        assert results[0].similarity > 0.99

    def test_no_embedding_raises(self, index: RamanujanVectorIndex) -> None:
        mem = Memory(id="bad", content="no embedding", user_id="u1")
        with pytest.raises(ValueError, match="no embedding"):
            _run(index.index(mem))

    def test_dimension_property(self, index: RamanujanVectorIndex) -> None:
        assert index.dimension == 32

    def test_empty_search(self, index: RamanujanVectorIndex) -> None:
        results = _run(index.search(VectorFilter(
            query_vector=np.zeros(32, dtype=np.float32), top_k=5,
        )))
        assert results == []
