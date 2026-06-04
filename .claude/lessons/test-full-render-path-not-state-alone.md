# test-full-render-path-not-state-alone

For rendering/UI tests, assert the complete path (state change → refresh signal → render invoked → visual output changed), not just intermediate state, to catch broken re-render triggers (refresh not called, compositor skipped, or broken render logic).

_Category: Testing_
