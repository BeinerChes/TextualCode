# git-detection-three-states

Before using git as a subprocess feature, detect and handle three states defensively—git not on PATH, git present but not in repo, valid repo—with graceful fallbacks for each. Prevents crashes and unusable features for users without git or in non-git directories.

_Category: Subprocess Robustness_
