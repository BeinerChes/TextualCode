"""Shared presentation-formatting helpers."""

from __future__ import annotations


def _short(n: int) -> str:
    """Compact token count: 1_703_00 -> '170.3k', 1_000_000 -> '1.0m'."""
    if n >= 1_000_000:
        return f"{n / 1_000_000:.1f}m"
    if n >= 1_000:
        return f"{n / 1_000:.1f}k"
    return str(n)
