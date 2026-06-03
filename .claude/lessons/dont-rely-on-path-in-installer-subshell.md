# dont-rely-on-path-in-installer-subshell

Use filesystem probes for well-known install locations in installer subshells instead of PATH-based lookup to avoid false warnings when child processes inherit the subshell's stripped environment.

_Category: Installation Scripts_
