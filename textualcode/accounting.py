"""TurnAccountant: owns UsageStats and the per-turn subagent-token counter.

Co-locates the counter reset with the consume so a stray second ResultMessage
for the same turn cannot double-bill (confirmed bug #2 fix).
"""

from __future__ import annotations

from .stats import UsageStats


class TurnAccountant:
    """Owns the session UsageStats and the per-turn subagent-token accumulator.

    Lifecycle per turn:
        begin_turn()                      — called when the user submits a prompt
        accrue_subagent_tokens(usage)     — called for each Task notification
        commit_turn(...)                  — called when ResultMessage arrives

    Two gates in commit_turn (in order):

    1. ``_committed`` flag — idempotency gate that prevents a stray second
       ResultMessage from double-billing regardless of what data the renderer
       has set on last_usage/last_cost at call time.  The flag is reset only by
       begin_turn() so it remains effective for the rest of the turn.

    2. Null-data guard — skips add_turn (and the turns counter) when the
       ResultMessage carries neither usage nor cost data (interrupted/error
       turns).  The ``_committed`` flag is set first so that a later real
       ResultMessage for the same turn cannot accidentally bill it.
    """

    def __init__(self) -> None:
        self._stats = UsageStats()
        self._turn_subagent_tokens = 0
        self._committed = False

    @property
    def stats(self) -> UsageStats:
        return self._stats

    def begin_turn(self) -> None:
        """Reset the subagent-token accumulator and committed flag at turn start."""
        self._turn_subagent_tokens = 0
        self._committed = False

    def accrue_subagent_tokens(self, usage: dict | None) -> None:
        """Accumulate Task notification token spend for the current turn's cost split."""
        self._turn_subagent_tokens += int((usage or {}).get("total_tokens", 0) or 0)

    def commit_turn(
        self,
        *,
        last_usage: dict | None,
        last_cost: float | None,
        last_model_usage: dict | None,
        main_models: "set[str] | list[str] | None",
    ) -> None:
        """Commit one turn's stats and reset the subagent-token counter.

        Two guards in order:

        1. ``_committed`` flag — idempotency gate.  Once set, any further call
           (e.g. from a stray second ResultMessage) returns immediately without
           touching stats.  The flag is reset only by begin_turn() so it remains
           effective for the rest of the turn regardless of the renderer's state.

        2. Null-data guard — mirrors the original ``_on_turn_complete`` check
           (``if last_usage is not None or last_cost is not None``).  When the
           ResultMessage carries no usage and no cost (e.g. an interrupted or
           error turn) we mark the turn committed (preventing a later real
           ResultMessage from accidentally billing it) but do NOT call add_turn,
           preserving the original behaviour where ``stats.turns`` is not
           incremented for null-data turns.
        """
        if self._committed:
            return
        self._committed = True
        # Null-data guard: skip add_turn (and the turns counter) for interrupted
        # or error turns that carry neither usage nor cost data.
        if last_usage is None and last_cost is None:
            return
        self._stats.add_turn(
            last_usage,
            last_cost,
            last_model_usage,
            main_models,
            self._turn_subagent_tokens,
        )
        # Co-located reset — must come immediately after add_turn so a stray
        # second ResultMessage cannot accumulate the same subagent tokens again.
        self._turn_subagent_tokens = 0
