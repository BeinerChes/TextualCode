# always-sanitize-model-controlled-filenames

Always apply path-sanitization (e.g., _slugify or is_relative_to confinement) to any model/user-controlled data before using it in Path() filesystem operations to prevent CWE-22 arbitrary file writes.

_Category: Security_
