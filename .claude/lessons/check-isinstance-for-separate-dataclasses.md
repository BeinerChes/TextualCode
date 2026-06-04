# check-isinstance-for-separate-dataclasses

When dispatching on dataclass type, explicitly check isinstance for all separate dataclasses (not subclasses) to avoid silently dropping code paths in isinstance-based conditionals.

_Category: Logic_
