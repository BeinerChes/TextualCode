"""Disposable benchmark: Textual `Markdown` widget vs `Static(rich Markdown)`.

Predicts the scroll-jank win of swapping the per-message Markdown widget for a
single pre-rendered Static. Measures the two things that drive scroll cost:
  - total live widget count in the scroll log (compositor + layout bookkeeping)
  - time to force a full relayout once everything is mounted

Run:  uv run python bench_render.py
This file is throwaway — delete after we read the numbers.
"""

from __future__ import annotations

import asyncio
import time

from rich.markdown import Markdown as RichMarkdown
from textual.app import App, ComposeResult
from textual.containers import VerticalScroll
from textual.widgets import Markdown, Static

# A representative "heavy" agent message: heading + prose + fenced code + list.
HEAVY_MD = """## Section heading

Some explanatory paragraph with **bold**, `inline code`, and a
[link](https://example.com) that wraps across a couple of lines to simulate a
realistic agent message body with enough text to matter.

```python
def example(n: int) -> int:
    total = 0
    for i in range(n):
        total += i * i
    return total
```

- first bullet point with a bit of text
- second bullet point with more text here
- third bullet point to round it out
"""

N = 50  # heavy messages, matching the reported "jumpy" case


class Bench(App):
    def __init__(self, mode: str) -> None:
        super().__init__()
        self.mode = mode

    def compose(self) -> ComposeResult:
        yield VerticalScroll(id="log")


async def run_variant(mode: str) -> tuple[int, float, float]:
    app = Bench(mode)
    async with app.run_test(size=(100, 40)) as pilot:
        log = app.query_one("#log", VerticalScroll)

        t0 = time.perf_counter()
        for _ in range(N):
            if mode == "markdown":
                await log.mount(Markdown(HEAVY_MD))
            else:  # static
                await log.mount(Static(RichMarkdown(HEAVY_MD)))
        await pilot.pause()
        mount_s = time.perf_counter() - t0

        widget_count = len(log.query("*"))

        # Force a full relayout (what a scroll/resize triggers) and time it.
        t2 = time.perf_counter()
        for _ in range(5):
            app.refresh(layout=True)
            await pilot.pause()
        relayout_s = (time.perf_counter() - t2) / 5

        return widget_count, mount_s, relayout_s


async def main() -> None:
    print(f"\n{N} heavy messages — Textual Markdown vs Static(rich Markdown)\n")
    print(f"{'variant':10s} {'widgets':>9s} {'mount':>10s} {'relayout/ea':>13s}")
    print("-" * 46)
    results = {}
    for mode in ("markdown", "static"):
        widgets, mount_s, relayout_s = await run_variant(mode)
        results[mode] = (widgets, mount_s, relayout_s)
        print(f"{mode:10s} {widgets:9d} {mount_s * 1000:8.1f}ms {relayout_s * 1000:11.1f}ms")

    mw, ms, mr = results["markdown"]
    sw, ss, sr = results["static"]
    print("\nratios (markdown / static):")
    print(f"  widgets : {mw / max(sw, 1):5.1f}x more")
    print(f"  mount   : {ms / max(ss, 1e-9):5.1f}x slower")
    print(f"  relayout: {mr / max(sr, 1e-9):5.1f}x slower")


if __name__ == "__main__":
    asyncio.run(main())
