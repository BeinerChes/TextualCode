# size-cap-and-binary-detect-content-previews

When reading untracked files for preview on worker threads, cap size (64 KB / 200 lines) and detect binary content (null-byte check) to prevent UI hangs and out-of-memory crashes.

_Category: Threading_
