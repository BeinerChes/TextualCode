# merge-preserve-on-settings-write

When writing permission updates to settings.json files, read the existing JSON, update the target keys in place, and write back the merged result instead of overwriting, to prevent silent data loss of unrelated config keys (allow rules, voice settings, etc.) and handle missing files gracefully.

_Category: Configuration_
