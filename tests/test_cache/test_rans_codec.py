"""Tests for rANS entropy coder."""

from __future__ import annotations

import random

import pytest

from headroom.cache.rans_codec import (
    compress_text,
    decompress_text,
    rans_decode,
    rans_encode,
)


class TestRansRoundTrip:
    def test_empty(self) -> None:
        encoded = rans_encode(b"")
        decoded = rans_decode(encoded)
        assert decoded == b""

    def test_single_byte(self) -> None:
        encoded = rans_encode(b"A")
        decoded = rans_decode(encoded)
        assert decoded == b"A"

    def test_repeated_byte(self) -> None:
        data = b"AAAAAAAAAA"
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data

    def test_ascii_text(self) -> None:
        data = b"Hello, World! This is a test of the rANS entropy coder."
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data

    def test_json_data(self) -> None:
        data = b'{"results":[{"id":1,"value":42},{"id":2,"value":99}]}'
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data

    def test_all_byte_values(self) -> None:
        data = bytes(range(256)) * 4
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data

    def test_large_data(self) -> None:
        rng = random.Random(42)
        data = bytes(rng.randint(0, 255) for _ in range(10_000))
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data

    def test_realistic_tool_output(self) -> None:
        import json

        obj = {
            "results": [
                {"id": i, "ts": 1718200000 + 7 * i, "level": "INFO", "msg": "ok"}
                for i in range(100)
            ]
        }
        data = json.dumps(obj).encode("utf-8")
        encoded = rans_encode(data)
        decoded = rans_decode(encoded)
        assert decoded == data


class TestCompression:
    def test_compresses_repeated_data(self) -> None:
        data = b"A" * 1000
        encoded = rans_encode(data)
        # Highly repetitive data should compress well
        assert len(encoded) < len(data)

    def test_compresses_json(self) -> None:
        import json

        obj = {"results": [{"id": i, "val": i * 10} for i in range(200)]}
        data = json.dumps(obj, separators=(",", ":")).encode("utf-8")
        encoded = rans_encode(data)
        ratio = len(encoded) / len(data)
        # JSON has redundant structure -> should compress
        assert ratio < 0.95, f"Compression ratio {ratio:.2f} too high"

    def test_random_data_minimal_expansion(self) -> None:
        rng = random.Random(42)
        data = bytes(rng.randint(0, 255) for _ in range(1000))
        encoded = rans_encode(data)
        # Random data can't compress, but shouldn't expand much
        # (overhead is header: 4 + 512 = 516 bytes)
        assert len(encoded) < len(data) + 600


class TestTextWrappers:
    def test_compress_decompress_text(self) -> None:
        text = "Hello, world! This is a test."
        encoded = compress_text(text)
        decoded = decompress_text(encoded)
        assert decoded == text

    def test_unicode_text(self) -> None:
        text = "Unicode: cafe\u0301 \u2603 \u2764"
        encoded = compress_text(text)
        decoded = decompress_text(encoded)
        assert decoded == text


class TestErrors:
    def test_decode_too_short(self) -> None:
        with pytest.raises(ValueError, match="too short"):
            rans_decode(b"\x00")

    def test_decode_missing_freq_table(self) -> None:
        # Valid length header but no freq table
        with pytest.raises(ValueError, match="frequency table"):
            rans_decode(b"\x05\x00\x00\x00" + b"\x00" * 10)
