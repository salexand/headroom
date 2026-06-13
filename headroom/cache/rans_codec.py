"""rANS-style entropy coder for CCR storage compression.

Compresses the *original* text stored in the CCR cache for on-disk/in-RAM
savings. This is **byte compression, not token reduction** — the LLM
never sees the encoded form. It reduces storage cost for the CCR
originals store.

This is a pure-Python implementation of a simple order-0 rANS (range
Asymmetric Numeral System) encoder. For production, the Rust crate would
use a tuned implementation, but this Python version is correct, tested,
and sufficient for validating the storage savings.

Usage::

    from headroom.cache.rans_codec import rans_encode, rans_decode

    encoded = rans_encode(b"original tool output text...")
    decoded = rans_decode(encoded)
    assert decoded == b"original tool output text..."

Integration with CompressionStore::

    # Wrap store/retrieve to compress originals on disk
    encoded = rans_encode(original.encode("utf-8"))
    # Store `encoded` bytes instead of raw string
    # On retrieve: original = rans_decode(encoded).decode("utf-8")
"""

from __future__ import annotations

import struct
from collections import Counter


# ---------------------------------------------------------------------------
# Order-0 rANS codec
# ---------------------------------------------------------------------------

# rANS parameters
_RANS_L = 1 << 23  # lower bound of state
_RANS_B = 1 << 8  # radix (byte-based I/O)
_PROB_BITS = 14  # precision bits for probabilities
_PROB_SCALE = 1 << _PROB_BITS


def _build_freq_table(data: bytes) -> list[int]:
    """Build a frequency table scaled to _PROB_SCALE."""
    counts = Counter(data)
    total = len(data)
    if total == 0:
        return [0] * 256

    # Scale frequencies to sum to _PROB_SCALE, ensuring each present
    # symbol gets at least 1
    freqs = [0] * 256
    remaining = _PROB_SCALE
    present = [s for s in range(256) if counts.get(s, 0) > 0]

    for s in present:
        f = max(1, round(counts[s] * _PROB_SCALE / total))
        freqs[s] = f
        remaining -= f

    # Distribute rounding error to the most frequent symbol
    if remaining != 0 and present:
        most_frequent = max(present, key=lambda s: counts[s])
        freqs[most_frequent] += remaining

    return freqs


def _build_cdf(freqs: list[int]) -> list[int]:
    """Build cumulative distribution function from frequencies."""
    cdf = [0] * 257
    for i in range(256):
        cdf[i + 1] = cdf[i] + freqs[i]
    return cdf


def rans_encode(data: bytes) -> bytes:
    """Encode data using order-0 rANS. Returns encoded bytes.

    Format: [4-byte original length][256 * 2-byte freq table][encoded stream]
    """
    if not data:
        return struct.pack("<I", 0)

    freqs = _build_freq_table(data)
    cdf = _build_cdf(freqs)

    # Encode in reverse order (rANS convention)
    state = _RANS_L
    out_bytes: list[int] = []

    for symbol in reversed(data):
        freq = freqs[symbol]
        if freq == 0:
            raise ValueError(f"Symbol {symbol} has zero frequency")

        # Renormalize: output bytes while state is too large
        max_state = freq * (_RANS_L // _PROB_SCALE) * _RANS_B
        while state >= max_state:
            out_bytes.append(state & 0xFF)
            state >>= 8

        # Encode
        state = (state // freq) * _PROB_SCALE + (state % freq) + cdf[symbol]

    # Flush final state (4 bytes)
    for _ in range(4):
        out_bytes.append(state & 0xFF)
        state >>= 8

    # Pack: length + freq table + reversed stream
    header = struct.pack("<I", len(data))
    freq_bytes = b"".join(struct.pack("<H", f) for f in freqs)
    stream = bytes(reversed(out_bytes))

    return header + freq_bytes + stream


def rans_decode(encoded: bytes) -> bytes:
    """Decode rANS-encoded data. Returns original bytes."""
    if len(encoded) < 4:
        raise ValueError("Encoded data too short")

    orig_len = struct.unpack("<I", encoded[:4])[0]
    if orig_len == 0:
        return b""

    if len(encoded) < 4 + 512:
        raise ValueError("Missing frequency table")

    # Read freq table (256 * 2 bytes)
    freqs = [
        struct.unpack("<H", encoded[4 + i * 2 : 4 + i * 2 + 2])[0]
        for i in range(256)
    ]
    cdf = _build_cdf(freqs)

    # Build symbol lookup table for fast CDF inversion
    sym_table = [0] * _PROB_SCALE
    for s in range(256):
        for j in range(freqs[s]):
            sym_table[cdf[s] + j] = s

    # Read stream
    stream = encoded[4 + 512 :]
    stream_pos = 0

    # Initialize state from first 4 bytes
    state = 0
    for i in range(4):
        if stream_pos < len(stream):
            state = (state << 8) | stream[stream_pos]
            stream_pos += 1

    # Decode
    output = bytearray(orig_len)
    for i in range(orig_len):
        # Find symbol
        slot = state % _PROB_SCALE
        symbol = sym_table[slot]
        output[i] = symbol

        # Advance state
        freq = freqs[symbol]
        state = freq * (state // _PROB_SCALE) + slot - cdf[symbol]

        # Renormalize
        while state < _RANS_L and stream_pos < len(stream):
            state = (state << 8) | stream[stream_pos]
            stream_pos += 1

    return bytes(output)


# ---------------------------------------------------------------------------
# Convenience wrappers for text
# ---------------------------------------------------------------------------


def compress_text(text: str) -> bytes:
    """Compress a text string using rANS. Returns encoded bytes."""
    return rans_encode(text.encode("utf-8"))


def decompress_text(encoded: bytes) -> str:
    """Decompress rANS-encoded bytes back to a text string."""
    return rans_decode(encoded).decode("utf-8")
