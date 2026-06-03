# escape-untrusted-cli-output-before-markup

Route git and shell command output (stderr, file paths, commit text) through an escaper before passing to Text.from_markup(), or use plain Text(..., style=...), to prevent malformed shell output containing [ or ] from raising MarkupError and breaking error-safe panels.

_Category: UI Safety_
