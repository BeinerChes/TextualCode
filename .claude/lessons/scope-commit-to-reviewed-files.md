# scope-commit-to-reviewed-files

When an LLM drafts a commit message based on a truncated diff snapshot, stage only the files the model actually reviewed via git pathspec, not git add -A, to prevent unreviewed secrets and post-snapshot changes from being committed with incorrect descriptions.

_Category: Security_
