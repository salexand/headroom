"""
Headroom Savings Monitor — live dashboard for compression savings.

Shows real-time token savings, cost reduction, and compression stats
from the running Headroom proxy. Auto-refreshes every 5 seconds.

Usage:
    python headroom-savings.py              # default, polls localhost:8787
    python headroom-savings.py --once       # print once and exit
    python headroom-savings.py --port 9000  # custom proxy port
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.request
import urllib.error


def fetch_stats(port: int) -> dict | None:
    try:
        url = f"http://127.0.0.1:{port}/stats"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fetch_history(port: int) -> dict | None:
    try:
        url = f"http://127.0.0.1:{port}/stats-history"
        with urllib.request.urlopen(url, timeout=3) as resp:
            return json.loads(resp.read())
    except Exception:
        return None


def fmt_tokens(n: int | float) -> str:
    return f"{int(n):,}"


def fmt_usd(n: float) -> str:
    if n < 0.01:
        return f"${n:.4f}"
    return f"${n:.2f}"


def fmt_pct(n: float) -> str:
    return f"{n:.1f}%"


def clear_screen() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def render(stats: dict, history: dict | None) -> str:
    lines: list[str] = []

    comp = stats.get("summary", {}).get("compression", {})
    cost = stats.get("summary", {}).get("cost", {})
    session = history.get("display_session", {}) if history else {}
    lifetime = history.get("lifetime", {}) if history else {}

    requests = stats.get("summary", {}).get("api_requests", 0)
    compressed = comp.get("requests_compressed", 0)
    tokens_compressed = comp.get("total_tokens_removed", 0)
    rtk_tokens = comp.get("rtk_tokens_avoided", 0) or comp.get("cli_filtering_tokens_avoided", 0)
    avg_pct = comp.get("avg_compression_pct", 0)
    best_pct = comp.get("best_compression_pct", 0)
    best_detail = comp.get("best_detail", "")

    saved_usd = cost.get("total_saved_usd", 0)
    without_usd = cost.get("without_headroom_usd", 0)
    with_usd = cost.get("with_headroom_usd", 0)

    lines.append("")
    lines.append("  +===================================================+")
    lines.append("  |          HEADROOM SAVINGS MONITOR                  |")
    lines.append("  +===================================================+")
    lines.append("")

    # Session stats
    lines.append("  THIS SESSION")
    lines.append(f"  ---------------------------------------------")
    lines.append(f"  Requests:          {requests}")
    lines.append(f"  Compressed:        {compressed}")
    if tokens_compressed > 0:
        lines.append(f"  Tokens saved (compression): {fmt_tokens(tokens_compressed)}")
    if rtk_tokens > 0:
        lines.append(f"  Tokens saved (RTK filter):  {fmt_tokens(rtk_tokens)}")
    total_saved = tokens_compressed + rtk_tokens
    if total_saved > 0:
        lines.append(f"  Tokens saved (total):       {fmt_tokens(total_saved)}")
    else:
        lines.append(f"  Tokens saved:      0 (no tool outputs compressed yet)")
    if avg_pct > 0:
        lines.append(f"  Avg compression:   {fmt_pct(avg_pct)}")
    if best_pct > 0:
        lines.append(f"  Best compression:  {fmt_pct(best_pct)}")
        if best_detail:
            lines.append(f"                     ({best_detail})")
    lines.append("")

    # Cost
    lines.append("  COST")
    lines.append(f"  ---------------------------------------------")
    lines.append(f"  Without Headroom:  {fmt_usd(without_usd)}")
    lines.append(f"  With Headroom:     {fmt_usd(with_usd)}")
    lines.append(f"  Saved:             {fmt_usd(saved_usd)}")
    if without_usd > 0:
        lines.append(f"  Savings:           {fmt_pct(100 * saved_usd / without_usd)}")
    lines.append("")

    # Lifetime (from history)
    if lifetime:
        lt_saved = lifetime.get("tokens_saved", 0)
        lt_cost = lifetime.get("compression_savings_usd", 0)
        lt_reqs = lifetime.get("requests", 0)
        lines.append("  LIFETIME (all sessions)")
        lines.append(f"  ---------------------------------------------")
        lines.append(f"  Total requests:    {lt_reqs}")
        lines.append(f"  Total tokens saved:{fmt_tokens(lt_saved)}")
        lines.append(f"  Total cost saved:  {fmt_usd(lt_cost)}")
        lines.append("")

    # Compression breakdown
    uncomp = stats.get("summary", {}).get("uncompressed_requests", {})
    if uncomp:
        lines.append("  UNCOMPRESSED (why some requests weren't compressed)")
        lines.append(f"  ---------------------------------------------")
        for reason, count in uncomp.items():
            lines.append(f"  {reason}: {count}")
        lines.append("")

    # Footer
    model = stats.get("summary", {}).get("primary_model", "unknown")
    lines.append(f"  Model: {model}")
    lines.append(f"  Refreshing every 5s... (Ctrl+C to stop)")
    lines.append("")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Headroom Savings Monitor")
    parser.add_argument("--port", type=int, default=8787, help="Proxy port")
    parser.add_argument("--once", action="store_true", help="Print once and exit")
    parser.add_argument("--interval", type=int, default=5, help="Refresh interval (seconds)")
    args = parser.parse_args()

    if args.once:
        stats = fetch_stats(args.port)
        if not stats:
            print(f"  Cannot connect to Headroom proxy on port {args.port}")
            print(f"  Start it first: headroom proxy --port {args.port}")
            sys.exit(1)
        history = fetch_history(args.port)
        print(render(stats, history))
        return

    print(f"  Connecting to Headroom proxy on port {args.port}...")

    try:
        while True:
            stats = fetch_stats(args.port)
            if stats:
                history = fetch_history(args.port)
                clear_screen()
                print(render(stats, history))
            else:
                clear_screen()
                print(f"\n  Waiting for Headroom proxy on port {args.port}...")
                print(f"  Start it: headroom proxy --port {args.port}")
            time.sleep(args.interval)
    except KeyboardInterrupt:
        print("\n  Monitor stopped.")


if __name__ == "__main__":
    main()
