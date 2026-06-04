# headless-pass-live-fail-suspects-wiring

When identical operations pass in headless synthetic tests but fail in live terminal, the code logic is likely sound; suspect environment wiring (CSS selectors, event propagation, gating flags) or broken render-path triggers (missing refresh calls, compositor gaps).

_Category: Debugging_
