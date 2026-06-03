"""Session usage accumulation.

A light take on claudewatcher: instead of parsing JSONL logs, we read the
`usage` + `total_cost_usd` the SDK already returns each turn and keep running
totals. The headline metric is the cache hit rate (read / total input).
"""

from __future__ import annotations

from dataclasses import dataclass


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


@dataclass
class UsageStats:
    turns: int = 0
    input_tokens: int = 0          # uncached (post-breakpoint) input
    output_tokens: int = 0
    cache_creation_tokens: int = 0  # cache writes
    cache_read_tokens: int = 0      # cache reads
    cost_usd: float = 0.0

    def add_turn(self, usage: dict | None, cost: float | None) -> None:
        self.turns += 1
        if usage:
            self.input_tokens += _int(usage.get("input_tokens"))
            self.output_tokens += _int(usage.get("output_tokens"))
            self.cache_creation_tokens += _int(usage.get("cache_creation_input_tokens"))
            self.cache_read_tokens += _int(usage.get("cache_read_input_tokens"))
        if cost:
            self.cost_usd += cost

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_read_tokens / self.total_input if self.total_input else 0.0
