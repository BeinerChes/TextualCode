# directorytree-skip-expensive-folders

Subclass DirectoryTree and override filter_paths to skip .git/, node_modules/, .venv/, and other expensive folders; DirectoryTree expands on-demand, and expanding these folders freezes the UI. Prevents user-triggered UI freezes on exploration.

_Category: UI Performance_
