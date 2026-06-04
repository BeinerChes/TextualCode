# explicit-utf8-encoding-in-headless-tests

In headless terminal-application tests, explicitly set UTF-8 output encoding to prevent Windows cp1252 fallbacks that suppress or hide non-ASCII render assertions; verify encoding setup before asserting on glyph output.

_Category: Testing_
