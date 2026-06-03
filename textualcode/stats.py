"""Session usage accumulation.

A light take on claudewatcher: instead of parsing JSONL logs, we read the
`usage` + `total_cost_usd` the SDK already returns each turn and keep running
totals. The headline metric is the cache hit rate (read / total input).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

# The CLI tags model_usage keys with the context-window tier, e.g.
# "claude-opus-4-8[1m]", while AssistantMessage.model reports the bare id
# "claude-opus-4-8". Strip a trailing "[...]" so the two can be compared.
_MODEL_TAG_RE = re.compile(r"\[[^\]]*\]\s*$")


def _base_model(model_id: str | None) -> str:
    if not model_id:
        return ""
    return _MODEL_TAG_RE.sub("", model_id).strip()


def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _float(value) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


@dataclass
class UsageStats:
    turns: int = 0
    input_tokens: int = 0          # uncached (post-breakpoint) input
    output_tokens: int = 0
    cache_creation_tokens: int = 0  # cache writes
    cache_read_tokens: int = 0      # cache reads
    cost_usd: float = 0.0           # authoritative total (incl. subagents)
    subagent_cost_usd: float = 0.0  # portion spent by Task subagents
    subagent_tokens: int = 0        # total tokens consumed by subagents

    def add_turn(
        self,
        usage: dict | None,
        cost: float | None,
        model_usage: dict | None = None,
        main_models: "set[str] | list[str] | None" = None,
        subagent_tokens: int = 0,
    ) -> None:
        """Accumulate one query() turn and split its cost main vs. subagents.

        The SDK exposes no per-subagent cost (only per-model `model_usage` and
        the authoritative `total_cost_usd`; the feature request for granular
        per-subagent tracking, claude-code#22625, was closed as not planned).
        So we attribute by combining two signals we *do* have:

        - `main_models`: base model ids seen on the MAIN stream (assistant
          messages with parent_tool_use_id=None). Subagent assistant messages
          never reach this stream, so every model here is a main-agent model.
        - `subagent_tokens`: Σ total_tokens from this turn's Task notifications —
          the only first-class subagent signal (no cost, just a token count).

        Cost split:
        - A model in `model_usage` that the main agent never used is wholly a
          subagent's (the common case: e.g. Haiku subagents under an Opus main).
          Its real per-model costUSD is exact.
        - Subagent tokens left over after accounting for those subagent-only
          models must belong to a model the main agent ALSO used (e.g. an Opus
          subagent under an Opus main). We carve that model's cost out
          proportionally by token share — exact *within* a model, since the
          per-token rate there is uniform.

        We only attribute subagent cost when a subagent actually ran this turn
        (`subagent_tokens > 0`) AND the main model is known. Otherwise an extra
        model in `model_usage` can't masquerade as a subagent — the bug where
        no-subagent turns still showed subagent spend (main $0.00).
        """
        self.turns += 1
        if usage:
            self.input_tokens += _int(usage.get("input_tokens"))
            self.output_tokens += _int(usage.get("output_tokens"))
            self.cache_creation_tokens += _int(usage.get("cache_creation_input_tokens"))
            self.cache_read_tokens += _int(usage.get("cache_read_input_tokens"))
        if cost:
            self.cost_usd += cost

        sub_tokens = _int(subagent_tokens)
        self.subagent_tokens += sub_tokens

        main_bases = {_base_model(m) for m in (main_models or []) if m}
        if not (model_usage and sub_tokens > 0 and main_bases):
            return

        sub_only_cost = 0.0
        sub_only_tokens = 0
        shared: list[tuple[float, int]] = []  # (costUSD, tokens) for main models
        for model_id, mu in model_usage.items():
            if not isinstance(mu, dict):
                continue
            base = _base_model(model_id)
            model_cost = _float(mu.get("costUSD"))
            model_tokens = (
                _int(mu.get("inputTokens"))
                + _int(mu.get("outputTokens"))
                + _int(mu.get("cacheCreationInputTokens"))
                + _int(mu.get("cacheReadInputTokens"))
            )
            if base and base in main_bases:
                shared.append((model_cost, model_tokens))
            else:
                sub_only_cost += model_cost
                sub_only_tokens += model_tokens

        turn_sub_cost = sub_only_cost
        # Subagent tokens not explained by subagent-only models came from a
        # model the main agent also used → carve out proportionally.
        remaining = sub_tokens - sub_only_tokens
        if remaining > 0:
            total_shared = sum(t for _, t in shared)
            if total_shared > 0:
                for model_cost, model_tokens in shared:
                    if model_tokens <= 0:
                        continue
                    carved = min(remaining * (model_tokens / total_shared), model_tokens)
                    turn_sub_cost += model_cost * (carved / model_tokens)

        # Subagents can never cost more than the turn's authoritative total.
        if cost:
            turn_sub_cost = min(turn_sub_cost, _float(cost))
        self.subagent_cost_usd += turn_sub_cost

    def merged_with(self, live: dict | None) -> "UsageStats":
        """Return a display-only copy with an in-flight turn's token usage added.

        ``live`` is a partial usage dict (Anthropic ``usage`` block keys) summed
        from the current turn's streamed assistant steps. Used to show tokens /
        cache hit rate updating in real time *before* the authoritative
        ``ResultMessage`` arrives. turns and cost are left untouched (no
        per-step cost is available); they update on commit. Returns ``self``
        unchanged when there is nothing live to overlay.
        """
        if not live:
            return self
        return replace(
            self,
            input_tokens=self.input_tokens + _int(live.get("input_tokens")),
            output_tokens=self.output_tokens + _int(live.get("output_tokens")),
            cache_creation_tokens=self.cache_creation_tokens
            + _int(live.get("cache_creation_input_tokens")),
            cache_read_tokens=self.cache_read_tokens
            + _int(live.get("cache_read_input_tokens")),
        )

    @property
    def main_cost_usd(self) -> float:
        """Main-agent spend = authoritative total minus the subagent portion.

        Derived (rather than summed independently) so main + subagents always
        reconciles to the displayed total.
        """
        return self.cost_usd - self.subagent_cost_usd

    @property
    def total_input(self) -> int:
        return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens

    @property
    def cache_hit_rate(self) -> float:
        return self.cache_read_tokens / self.total_input if self.total_input else 0.0
