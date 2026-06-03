# TextualCode — Bug Report (Haiku Code Review)

> Generated 2026-06-02 via parallel Haiku code review of `agent.py`, `permissions.py`, `app.py`.

---

## `agent.py`

### BUG-1 — Race condition in `reconnect()`
`_client` is set to `None` before `connect()` completes. If `aclose()` fails or `connect()` raises partway through, the session is left in an indeterminate state — neither fully connected nor fully closed. Callers that subsequently call `_require_client()` may operate on a partially-failed connection.

**Fix:** Use `try/finally` to separate `aclose()` failures from `connect()` failures; only null `_client` once the new connection is confirmed.

---

### BUG-2 — State mismatch in `set_model()`
`self.model` is updated *before* the SDK's `set_model()` call (line 98 before line 99). If the SDK raises, the local model field is stale — the next `reconnect()` will attempt to use it.

**Fix:** Call the SDK first; update `self.model` only on success.
```python
await self._require_client().set_model(model)
self.model = model
```

---

### BUG-3 — Silent iterator failure after disconnect
The long-lived `messages()` pump in `app.py` iterates `_client` across a concurrent `reconnect()`. When `reconnect()` sets `_client = None`, the iterator raises `RuntimeError` which is swallowed by a blanket `except` — masking the failure entirely.

**Fix:** Catch `RuntimeError` explicitly in the pump and surface it as a reconnect event, or guard the iterator with the `asyncio.Lock` proposed in improvements.

---

## `permissions.py`

### BUG-4 — `IndexError` in `similarity_key()` on whitespace input
`command.split(maxsplit=1)` on a whitespace-only string (e.g. `"   "`) returns `[]`. Indexing `[0]` then raises `IndexError`. The existing `if not command` guard only catches empty strings, not whitespace-only ones.

**Fix:**
```python
parts = command.split(maxsplit=1)
first = parts[0] if parts else ""
```

---

### BUG-5 — Newline never detected in `_has_shell_operator()`
`_SHELL_OPERATORS` contains the two-character literal string `'\\n'` (backslash + n) rather than a real newline character (`'\n'`). The `in` check against an actual command string will therefore never match a real newline, allowing multiline Bash commands to bypass the re-prompt safety gate.

**Fix:** Replace the escaped literal with a real newline in the operators tuple:
```python
'\n',  # real newline, not '\\n'
```

---

## `app.py`

### BUG-6 — `message_pump()` may not be properly awaited
At lines 254/269 `message_pump()` appears to be called in a context where it may not be awaited. If `@work` does not automatically schedule it, the pump never runs and no messages are processed.

**Fix:** Verify `@work` invocation semantics; if called directly, ensure it is `await`ed or explicitly submitted as a background task.

---

### BUG-7 — Context refresh silently dropped in `_on_turn_complete()`
`_on_turn_complete()` triggers `refresh_context()` (an async worker) from within the `message_pump` async-for loop with no `await` and no explicit task scheduling. If the pump advances before the worker is scheduled, the context refresh is silently skipped.

**Fix:** Either `await` the refresh or schedule it as an explicit Textual worker call to ensure it always runs.
