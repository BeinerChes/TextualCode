# verify-api-not-guess

Never guess an API or framework behavior. Verify in this order: (1) check the installed package version first so verification targets it; (2) web search is the primary method — prefer Anthropic's official docs/repos for Claude/Agent-SDK topics, else the library's official docs/GitHub, scoped to that version; (3) reading installed `.venv` source is the fallback when a search can't confirm it. If the installed version is outdated, propose upgrading before building on old behavior. Reasoning from memory never counts; always cite what you checked and the version it applies to.

_Category: Workflow_
