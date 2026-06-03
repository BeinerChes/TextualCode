# Lessons Index

Cross-session lessons harvested from coding sessions. Each line is an imperative rule; open the file for detail.

## Architecture

- [isolate-extraction-to-subagent.md](isolate-extraction-to-subagent.md) — Extract structured maps into isolated subagents (cheaper models like Haiku) rather than inline processing to reduce token cost and enable composable skill chains.

## Deployment

- [embed-resources-in-code-for-isolation.md](embed-resources-in-code-for-isolation.md) — When deploying agents with restricted I/O access, embed critical resources like prompts as code constants rather than configuration files to survive isolation boundaries.

## ContextManagement

- [map-over-summary-for-context-rot.md](map-over-summary-for-context-rot.md) — Replace prose summaries with structured maps (goal, did, mistakes, result, next, keywords) to fight context rot; maps enable selective re-anchoring and require fewer tokens than narrative reconstruction.
