# Bug Report: TextualCode Agent Project

**Generated:** 2026-06-02
**Scope:** `textualcode/` module (agent.py, app.py, commands.py, config.py, permissions.py, renderer.py, screens.py, stats.py, widgets.py)
**Total Issues Found:** 62

---

## Executive Summary

| Severity | Count |
|----------|-------|
| 🔴 Critical | 1 |
| 🟠 High | 17 |
| 🟡 Medium | 26 |
| 🟢 Low | 18 |

---

## Bug Details

### agent.py

---

#### BUG-001 — Async Generator Mis-annotation and Lazy Execution

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 84–89 |
| **Severity** | 🟠 High |
| **Category** | Type error / incorrect annotation |

**Description:**
`send` is declared `async def` with a `yield` inside it, making it an async generator function, not a coroutine that returns `AsyncIterator[Message]`. The return-type annotation `-> AsyncIterator[Message]` is wrong; the actual runtime type is `AsyncGenerator[Message, None]`. More importantly, `await client.query(prompt)` executes lazily inside the generator body — if the caller never begins iterating, the query is never sent. Any code path that does `await agent.send(text)` instead of `async for ... in agent.send(text)` silently receives a generator object and does nothing, with no error raised.

```python
async def send(self, prompt: str) -> AsyncIterator[Message]:
    """Send a prompt and yield each streamed response message."""
    client = self._require_client()
    await client.query(prompt)
    async for message in client.receive_response():
        yield message
```

**Best Practice:**
Annotate async generator functions with `-> AsyncGenerator[YieldType, None]` (e.g., `async def stream() -> AsyncGenerator[int, None]`) rather than `-> AsyncIterator[int]`. This accurately reflects the concrete type returned, prevents false type-checker errors about missing `.aclose()`/`.asend()` methods, and makes it immediately clear to readers that the function uses `yield` internally. Reserve `AsyncIterator[T]` for abstract parameter or return-type annotations where any async-iterable object is acceptable.

**Recommendation:** Change the return annotation to `-> AsyncGenerator[Message, None]` and document that callers must use `async for` — never `await` — on the return value.

---

#### BUG-002 — Inconsistent State if `get_server_info` Raises During `connect`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 50–65 |
| **Severity** | 🟠 High |
| **Category** | Resource leak / incorrect state on partial failure |

**Description:**
`connect` assigns `self._client = client` (line 63) before calling `get_server_info()` (line 64). If `get_server_info` raises, the session is left in an inconsistent state: `connected` returns `True`, `_models` is empty `[]`, and the partially-initialised client object is stored. Any subsequent call that uses `_require_client()` will proceed against a client that may not be fully ready.

```python
await client.connect()
self._client = client          # assigned before get_server_info
info = await client.get_server_info()
self._models = list(info.get("models", [])) if info else []
```

**Best Practice:**
Wrap all async resource acquisition in an `@asynccontextmanager` with a `try/finally` block wrapping the `yield` so any resource successfully acquired is always released on exit, even during partial initialization failures.

**Recommendation:** Defer `self._client = client` until after all post-connect setup succeeds, or wrap the post-connect setup in a `try/except` that calls `client.disconnect()` and re-raises on failure. Use a `try/finally` to ensure cleanup.

---

#### BUG-003 — Double-Connect Resource Leak

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 50–65 |
| **Severity** | 🟡 Medium |
| **Category** | Resource leak / double-connect |

**Description:**
`connect` has no guard against being called while already connected. If called a second time (e.g. race between two workers), it creates a new `ClaudeSDKClient` and overwrites `self._client` without disconnecting the previous one, permanently leaking the old connection.

```python
async def connect(self) -> None:
    options = ClaudeAgentOptions(...)
    client = ClaudeSDKClient(options=options)
    await client.connect()
    self._client = client   # old client silently dropped if already connected
```

**Best Practice:**
Guard the connect coroutine with an `asyncio.Lock` and a post-lock state re-check. In a Textual app, additionally decorate the worker with `@work(exclusive=True)` so re-triggering the worker automatically cancels any in-flight connection attempt before starting a new one.

**Recommendation:** Add a guard at the top of `connect`: `if self.connected: return`. Also add an `asyncio.Lock` (`self._connect_lock`) and use `async with self._connect_lock:` to make the guard race-safe.

---

#### BUG-004 — `aclose` Not Atomic; Broken State on Disconnect Exception

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 104–107 |
| **Severity** | 🟠 High |
| **Category** | Resource leak / inconsistent state on exception |

**Description:**
`aclose` is not atomic. If `await self._client.disconnect()` raises an exception, `self._client = None` is never reached. The session is left in a permanently broken state: `connected` still returns `True`, but subsequent calls via `_require_client()` will use a half-closed client, and repeated calls to `aclose()` will repeatedly attempt `disconnect()` on an already-broken client.

```python
async def aclose(self) -> None:
    if self._client is not None:
        await self._client.disconnect()   # if this raises ...
        self._client = None               # ... this line is never reached
```

**Best Practice:**
Wrap any `aclose()` or `disconnect()` call in a `try/finally` block inside `on_unmount` (or the equivalent cleanup handler), and always re-raise `CancelledError` after cleanup completes. Use `async with contextlib.aclosing(resource):` rather than manually calling `aclose()` in a bare except block.

**Recommendation:** Rewrite as:
```python
async def aclose(self) -> None:
    if self._client is not None:
        try:
            await self._client.disconnect()
        finally:
            self._client = None
```

---

#### BUG-005 — `reconnect` Has No Rollback on `connect` Failure

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 76–82 |
| **Severity** | 🟡 Medium |
| **Category** | State management bug / no rollback on failure |

**Description:**
`reconnect` calls `aclose()` first, then `connect()`. If `connect()` fails, the session is left fully disconnected: `_client` is `None`, `connected` is `False`, but `_models` still holds stale data from the previous session. The caller shows an error but does not restore the previous state, leaving the app in an offline state with no recovery path.

```python
async def reconnect(self) -> None:
    await self.aclose()   # old connection destroyed
    await self.connect()  # if this fails, session is gone with no rollback
```

**Best Practice:**
Wrap each reconnect attempt in an async context manager that snapshots mutable app state on entry and rolls it back in `__aexit__` if an exception is raised, then drive the reconnect loop with exponential backoff.

**Recommendation:** Snapshot `self._client` and `self._models` before `aclose()`. On `connect()` failure, restore the snapshot and re-raise. Consider a `try/except` in `reconnect_agent` (in `app.py`) that restores state and notifies the user.

---

#### BUG-006 — Default-Allow Permission Policy (Security)

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 114–125 |
| **Severity** | 🟠 High |
| **Category** | Security / incorrect default permission |

**Description:**
When `_permission_handler` is `None`, `_approve_tool` falls through to `return PermissionResultAllow()`, auto-approving every tool call including destructive ones like `Bash`, `Write`, and `Edit`. The safe default should be `PermissionResultDeny`. Any `AgentSession` instantiated without a `permission_handler` silently grants all tool calls.

```python
if self._permission_handler is None:
    return PermissionResultAllow()   # should be Deny for unknown/destructive tools
```

**Best Practice:**
Structure evaluation as: (1) explicit allow for known-safe operations, (2) explicit deny for known-dangerous patterns, (3) a hard default-deny fallback for everything else — never return `PermissionResultAllow()` as the catch-all default.

**Recommendation:** Change the fallback to `return PermissionResultDeny(message="No permission handler configured")`. If a read-only auto-allow is desired, enumerate specific safe tools explicitly.

---

#### BUG-007 — Concurrent `send` Calls Race on Shared Client

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 84–89 |
| **Severity** | 🟡 Medium |
| **Category** | Async/await race condition |

**Description:**
`send` has no concurrency guard. Two concurrent callers can both call `client.query(prompt)` and then both iterate `client.receive_response()` on the same underlying client, interleaving or corrupting the response stream. The `@work(exclusive=True)` in `app.py` provides protection at the app layer, but `AgentSession.send` itself provides no protection.

```python
async def send(self, prompt: str) -> AsyncIterator[Message]:
    client = self._require_client()
    await client.query(prompt)
    async for message in client.receive_response():
        yield message
```

**Best Practice:**
Replace any Lock-guarded concurrent `__anext__()` calls with a single pump coroutine: create one `asyncio.Queue` per consumer, launch the pump as a background task that iterates the generator exclusively, then have each consumer do `await queue.get()`.

**Recommendation:** Add a lock guard (`self._send_lock = asyncio.Lock()`) in `AgentSession` and wrap the body of `send` with `async with self._send_lock:` so the method is self-contained and safe regardless of caller context.

---

#### BUG-008 — `available_models()` Exposes Internal List Reference

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 72–74 |
| **Severity** | 🟢 Low |
| **Category** | State management bug / mutable internal state exposed |

**Description:**
`available_models()` returns `self._models` directly. Callers receive a reference to the internal list and can mutate it (append, clear, etc.), corrupting `AgentSession` state.

```python
def available_models(self) -> list[dict]:
    return self._models   # caller gets a direct reference to internal state
```

**Best Practice:**
In any property or method that returns an internal list, return a copy instead of the raw reference. For a flat list of immutable items use `return self._items.copy()`.

**Recommendation:** Change to `return list(self._models)`. Since models contain dicts (mutable), consider `return [m.copy() for m in self._models]` for deeper protection.

---

#### BUG-009 — `_approve_tool` Ignores `context` Parameter

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 114–125 |
| **Severity** | 🟢 Low |
| **Category** | Claude Agent SDK misuse / ignored parameter |

**Description:**
The `_approve_tool` callback accepts a `context` parameter from the SDK but never uses it. If the SDK ever changes the callback signature or passes `context` as a keyword-only argument, the positional mismatch will raise a `TypeError` at runtime.

```python
async def _approve_tool(self, tool_name, tool_input, context):
    # context is never inspected or forwarded
```

**Best Practice:**
Always declare your callback with all three parameters — `async def my_callback(tool_name: str, input_data: dict, context: ToolPermissionContext) -> PermissionResultAllow | PermissionResultDeny` — and import `ToolPermissionContext` from `claude_agent_sdk.types`. Use `context.title` as the human-readable prompt text in any approval UI, and return `PermissionResultAllow(updated_permissions=context.suggestions)` when persisting approvals.

**Recommendation:** Add proper type annotations: `async def _approve_tool(self, tool_name: str, tool_input: dict, context: ToolPermissionContext) -> PermissionResult:`. Forward `context` to the permission handler so policy decisions can use it.

---

#### BUG-010 — `set_model` Updates State Before SDK Call

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 91–93 |
| **Severity** | 🟡 Medium |
| **Category** | State management bug / partial update on error |

**Description:**
`set_model` updates `self.model` before the async SDK call. If `_require_client().set_model(...)` raises an exception, the in-memory `self.model` is already changed even though the SDK rejected it, leaving `AgentSession.model` out of sync with the actual model in use.

```python
async def set_model(self, model: str | None) -> None:
    self.model = model   # updated before SDK call; stale on failure
    await self._require_client().set_model(self._normalize_model(model))
```

**Best Practice:**
Wrap every multi-step async state mutation in an `@asynccontextmanager` that saves a snapshot of the relevant state before `yield` and restores it in the `except` branch.

**Recommendation:** Save the previous model, perform the SDK call, and only commit the update on success:
```python
async def set_model(self, model: str | None) -> None:
    previous = self.model
    try:
        await self._require_client().set_model(self._normalize_model(model))
        self.model = model
    except Exception:
        self.model = previous
        raise
```

---

#### BUG-011 — Resource Leak When `get_server_info` Raises (variant)

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 61–65 |
| **Severity** | 🟡 Medium |
| **Category** | Resource leaks |

**Description:**
In `connect()`, if `client.connect()` succeeds but `client.get_server_info()` raises an exception, `self._client` is never assigned and the connected client is leaked — `disconnect()` is never called because `self._client` is still `None`. The client object is unreachable after `connect()` raises.

```python
client = ClaudeSDKClient(options=options)
await client.connect()
self._client = client          # only set AFTER get_server_info
info = await client.get_server_info()
```

**Best Practice:**
Wrap every async connection or resource acquisition in an `@asynccontextmanager` function that uses `try/finally` to call `await resource.aclose()` in the `finally` block.

**Recommendation:** Use a `try/except` block to call `await client.disconnect()` if `get_server_info` raises before the client is assigned to `self._client`.

---

#### BUG-012 — `send()` query/receive_response Race Condition

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 84–89 |
| **Severity** | 🟠 High |
| **Category** | Async/await issues |

**Description:**
If `client.receive_response()` returns the same stream that `query` initiates, calling `query` separately before iterating may result in a race condition or dropped messages if the response starts streaming before the `receive_response` loop begins. Additionally, if `query` itself raises, the exception propagates before any cleanup, leaking the in-progress request.

```python
async def send(self, prompt: str) -> AsyncIterator[Message]:
    client = self._require_client()
    await client.query(prompt)
    async for message in client.receive_response():
        yield message
```

**Best Practice:**
Wrap the async for loop that consumes `receive_response()`/`query()` in an outer `asyncio.wait_for(..., timeout=N)` to prevent indefinite hanging when the streaming connection stalls.

**Recommendation:** Wrap the entire send body in a `try/finally` to ensure cleanup on exception from `query`. Consider combining query and receive into a single atomic operation if the SDK supports it.

---

#### BUG-013 — `context_usage()` Swallows All Exceptions Silently

| Field | Detail |
|-------|--------|
| **File** | `textualcode/agent.py` |
| **Lines** | 101–102 |
| **Severity** | 🟡 Medium |
| **Category** | Exception handling problems |

**Description:**
The bare `except Exception` in `context_usage()` swallows all errors silently, including genuine programming errors. Any SDK bug or connection error during a `get_context_usage()` call is silently discarded with no logging, making post-mortem debugging impossible.

```python
except Exception:  # noqa: BLE001 - degrade gracefully if unsupported
    return None
```

**Best Practice:**
Attach a `add_done_callback` to every `asyncio.create_task()` call using a reusable helper that calls `task.result()` in a try/except and logs the exception immediately.

**Recommendation:** At minimum, add `logging.debug("context_usage failed", exc_info=True)` inside the except block so failures are visible in debug logs without impacting users.

---

### app.py

---

#### BUG-014 — `_ask_permission` Future Leak and Thread-Safety Issue

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 132–146 |
| **Severity** | 🟠 High |
| **Category** | Async/await — race condition / Future leak |

**Description:**
`_ask_permission` creates a Future tied to `asyncio.get_running_loop()` inside a Textual worker context. If the `PermissionDialog` is dismissed without calling the callback (e.g. the screen is forcibly removed during app shutdown, or `push_screen` itself raises), `_resolve` is never called and the Future returned from `await future` hangs forever, blocking the SDK's approval callback task indefinitely. There is no timeout and no cancellation path. Additionally, if Textual's dismiss runs in a different task from a different event loop (e.g. in a thread-pool worker), `set_result` would be called from the wrong thread, corrupting the Future.

```python
future: asyncio.Future[Decision] = asyncio.get_running_loop().create_future()
...
self.push_screen(PermissionDialog(tool_name, tool_input, label), _resolve)
return await future
```

**Best Practice:**
Use Textual's built-in `push_screen(screen, callback)` pattern and let Textual invoke the callback on the main thread. If you genuinely need an awaitable result from a pushed screen, create the Future on the event loop thread, then schedule the `set_result` call safely: `self.app.call_from_thread(fut.set_result, value)` from a thread worker, or `loop.call_soon_threadsafe(fut.set_result, value)` from bare-thread code — never call `set_result` directly from outside the event loop thread.

**Recommendation:** Add `asyncio.wait_for(future, timeout=300)` to prevent indefinite hangs. Use `loop.call_soon_threadsafe(future.set_result, value)` inside `_resolve` to guarantee thread safety.

---

#### BUG-015 — Wrong Return Type Annotation on `send()` Creates Silent Breakage Risk

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 288–303 |
| **Severity** | 🟠 High |
| **Category** | Async/await — wrong return type annotation causes silent breakage |

**Description:**
`AgentSession.send()` is declared as `async def send(...) -> AsyncIterator[Message]` but its body uses `yield`, making it an async generator function. The confusion between the coroutine and async-generator boundary means that any refactor that mistakenly adds `await` before the call will silently swallow all messages.

```python
async for message in self._agent.send(text):
    await self._renderer.render(message)
```

**Best Practice:**
Annotate async generator functions as `AsyncGenerator[YieldType, None]` rather than `AsyncIterator[YieldType]`. This avoids false-positive type-checker errors about missing `.aclose()`/`.athrow()`/`.asend()` methods and accurately reflects the concrete return type.

**Recommendation:** Fix the annotation on `agent.py`'s `send()` to `-> AsyncGenerator[Message, None]` (see BUG-001) and add a type-checker comment at the call site if needed.

---

#### BUG-016 — Agent `send` Generator Not Cleaned Up on Worker Cancellation

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 288–303 |
| **Severity** | 🟡 Medium |
| **Category** | Resource leak — agent send not cancelled on worker cancellation |

**Description:**
`send_to_agent` is a `@work(exclusive=True)` worker. If a new agent worker is started while one is running, Textual cancels the old worker. The `async for message in self._agent.send(text)` generator is not explicitly closed in that case, so the underlying SDK streaming session may not be properly terminated. The `finally` block runs `context_usage()` on the agent which may itself fail or return stale data after an abrupt cancel.

```python
@work(exclusive=True, group="agent")
async def send_to_agent(self, text: str) -> None:
    ...
    async for message in self._agent.send(text):
        await self._renderer.render(message)
```

**Best Practice:**
Wrap every async generator iteration in `async with contextlib.aclosing(my_gen()) as gen:` and add a `try/finally` block inside your Textual async worker coroutine that calls `await gen.aclose()` on exit.

**Recommendation:**
```python
async with contextlib.aclosing(self._agent.send(text)) as stream:
    async for message in stream:
        await self._renderer.render(message)
```

---

#### BUG-017 — `reconnect_agent` Leaves Agent Half-Disconnected on Cancellation

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 245–261 |
| **Severity** | 🟠 High |
| **Category** | Race condition — reconnect_agent reads tools before connect completes |

**Description:**
If two rapid `_apply_tools()` calls occur, the exclusive `"connect"` group cancels the first reconnect mid-flight and starts the second. The agent may be left in a half-disconnected state if `aclose()` completed but `connect()` was cancelled before setting `self._client`.

```python
@work(exclusive=True, group="connect")
async def reconnect_agent(self) -> None:
    tools = self._agent.tools
    ...
    await self._agent.reconnect()
```

**Best Practice:**
Guard every state-mutating step inside a worker with an `is_cancelled` check, and route all UI updates through `call_from_thread()` rather than setting reactive variables directly.

**Recommendation:** Check `get_current_worker().is_cancelled` after `await self._agent.aclose()` and before `await self._agent.connect()`. If cancelled, skip `connect()` to avoid a partial-initialization state.

---

#### BUG-018 — Synchronous File I/O on UI Thread in `_apply_tools`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 126–130 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug — _apply_tools called synchronously from get_system_commands |

**Description:**
`_apply_tools()` calls `self._project.save()`, which performs synchronous disk I/O on the UI thread, potentially blocking the event loop.

```python
def _apply_tools(self, tools: list[str] | None) -> None:
    self._project.tools = tools
    self._project.save(self._project_dir)  # synchronous file I/O on UI thread
    self._agent.tools = tools
    self.reconnect_agent()
```

**Best Practice:**
Wrap every synchronous file I/O call in a Textual worker thread: decorate the method with `@work(thread=True)` (or call `self.run_worker(my_sync_func, thread=True)`), then use `self.app.call_from_thread(self.update_ui, result)` to post results back to the main thread.

**Recommendation:** Move `self._project.save(self._project_dir)` inside `reconnect_agent` (which is already a worker), or wrap it in a `@work(thread=True)` call.

---

#### BUG-019 — `switch_model` May Receive String `"None"` from ModelSelector

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 199–225 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug — switch_model does not guard against empty name after open_model_selector |

**Description:**
`ModelSelector.action_save()` calls `self.dismiss(str(self._models[index]["value"]))` which could produce the string `"None"` if `model["value"]` is Python `None`. `match_model` would then search for `"none"` in displayName/description and potentially match an unintended model, or fall through and send the literal string `"none"` to the SDK.

```python
chosen = await self.push_screen_wait(ModelSelector(models, self._model_label))
if chosen is not None:
    await self.switch_model(chosen)
```

**Best Practice:**
Replace any bare `str(value)` or `f"{value}"` where value is `Optional` with an explicit guard: use `value if value is not None else ""`.

**Recommendation:** In `ModelSelector.action_save()`, guard: `value = self._models[index].get("value"); if value is None: return; self.dismiss(str(value))`.

---

#### BUG-020 — `on_mount` Calling `@work` — Benign but Fragile

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 100 |
| **Severity** | 🟢 Low |
| **Category** | Textual framework misuse — synchronous call to @work from on_mount |

**Description:**
`on_mount` calls `self.connect_agent()` which is a `@work` decorator. This is functionally correct, but `sub_title` is set to `"connecting…"` before the worker actually starts. If `on_mount` is somehow called twice, the exclusive flag would cancel the running worker silently.

```python
await self._conversation.add_markdown(WELCOME)
self.query_one("#prompt", Input).focus()
self.connect_agent()
```

**Best Practice:**
Triggering a `@work(exclusive=True)` method inside `on_mount` is the standard pattern for kicking off an initial data load automatically while still protecting against future re-triggers racing each other.

**Recommendation:** This is acceptable as-is; document why `sub_title` is set before the worker starts to prevent future confusion.

---

#### BUG-021 — `KeyError` in `get_system_commands` When Model Lacks `"value"`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 155–159 |
| **Severity** | 🟡 Medium |
| **Category** | Edge case — KeyError crash in get_system_commands when model dict lacks 'value' |

**Description:**
`get_system_commands` accesses `model['value']` directly without `.get()`. If any model dict returned by the SDK is missing the `'value'` key, this raises a `KeyError` inside `get_system_commands`, crashing the command palette unexpectedly.

```python
partial(self._switch_model_worker, str(model["value"]))
```

**Best Practice:**
Prefer `dict.get(key, default)` over `dict[key]` bracket access when a key may be absent.

**Recommendation:** Change to `model.get("value")` with an explicit `None` check: `if (val := model.get("value")) is not None: yield SystemCommand(...)`.

---

#### BUG-022 — `_switch_model_worker` Not Exclusive; Concurrent Switches Possible

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 305–308 |
| **Severity** | 🟢 Low |
| **Category** | Textual framework misuse — _switch_model_worker not exclusive |

**Description:**
`_switch_model_worker` is decorated `@work(group="agent")` without `exclusive=True`. Two concurrent invocations can race on `set_model`, with the final model state determined by whichever coroutine finishes last rather than whichever was invoked last.

```python
@work(group="agent")
async def _switch_model_worker(self, name: str) -> None:
    await self.switch_model(name)
```

**Best Practice:**
Decorate your model-switching method with `@work(exclusive=True, group="model_switch")` so triggering a new model switch automatically cancels any in-flight switch worker in that group.

**Recommendation:** Change to `@work(exclusive=True, group="agent")`.

---

#### BUG-023 — User Message Shown Before Connectivity Check

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 193–197 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug — user message shown before connectivity check |

**Description:**
In `on_input_submitted`, the user's message is appended to the conversation view before checking whether the agent is connected. If the agent is not connected, the user's message already appears in the transcript with no corresponding agent reply, making the conversation look broken.

```python
await self._conversation.add_markdown(f"{USER_ICON} {text}")
if not self._agent.connected:
    await self._conversation.add_markdown("> Agent not connected yet — try again in a moment.")
    return
self.send_to_agent(text)
```

**Best Practice:**
Perform the connectivity check before appending the user message, or show the user message only after a successful send.

**Recommendation:** Move the `if not self._agent.connected:` check to before the `add_markdown` call.

---

#### BUG-024 — `on_unmount` Broad `except` Swallows Errors Silently

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 310–314 |
| **Severity** | 🟢 Low |
| **Category** | Exception handling — broad except swallows aclose errors silently |

**Description:**
`on_unmount` catches all exceptions from `aclose()` and passes silently. Any programming errors in `aclose()` during development would be invisible.

```python
async def on_unmount(self) -> None:
    try:
        await self._agent.aclose()
    except Exception:  # noqa: BLE001 - best-effort cleanup
        pass
```

**Best Practice:**
Replace any `except Exception: pass` blocks with a specific exception catch that calls `self.app.notify(str(e), title="Error", severity="error")` (or logs the error) so the user receives visible feedback.

**Recommendation:** Add at minimum `logging.warning("aclose failed during unmount", exc_info=True)` inside the except block.

---

#### BUG-025 — `send_to_agent` Finally Block Calls `context_usage` After Cancellation

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 296–303 |
| **Severity** | 🟠 High |
| **Category** | Async/await issues |

**Description:**
`send_to_agent` is a `@work` Textual worker. The `except Exception` block does NOT catch `CancelledError` (which is `BaseException`). The `finally` block still runs, but `self._agent.context_usage()` is then called on a potentially half-closed session, which could raise again inside `finally`, masking the original cancellation.

```python
except Exception as exc:  # noqa: BLE001 - keep the UI alive on errors
    await self._conversation.add_markdown(f"> **Error:** {type(exc).__name__}: {exc}")
finally:
    ...
    self._last_context = await self._agent.context_usage()
```

**Best Practice:**
For cleanup in async code, use `try/finally` (not `except Exception`) so cleanup always runs regardless of how the coroutine exits. If you catch `CancelledError` explicitly, always re-raise it.

**Recommendation:** Wrap the `context_usage()` call in a `try/except Exception` inside the `finally` block to prevent masking the original cancellation.

---

#### BUG-026 — Shared List Reference Between `_project.tools` and `_agent.tools`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 127–129 |
| **Severity** | 🟡 Medium |
| **Category** | State management bugs |

**Description:**
In `_apply_tools`, `self._project.tools = tools` and `self._agent.tools = tools` are set to the same list object. Subsequent mutations of one reference would silently affect the other.

```python
self._project.tools = tools
self._project.save(self._project_dir)
self._agent.tools = tools
```

**Best Practice:**
Replace any mutable default directly assigned with `field(default_factory=list)`, and when assigning shared data, always assign copies.

**Recommendation:** Change to `self._agent.tools = list(tools) if tools is not None else None` to break the aliasing.

---

#### BUG-027 — `push_screen` Called from SDK Task (Thread-Safety)

| Field | Detail |
|-------|--------|
| **File** | `textualcode/app.py` |
| **Lines** | 145 |
| **Severity** | 🟡 Medium |
| **Category** | Textual framework misuse |

**Description:**
`_ask_permission` calls `self.push_screen(...)` from the SDK's own task (not a Textual worker). Textual's `push_screen` is not documented as thread/task-safe when called outside of the main Textual event loop thread.

```python
self.push_screen(PermissionDialog(tool_name, tool_input, label), _resolve)
```

**Best Practice:**
Replace any direct `push_screen()` calls inside a thread worker with `self.call_from_thread(self.app.push_screen, MyScreen())`, or post a custom Message subclass with `self.post_message(MyMessage(...))` and handle the screen transition in the corresponding handler on the app.

**Recommendation:** Use `self.call_from_thread(self.push_screen, PermissionDialog(...), _resolve)` or post a custom message to trigger the permission dialog from the main event loop.

---

### commands.py

---

#### BUG-028 — `IndexError` When Input Is Bare `"/"`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/commands.py` |
| **Lines** | 35–36 |
| **Severity** | 🟠 High |
| **Category** | Edge case not handled / IndexError |

**Description:**
If `text` is exactly `"/"` (the slash with nothing after it), `text[1:]` is an empty string and `"".split(maxsplit=1)` returns `[]`. The very next line `parts[0]` then raises an `IndexError` that is completely unhandled, crashing the Textual worker.

```python
parts = text[1:].split(maxsplit=1)
name = parts[0].lower()  # IndexError when text == "/"
```

**Best Practice:**
Before accessing any index on a split result, guard with a truthiness check: `parts = text.split(); result = parts[0] if parts else default_value`.

**Recommendation:** Add a guard:
```python
parts = text[1:].split(maxsplit=1)
if not parts:
    raise UnknownCommand("")
name = parts[0].lower()
```

---

#### BUG-029 — No Runtime Validation That Handler Is Async

| Field | Detail |
|-------|--------|
| **File** | `textualcode/commands.py` |
| **Lines** | 33–41 |
| **Severity** | 🟡 Medium |
| **Category** | Missing await / async type-safety |

**Description:**
`dispatch` is typed to `await` any `Handler`, but there is no runtime check that the registered callable is actually a coroutine function. If a caller accidentally registers a plain synchronous function, `await handler(arg)` will raise a `TypeError` at call time with no descriptive error.

```python
def register(self, name: str, handler: Handler) -> None:
    self._handlers[name.lower()] = handler

# ...
await handler(arg)  # silently breaks if handler is sync
```

**Best Practice:**
Replace any use of `asyncio.iscoroutinefunction(fn)` with `inspect.iscoroutinefunction(fn)`. This is the only non-deprecated form as of Python 3.14+, and it correctly handles `unittest.mock.AsyncMock` and other duck-typed async callables.

**Recommendation:** In `register`, add: `if not inspect.iscoroutinefunction(handler): raise TypeError(f"Handler for '{name}' must be a coroutine function")`.

---

#### BUG-030 — Silent Handler Overwrite in Registry

| Field | Detail |
|-------|--------|
| **File** | `textualcode/commands.py` |
| **Lines** | 27 |
| **Severity** | 🟡 Medium |
| **Category** | Silent overwrite / state management |

**Description:**
`register` silently overwrites an existing handler for the same command name without any warning or error. If `register` is called a second time (e.g., on a reconnect, a plugin, or a test helper), the previous handler is lost silently.

```python
def register(self, name: str, handler: Handler) -> None:
    self._handlers[name.lower()] = handler  # silent overwrite
```

**Best Practice:**
In the registry's `register` method, add an explicit duplicate-key guard before every write: `if key in self._store: raise ValueError(f"Key '{key}' is already registered.")`.

**Recommendation:** Add `if name.lower() in self._handlers: raise ValueError(f"Command '{name}' is already registered")`. If re-registration is intentional, require `overwrite=True`.

---

#### BUG-031 — `dispatch` Assumes Leading `"/"` Without Enforcing It

| Field | Detail |
|-------|--------|
| **File** | `textualcode/commands.py` |
| **Lines** | 35 |
| **Severity** | 🟢 Low |
| **Category** | Type error / precondition not enforced |

**Description:**
`dispatch` slices `text[1:]` assuming the caller has already verified that `text` starts with `'/'`. If `dispatch` is ever called with a plain string, the slice silently consumes the first real character of the command name.

```python
async def dispatch(self, text: str) -> None:
    parts = text[1:].split(maxsplit=1)  # assumes text[0] == '/'
```

**Best Practice:**
Replace any `assert` used for input validation in public or library-facing functions with explicit `if not condition: raise ValueError(...)` guards at the top of the function body.

**Recommendation:** Add at the top: `if not text.startswith("/"): raise ValueError(f"dispatch expects a slash-prefixed command, got: {text!r}")`.

---

#### BUG-032 — `UnknownCommand.__init__` Has an Unhelpful `str()` Representation

| Field | Detail |
|-------|--------|
| **File** | `textualcode/commands.py` |
| **Lines** | 18 |
| **Severity** | 🟢 Low |
| **Category** | Exception design / usability |

**Description:**
`UnknownCommand.__init__` passes the raw name string as the sole positional arg to `Exception.__init__`. This means `str(exc)` returns just the bare name (e.g. `"foo"`) with no context.

```python
def __init__(self, name: str) -> None:
    super().__init__(name)  # str(exc) == "foo" — no context
```

**Best Practice:**
Always call `super().__init__(message)` with the fully composed human-readable message string as a positional argument.

**Recommendation:** Change to `super().__init__(f"Unknown command: /{name}")`.

---

### config.py

---

#### BUG-033 — `_read_tools` Returns Aliased JSON List

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 80–89 |
| **Severity** | 🟠 High |
| **Category** | State management bug — mutable default argument in dataclass |

**Description:**
`_read_tools` can return a raw list taken directly from the parsed JSON. That list is the same object that lives inside the parsed `data` dict. All callers that later mutate `self.tools` are mutating the JSON-originated object rather than an owned copy, which can cause surprising aliasing.

```python
return value if (value is None or isinstance(value, list)) else None
```

**Best Practice:**
Return a copy: `return list(value)` in `_read_tools`.

**Recommendation:** Change to `return list(value)` when `isinstance(value, list)` is true, to ensure the caller owns the list.

---

#### BUG-034 — `_read_tools` Does Not Validate List Element Types

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 104–110 |
| **Severity** | 🟡 Medium |
| **Category** | Type safety — list items not validated before use |

**Description:**
`_read_tools` accepts any list from the JSON without checking that every element is actually a `str`. If the config file contains `{"tools": [1, null, true]}` the method returns that list unchanged, typed as `list[str] | None`. Downstream code will produce opaque type errors.

```python
return value if (value is None or isinstance(value, list)) else None
```

**Best Practice:**
Use Pydantic v2's `TypeAdapter` for safe, declarative validation and casting of JSON list elements, or filter manually: `[str(t) for t in value if isinstance(t, str)]`.

**Recommendation:** Change to: `return [t for t in value if isinstance(t, str)]` to filter invalid elements, or raise a `ValueError` with a descriptive message if non-string elements are found.

---

#### BUG-035 — `load()` Swallows Unexpected `ValueError`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 91–101 |
| **Severity** | 🟡 Medium |
| **Category** | Exception handling — overly broad exception swallowing on load |

**Description:**
The `load()` method catches `(OSError, ValueError)`. `json.loads` raises `json.JSONDecodeError` which is a subclass of `ValueError`, so that is intentional. However, any other `ValueError` raised inside the try block will also be silently swallowed and replaced with a default config, making bugs invisible.

```python
except (OSError, ValueError):
    return cls()
```

**Best Practice:**
Replace any `except Exception:` or bare `except:` block that catches more than intended with the narrowest specific type. Never use a silent `pass` inside an except block for a broad exception type.

**Recommendation:** Change to `except (OSError, json.JSONDecodeError):` to avoid swallowing unrelated `ValueError` instances from future refactoring inside the try block.

---

#### BUG-036 — `save()` Silently Fails Without User Feedback

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 112–117 |
| **Severity** | 🟢 Low |
| **Category** | Exception handling — silent failure on save |

**Description:**
`save()` catches `OSError` and does `pass`, treating it as non-fatal. There is no logging, warning, or notification to the user that their config was not saved.

```python
except OSError:
    pass  # non-fatal: settings just won't persist
```

**Best Practice:**
Replace any `except Exception: pass` blocks with feedback: call `self.app.notify(str(e), title="Error", severity="error")` or at minimum log the error.

**Recommendation:** Add `logging.warning("Failed to save config: %s", exc_info=True)` inside the except block. In a Textual context, consider `self.app.notify("Failed to save settings", severity="warning")` if a reference to the app is available.

---

#### BUG-037 — `match_model` Returns Raw `name` Silently on No Match

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 19–34 |
| **Severity** | 🟢 Low |
| **Category** | Edge case — empty models list not handled |

**Description:**
`match_model` falls through to returning the raw `name` string if nothing matches. If `models` is an empty list, both loops are no-ops and the raw user string is returned unchanged as the active model string with no warning.

```python
for model in models:
    haystack = f"{model.get('displayName', '')} {model.get('description', '')}".lower()
    if query and query in haystack:
        return str(model["value"])
return name
```

**Best Practice:**
Add an explicit guard clause at the entry of the function that checks for the empty-list condition and either raises a descriptive exception or returns early with a clear sentinel.

**Recommendation:** Add `if not models: logging.warning("match_model called with empty models list for query %r", name)` before the loops.

---

#### BUG-038 — Empty-String Query Guard Inconsistent Between Loops

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 19–34 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug — empty-string query guard misplaced |

**Description:**
In the second loop, there is a `if query and query in haystack` guard, but the first loop `if str(model.get('value', '')).lower() == query` would match a model whose value field is the empty string `''` when the user passes an empty or whitespace-only name.

```python
query = name.strip().lower()
for model in models:
    if str(model.get("value", "")).lower() == query:
        return str(model["value"])
```

**Best Practice:**
In any search or filter handler, add an early-return guard as the very first line: `if not query.strip(): return`.

**Recommendation:** Add `if not query: return name` as the first line of `match_model` after computing `query`.

---

#### BUG-039 — `Settings` Frozen Dataclass Doesn't Validate Tuple Field Type

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 63–77 |
| **Severity** | 🟢 Low |
| **Category** | State management — frozen dataclass with mutable default tuple field |

**Description:**
`Settings` is `frozen=True` with a `tuple[str, ...]` field for `tool_preview_keys`. The frozen flag only prevents attribute reassignment; it does not validate that the value stored is actually immutable. Passing a list at construction time silently stores a mutable object.

```python
tool_preview_keys: tuple[str, ...] = (
    "command",
    "file_path",
    ...)
```

**Best Practice:**
In a frozen dataclass, raise `TypeError` or `ValueError` inside `__post_init__` for invalid types/values using explicit `isinstance` checks.

**Recommendation:** Add a `__post_init__` method: `if not isinstance(self.tool_preview_keys, tuple): object.__setattr__(self, 'tool_preview_keys', tuple(self.tool_preview_keys))`.

---

#### BUG-040 — `model` Field Not Validated for Empty String on Load

| Field | Detail |
|-------|--------|
| **File** | `textualcode/config.py` |
| **Lines** | 98–101 |
| **Severity** | 🟢 Low |
| **Category** | Type safety — model field not validated for empty string |

**Description:**
In `load()`, `model=str(data.get('model', 'default'))` will produce an empty string `''` if the JSON contains `{"model": ""}`. Downstream code that does `if self._project.model` to decide whether to use the model would silently fall back to the SDK default without indicating that the config is malformed.

```python
model=str(data.get("model", "default")),
```

**Best Practice:**
Replace any `value = raw or default` pattern in config loading with explicit None check and strip: `value = raw.strip() if raw and raw.strip() else default`.

**Recommendation:** Change to `model=str(data.get("model", "default")).strip() or "default"`.

---

### permissions.py

---

#### BUG-041 — `similarity_key` Crashes if `tool_input` Is `None`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 37 |
| **Severity** | 🟡 Medium |
| **Category** | Edge case / IndexError |

**Description:**
`similarity_key` does not defend against `tool_input` itself being `None`, which would cause `AttributeError` on `.get`. While not triggered by current callers, the function is a public module-level helper with no guard.

```python
def similarity_key(tool_name: str, tool_input: dict) -> tuple[str, str]:
    if tool_name == "Bash":
        command = str(tool_input.get("command", "")).strip()
        first = command.split(maxsplit=1)[0] if command else ""
        return ("Bash", first)
```

**Best Practice:**
Always pass a sentinel default to `dict.get()` when you intend to chain attribute access on the result, and add guard clauses at the top of public functions.

**Recommendation:** Add at the top: `if tool_input is None: tool_input = {}`. Also ensure callers type-check before passing.

---

#### BUG-042 — `similarity_key` Too Coarse for Bash — Security Bypass

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 35–39 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug — similarity key too coarse / security bypass |

**Description:**
`similarity_key` for Bash keys only on the first whitespace-delimited token (e.g. `"git"`). If a user approves `git status`, the remembered key `("Bash", "git")` will auto-allow *any* subsequent `git` command — including destructive ones like `git push --force`, `git reset --hard HEAD~50`, or `git clean -fdx`.

```python
first = command.split(maxsplit=1)[0] if command else ""
return ("Bash", first)
```

**Best Practice:**
Replace prefix-string matching with argument-list parsing before approval: split the command into tokens using `shlex.split()`, evaluate policy against the first token (the executable) and each argument separately, and explicitly reject any token that is a shell metacharacter or operator.

**Recommendation:** Include the second token (subcommand) in the similarity key: `parts = command.split(maxsplit=2); key = " ".join(parts[:2])`. Consider using `shlex.split()` for more accurate tokenization.

---

#### BUG-043 — `AUTO_ALLOW_TOOLS` Includes `TodoWrite` (Unexpected Side Effects)

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 13 |
| **Severity** | 🟡 Medium |
| **Category** | Security — overly permissive auto-allow list |

**Description:**
`AUTO_ALLOW_TOOLS` includes `"TodoWrite"`. `TodoWrite` modifies the agent's persistent to-do list and can overwrite or clear existing items. Auto-approving it means the agent can silently manipulate its task list with no user confirmation.

**Best Practice:**
Use `disallowed_tools` to explicitly block every built-in tool that should not run, and implement a `can_use_tool` callback that enforces the same policy at runtime.

**Recommendation:** Remove `"TodoWrite"` from `AUTO_ALLOW_TOOLS` and require explicit user confirmation, or at minimum document the side-effect risk prominently.

---

#### BUG-044 — `_SHELL_OPERATORS` Incomplete; Injection Bypass Possible

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 17 |
| **Severity** | 🟠 High |
| **Category** | Logic bug — incomplete shell-operator list allows command injection bypass |

**Description:**
`_SHELL_OPERATORS` is missing several shell metacharacters: `{` (brace expansion), `$'...'` (ANSI-C quoting), process substitution `<(cmd)`, and `\r` (carriage return can hide injected commands). The blacklist approach is inherently incomplete.

**Best Practice:**
Replace `subprocess.run(shell=True)` or `os.system()` calls that incorporate user input with `subprocess.run([cmd, arg1, arg2, ...], shell=False)` — passing the command and each argument as separate list elements, eliminating the injection surface.

**Recommendation:** Either expand `_SHELL_OPERATORS` to include the missing cases, or switch to `shlex.split()` + allowlist validation rather than blacklist-based metacharacter detection. Add `\r`, `{`, and process substitution patterns to the existing list as an immediate fix.

---

#### BUG-045 — `PermissionPolicy` Accepts Mutable `set` Despite `frozenset` Annotation

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 57 |
| **Severity** | 🟢 Low |
| **Category** | State management — mutable default argument pattern (latent) |

**Description:**
`PermissionPolicy.__init__` stores `self._auto_allow = auto_allow`. If a caller passes a mutable `set` instead of a `frozenset`, that set can be mutated externally after construction, silently changing which tools are auto-allowed at runtime.

**Best Practice:**
Replace any mutable default argument with `None` and add a guard at the top, or freeze/copy the incoming value.

**Recommendation:** In `__init__`, add: `self._auto_allow = frozenset(auto_allow)` to ensure immutability regardless of what the caller passes.

---

#### BUG-046 — `_has_shell_operator` Misleading for Non-Bash Tools

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 49–51 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug — `_has_shell_operator` only checks Bash but accepts any tool_input |

**Description:**
`_has_shell_operator` searches the `"command"` key of `tool_input`. If called with a non-Bash tool's input (which won't have a `"command"` key), `tool_input.get("command", "")` returns `""` and the function returns `False`, potentially giving a false negative to a future caller.

**Best Practice:**
Add guard clauses at the top of every public function. Here: validate that the function is only called with Bash tool input, or document its limitation explicitly.

**Recommendation:** Add a docstring note or a `tool_name` parameter to make intent explicit, and add `assert isinstance(tool_input, dict)` to surface misuse during development.

---

#### BUG-047 — `_remembered` Set Has No Concurrency Protection

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 59–70 |
| **Severity** | 🟢 Low |
| **Category** | Thread / concurrency safety — unprotected shared mutable state |

**Description:**
`self._remembered` is a plain `set` mutated by `remember()` and read by `auto_allow()`. If the SDK calls `_approve_tool` concurrently, the check-then-act sequence across `auto_allow` (read) and `remember` (write) is not atomic.

**Best Practice:**
Wrap every read-modify-write sequence on the shared `set` inside a single `async with asyncio.Lock():` block so no `await` can occur between the check and the mutation.

**Recommendation:** Add `self._remember_lock = asyncio.Lock()` to `__init__`, and use `async with self._remember_lock:` in both `auto_allow` and `remember`.

---

#### BUG-048 — Empty `tool_name` Produces Degenerate Similarity Key

| Field | Detail |
|-------|--------|
| **File** | `textualcode/permissions.py` |
| **Lines** | 28–39 |
| **Severity** | 🟢 Low |
| **Category** | Edge case — empty `tool_name` produces degenerate similarity key |

**Description:**
If `tool_name` is an empty string `""`, `similarity_key` falls through to `return (tool_name, "")` = `("", "")`. A `remember("", {})` call would pollute `_remembered` with a universally-matching key for all non-Bash, unnamed tools.

**Best Practice:**
Add an explicit guard clause at the entry of the function that checks for empty/falsy inputs.

**Recommendation:** Add at the top of `similarity_key`: `if not tool_name: raise ValueError("tool_name must not be empty")`.

---

### renderer.py

---

#### BUG-049 — `_render_assistant` Crashes on `None` or Non-Iterable `message.content`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/renderer.py` |
| **Lines** | 35 |
| **Severity** | 🟡 Medium |
| **Category** | Edge cases not handled |

**Description:**
In `_render_assistant`, the loop iterates over `message.content` without any guard. If `message.content` is `None` or not iterable (e.g. the SDK returns a malformed message), this raises `TypeError` and propagates uncaught out of `render()`.

```python
for block in message.content:
```

**Best Practice:**
Guard every iteration over SDK message content with a None/empty check and an isinstance filter: `for block in (message.content or []):`.

**Recommendation:** Change to:
```python
for block in (message.content or []):
    if isinstance(block, TextBlock):
        ...
```

---

#### BUG-050 — `last_cost` / `last_usage` Are Public Mutable State Managed by Caller

| Field | Detail |
|-------|--------|
| **File** | `textualcode/renderer.py` |
| **Lines** | 24–25 |
| **Severity** | 🟢 Low |
| **Category** | State management bugs |

**Description:**
`last_cost` and `last_usage` are public mutable attributes reset from outside the class (`app.py` resets them between turns). This is fragile shared state that violates single-responsibility and creates a latent race if the exclusivity assumption ever changes.

```python
self.last_cost: float | None = None
self.last_usage: dict | None = None
```

**Best Practice:**
Extract shared mutable state into a dedicated dataclass that owns all mutable fields, then pass it as a dependency to the classes that need it.

**Recommendation:** Add a `reset()` method to `MessageRenderer` that clears `last_cost` and `last_usage`, so the caller's intent is explicit and encapsulated.

---

#### BUG-051 — `last_cost` Not Validated; May Store Non-Float Value

| Field | Detail |
|-------|--------|
| **File** | `textualcode/renderer.py` |
| **Lines** | 31 |
| **Severity** | 🟢 Low |
| **Category** | Type errors or unsafe casts |

**Description:**
`self.last_cost = message.total_cost_usd` stores whatever the SDK returns. If `total_cost_usd` is a string (e.g. `"0.003"`) rather than a float, the downstream `self._stats.add_turn(usage, cost)` will raise `TypeError`.

```python
self.last_cost = message.total_cost_usd
```

**Best Practice:**
Annotate any SDK response field that might be absent as `float | None`, then gate conversion behind an explicit None check or a safe helper.

**Recommendation:** Change to `self.last_cost = float(message.total_cost_usd) if message.total_cost_usd is not None else None` with a `try/except (ValueError, TypeError)`.

---

#### BUG-052 — Unknown `Message` Subtypes Silently Ignored

| Field | Detail |
|-------|--------|
| **File** | `textualcode/renderer.py` |
| **Lines** | 27–32 |
| **Severity** | 🟢 Low |
| **Category** | Edge cases not handled |

**Description:**
`render()` silently ignores any `Message` subtype that is neither `AssistantMessage` nor `ResultMessage`. There is no logging, warning, or fallback rendering, making debugging SDK protocol changes very difficult.

```python
async def render(self, message: Message) -> None:
    if isinstance(message, AssistantMessage):
        await self._render_assistant(message)
    elif isinstance(message, ResultMessage):
        self.last_cost = message.total_cost_usd
        self.last_usage = message.usage
```

**Best Practice:**
In the wildcard/else branch of your isinstance dispatch, add a `logging.warning("Unhandled message type %r: %r", type(message).__name__, message)` call.

**Recommendation:** Add an `else: logging.warning("Unhandled message type: %r", type(message).__name__)` branch.

---

### screens.py

---

#### BUG-053 — `PermissionDialog.on_button_pressed` Deadlocks on Unknown Button ID

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 51–57 |
| **Severity** | 🔴 Critical |
| **Category** | Exception handling / deadlock |

**Description:**
`on_button_pressed` in `PermissionDialog` does `decisions[event.button.id]` with no guard. If `event.button.id` is `None` (buttons without an explicit id in Textual default to None) or any value not in the dict, a `KeyError` is raised. Because the dialog was opened via a Future in `_ask_permission`, the unhandled exception exits the handler without resolving the Future, permanently deadlocking the agent worker.

```python
self.dismiss(decisions[event.button.id])
```

**Best Practice:**
Replace a monolithic `on_button_pressed` method that checks `event.button.id` with separate `@on(Button.Pressed, "#button-id")` decorated methods. For the interim, use `decisions.get(event.button.id)` with an explicit None check.

**Recommendation:** Use `@on` decorators per button, or change to:
```python
decision = decisions.get(event.button.id)
if decision is not None:
    self.dismiss(decision)
```

---

#### BUG-054 — `ModelSelector` Converts `None` Current to String `"None"`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 125 |
| **Severity** | 🟠 High |
| **Category** | Type error / logic bug |

**Description:**
`ModelSelector.__init__` does `self._current = str(current)` where `current` is typed `str | None`. When `current` is `None`, `str(None)` produces the string literal `"None"`. The comparison `str(model["value"]) == self._current` then never matches any real model value, so no radio button is pre-selected even when a model is currently active.

```python
self._current = str(current)
```

**Best Practice:**
Guard every `Optional[str]` value before passing it to a Textual widget. Use `value if value is not None else ""`.

**Recommendation:** Change to `self._current = current if current is not None else ""`.

---

#### BUG-055 — `ModelSelector.compose` Crashes on Missing `"value"` Key

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 132–136, 153 |
| **Severity** | 🟠 High |
| **Category** | Edge case / KeyError |

**Description:**
Multiple accesses to `model["value"]` (not `model.get("value")`) will raise an unhandled `KeyError` if the SDK returns a model dict that lacks the `"value"` key. Line 132 is especially subtle: `model.get("displayName", model["value"])` — the fallback itself raises `KeyError` rather than producing a safe default.

```python
name = model.get("displayName", model["value"])
```

**Best Practice:**
Replace any direct bracket access on nested dicts with chained `.get()` calls using safe fallbacks at every level.

**Recommendation:** Change to `name = model.get("displayName") or model.get("value", "")` to ensure safe access at every level.

---

#### BUG-056 — `PermissionDialog` Title Vulnerable to Rich Markup Injection

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 40 |
| **Severity** | 🟠 High |
| **Category** | Security / markup injection |

**Description:**
`self._tool_name` is interpolated directly into a Rich markup string without escaping: `f"🔐 Allow [b]{self._tool_name}[/b] to run?"`. A tool name containing Rich markup metacharacters (e.g. `evil[/b][red]`) would inject formatting tags and could corrupt the display.

```python
yield Static(f"🔐 Allow [b]{self._tool_name}[/b] to run?", id="dlg-title")
```

**Best Practice:**
When displaying any user-supplied or externally-sourced string in a `Static` (or `Label`) widget, either construct it with `Static(user_input, markup=False)` or call `from textual.markup import escape` and pass `escape(user_input)` when you still need surrounding markup.

**Recommendation:** Change to `f"🔐 Allow [b]{escape(self._tool_name)}[/b] to run?"` (import `escape` from `textual.markup`).

---

#### BUG-057 — `PermissionDialog` Hint Static Vulnerable to Rich Markup Injection

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 42–45 |
| **Severity** | 🟠 High |
| **Category** | Security / markup injection |

**Description:**
`self._similar_label` (produced from the tool name and raw command prefix) is also interpolated into a Rich markup string without escaping. A crafted tool name or Bash command prefix containing Rich markup characters corrupts the rendering.

```python
yield Static(f'[dim]"Approve similar" allows {self._similar_label} this session.[/dim]', id="dlg-hint")
```

**Best Practice:**
Wrap every untrusted or dynamically constructed label string with `textual.markup.escape()` before passing it to any Textual widget that renders markup.

**Recommendation:** Change to `f'[dim]"Approve similar" allows {escape(self._similar_label)} this session.[/dim]'`.

---

#### BUG-058 — `ModelSelector.action_save` No Upper-Bound Check on Index

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 148–153 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug / index out of range |

**Description:**
`action_save` in `ModelSelector` accesses `self._models[index]` after checking only `index < 0`. There is no upper-bound check. If `pressed_index` somehow exceeds `len(self._models)-1`, an `IndexError` is raised with no handler, crashing the worker.

```python
self.dismiss(str(self._models[index]["value"]))
```

**Best Practice:**
Before accessing a list by index, use an explicit bounds guard: `if 0 <= index < len(my_list): value = my_list[index]`.

**Recommendation:** Change to `if 0 <= index < len(self._models): self.dismiss(...) else: return`.

---

#### BUG-059 — `ToolSelector.on_button_pressed` Silently Cancels on Unrecognised Buttons

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 100–104 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug / silent wrong behaviour |

**Description:**
`ToolSelector.on_button_pressed` dismisses with `None` for any button id that is not `"save"`, including `None` (id-less buttons) and any typo'd or future ids. This means a `Save` button with a wrong id silently cancels instead of saving.

```python
else:
    self.dismiss(None)
```

**Best Practice:**
Replace a monolithic `on_button_pressed` with separate `@on(Button.Pressed, "#button-id")` decorated methods, or add a guard to only dismiss on known button ids.

**Recommendation:** Replace with `@on` decorators, or add `elif event.button.id is not None: logging.warning("Unknown button id in ToolSelector: %r", event.button.id)` before the `else` branch.

---

#### BUG-060 — `ModelSelector.compose` RadioButton Label Vulnerable to Markup Injection

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 134–135 |
| **Severity** | 🟡 Medium |
| **Category** | Security / markup injection |

**Description:**
In `ModelSelector.compose`, the RadioButton label is built by interpolating `name` and `desc` from the SDK's model dict directly into an f-string that Textual renders with Rich markup. Neither field is escaped, so a tampered server response with Rich markup in `displayName` or `description` would corrupt the radio list rendering.

```python
yield RadioButton(
    f"{name} — {desc}" if desc else str(name),
    value=str(model["value"]) == self._current,
)
```

**Best Practice:**
Wrap every untrusted or dynamically constructed label string with `textual.markup.escape()` before passing it to RadioButton.

**Recommendation:** Change to `f"{escape(str(name))} — {escape(str(desc))}" if desc else escape(str(name))`.

---

#### BUG-061 — `ModelSelector` BINDINGS Action Name/Label Mismatch

| Field | Detail |
|-------|--------|
| **File** | `textualcode/screens.py` |
| **Lines** | 117–119 |
| **Severity** | 🟢 Low |
| **Category** | Textual framework misuse / UX inconsistency |

**Description:**
`ModelSelector` BINDINGS maps the key `"s"` to action `"save"` with the display label `"Select"`. The action name is `action_save` but the label shown in the footer says `"Select"`. This is confusing to developers maintaining the code.

```python
BINDINGS = [
    ("s", "save", "Select"),
    ("escape", "cancel", "Cancel"),
]
```

**Best Practice:**
Keep action names and labels deliberately separate: the action field must exactly match the `action_` method name, while the description field should be a short, sentence-cased, user-facing label. Never try to make them identical or derive one from the other.

**Recommendation:** The label `"Select"` is acceptable user-facing text. Document with a comment that the action is `action_save` and the label intentionally differs from the action name.

---

### stats.py

---

#### BUG-062 — `if cost:` Skips Legitimate Zero-Cost Turns

| Field | Detail |
|-------|--------|
| **File** | `textualcode/stats.py` |
| **Lines** | 36–37 |
| **Severity** | 🟡 Medium |
| **Category** | Logic bug / edge case not handled |

**Description:**
The `if cost:` guard silently skips accumulating a cost of exactly `0.0`. A turn may genuinely return `total_cost_usd = 0.0` (e.g. a cached/free response). Because `bool(0.0)` is `False` in Python, that turn's cost is dropped and `cost_usd` is never incremented.

```python
if cost:
    self.cost_usd += cost
```

**Best Practice:**
PEP 8 explicitly states: "Beware of writing `if x` when you really mean `if x is not None`". Replace bare truthiness checks on numeric variables with explicit None guards.

**Recommendation:** Change to `if cost is not None: self.cost_usd += cost`.

---

#### BUG-063 — `turns` Counter Incremented Even for `(None, None)` Input

| Field | Detail |
|-------|--------|
| **File** | `textualcode/stats.py` |
| **Lines** | 29–37 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug / turns counter incorrectly incremented |

**Description:**
`self.turns += 1` is executed unconditionally on every `add_turn` call, even when `usage` is `None` and `cost` is `None`. Any future caller that passes `(None, None)` will silently increment `turns` while contributing zero to every other counter, causing a misleading cache-hit-rate calculation.

```python
def add_turn(self, usage: dict | None, cost: float | None) -> None:
    self.turns += 1
    if usage:
        ...
```

**Best Practice:**
The `turns` increment should be conditional on meaningful data, or documented explicitly. Use `field(init=False, default=0)` in a dataclass and validate in `__post_init__`.

**Recommendation:** Add a guard: `if usage is not None or cost is not None: self.turns += 1`.

---

#### BUG-064 — `_int` Helper Silently Returns `0` on All Failures

| Field | Detail |
|-------|--------|
| **File** | `textualcode/stats.py` |
| **Lines** | 13–17 |
| **Severity** | 🟢 Low |
| **Category** | Type safety / silent data loss |

**Description:**
The `_int` helper silently converts any non-numeric or `None` token count to `0` without any logging or warning. If the SDK changes key names, all token fields will silently stay at `0` and the cache-hit-rate will be calculated as `0.0` with no signal that data is missing.

```python
def _int(value) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
```

**Best Practice:**
Use a unique `MISSING = object()` sentinel checked with `is`, not `==`, to distinguish "caller passed 0" from "no value was provided".

**Recommendation:** Add `if value is None: logging.debug("_int received None; check SDK key names")` before the `try` block to surface key-name drift during development.

---

#### BUG-065 — `if usage:` Skips Processing on Empty Dict

| Field | Detail |
|-------|--------|
| **File** | `textualcode/stats.py` |
| **Lines** | 31 |
| **Severity** | 🟢 Low |
| **Category** | Edge case not handled / unexpected types |

**Description:**
`if usage:` evaluates to `False` for an empty dict `{}`. An empty dict is a valid (though unusual) return from the SDK. The guard should be `if usage is not None:` so that an empty dict still goes through `_int` (all fields would be 0) and does not silently skip the block.

```python
if usage:
    self.input_tokens += _int(usage.get("input_tokens"))
```

**Best Practice:**
Replace bare falsy checks on dict values with explicit None checks when an empty dict is semantically different from a missing value.

**Recommendation:** Change to `if usage is not None:`.

---

#### BUG-066 — `total_input` Denominator May Be Inconsistent with API Semantics

| Field | Detail |
|-------|--------|
| **File** | `textualcode/stats.py` |
| **Lines** | 39–41 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug / total_input definition may diverge from API semantics |

**Description:**
`total_input` is defined as `input_tokens + cache_creation_tokens + cache_read_tokens`. The field `input_tokens` is documented as 'uncached (post-breakpoint) input'. Including `cache_creation_tokens` in the denominator may inflate it and deflate the reported `cache_hit_rate` depending on Anthropic billing semantics.

```python
@property
def total_input(self) -> int:
    return self.input_tokens + self.cache_creation_tokens + self.cache_read_tokens
```

**Best Practice:**
Always read token counts directly from the raw Anthropic SDK response object (`response.usage`). For cache hit rate, use `cache_read_input_tokens / (cache_read_input_tokens + cache_creation_input_tokens)` as both numerator and denominator.

**Recommendation:** Verify against Anthropic's billing documentation. The `cache_hit_rate` denominator should likely be `cache_creation_tokens + cache_read_tokens` only (i.e. cacheable tokens), not `total_input`.

---

### widgets.py

---

#### BUG-067 — `_append` Calls `scroll_end` Before Layout Is Complete

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 27–29 |
| **Severity** | 🟡 Medium |
| **Category** | Async/await issue |

**Description:**
In `ConversationView._append`, `self.scroll_end(animate=False)` is called immediately after `await self.mount(widget)`. `mount` only schedules the widget to be composed and attached — the DOM layout and rendering are not complete by the time the next line runs. `scroll_end` therefore measures stale geometry and will frequently fail to scroll to the new content.

```python
async def _append(self, widget: Widget) -> None:
    await self.mount(widget)
    self.scroll_end(animate=False)
```

**Best Practice:**
In `on_mount`, replace a direct `self.scroll_end()` call with `self.call_after_refresh(self.scroll_end, animate=False)`. This defers the scroll until after Textual has completed its layout pass.

**Recommendation:** Change to `self.call_after_refresh(self.scroll_end, animate=False)`.

---

#### BUG-068 — `_short` Docstring Has Incorrect Example Value

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 33 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug / incorrect comment |

**Description:**
The docstring example for `_short` shows `1_703_00 -> '170.3k'` which parses as `170300`, not `1703000` as the formatting implies. This misleads future maintainers about the intended threshold logic.

```python
def _short(n: int) -> str:
    """Compact token count: 1_703_00 -> '170.3k', 1_000_000 -> '1.0m'."""
```

**Best Practice:**
PEP 257 is the authoritative standard: docstrings must be updated whenever the code changes and should never contain inaccurate examples.

**Recommendation:** Change the docstring example to `1_703_000 -> '1.7m'` or provide a correct value that demonstrates the `'k'` threshold.

---

#### BUG-069 — Progress Bar Off-by-One When `pct > 100`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 98 |
| **Severity** | 🟡 Medium |
| **Category** | Off-by-one / edge case |

**Description:**
`filled = round(pct / 100 * self._BAR_CELLS)` can produce `filled` exceeding `_BAR_CELLS` when `pct > 100` (a corrupted context dict), causing `self._BAR_CELLS - filled` to become negative. In Python, `'░' * negative_number` returns `""` silently.

```python
filled = round(pct / 100 * self._BAR_CELLS)
bar = (
    f"[{fill}]" + "█" * filled + "[/]"
    + "[dim]" + "░" * (self._BAR_CELLS - filled) + "[/dim]"
)
```

**Best Practice:**
Guard every string-repeat expression in a progress bar with both a lower and upper clamp: `filled = min(max(0, int(bar_width * current / total)), bar_width)`.

**Recommendation:** Change to `filled = min(max(0, round(pct / 100 * self._BAR_CELLS)), self._BAR_CELLS)`.

---

#### BUG-070 — `float()` on `context.get("percentage")` Can Raise on Non-Numeric Value

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 95 |
| **Severity** | 🟢 Low |
| **Category** | Type error / unsafe cast |

**Description:**
`pct = float(context.get('percentage', 0.0))` does not guard against non-numeric values. If the context dict contains `'percentage': 'N/A'` or any non-numeric string, `float()` raises `ValueError`, crashing `_add_context`.

```python
pct = float(context.get("percentage", 0.0))
```

**Best Practice:**
Define a small helper: `def safe_float(value, default=None): try: return float(str(value).strip()) except (ValueError, TypeError): return default`.

**Recommendation:** Wrap in a `try/except`: `try: pct = float(context.get("percentage", 0.0)) except (ValueError, TypeError): pct = 0.0`.

---

#### BUG-071 — `int(cat.get("tokens", 0))` Can Raise on Non-Numeric String

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 112 |
| **Severity** | 🟢 Low |
| **Category** | Type error / unsafe cast |

**Description:**
`tokens = _short(int(cat.get('tokens', 0)))` will raise `ValueError` if `cat['tokens']` is a non-integer string (e.g. `'unknown'`). The `int()` call has no try/except, and the exception would propagate up through `show()` uncaught.

```python
tokens = _short(int(cat.get("tokens", 0)))
```

**Best Practice:**
Wrap `int()` in a `try/except` block that catches both `ValueError` and `TypeError`.

**Recommendation:** Change to: `try: tokens = _short(int(cat.get("tokens", 0))) except (ValueError, TypeError): tokens = "?"`.

---

#### BUG-072 — `tool_preview` Falsy Check Skips Valid Zero/Empty Values

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 126–130 |
| **Severity** | 🟡 Medium |
| **Category** | Edge case not handled |

**Description:**
In `tool_preview`, the truthiness check `if value:` will skip a key whose value is `0`, `False`, or an empty list even though these are valid and potentially meaningful tool inputs. A tool called with `{"path": ""}` or `{"count": 0}` would produce no preview.

```python
for key in keys:
    value = data.get(key)
    if value:
        line = str(value).splitlines()[0]
        return f"· {line[:60]}" + ("…" if len(line) > 60 else "")
```

**Best Practice:**
Replace bare `if value:` or `if not value:` guards with explicit `is None` checks when the variable could legitimately hold `0`, `""`, `[]`, or another falsy-but-valid value.

**Recommendation:** Change to `if value is not None:`.

---

#### BUG-073 — `_format_input` Truncates Without Considering Multi-Byte Unicode

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 133–140 |
| **Severity** | 🟢 Low |
| **Category** | Logic bug |

**Description:**
`_format_input` truncates by character count (`len(text) > limit`) after JSON serialization. The appended `'\n… (truncated)'` itself adds 16 characters on top of `limit`, so the actual output can exceed the intended limit. For multi-byte Unicode characters, `len(text)` counts code points, not bytes.

```python
if len(text) > limit:
    text = text[:limit] + "\n… (truncated)"
```

**Best Practice:**
When truncating a Python string to a byte limit, use `s.encode('utf-8')[:max_bytes].decode('utf-8', errors='ignore')`. For display truncation, `s[:N]` (code-point slicing) is usually sufficient in Textual.

**Recommendation:** Cosmetic fix: note that the annotation `… (truncated)` adds to the output length, and document this in a comment if the `limit` is intended to be an approximate bound rather than a strict cap.

---

#### BUG-074 — `StatsPanel.show` Displays `0%` Cache Hit at Startup

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 64 |
| **Severity** | 🟢 Low |
| **Category** | Edge case not handled |

**Description:**
`StatsPanel.show` calls `stats.cache_hit_rate` before any turn completes. At startup, `rate` is `0.0`, `_rate_color` returns `'red'`, and the panel shows `0%` cache hit in red, which may confuse users who have not yet sent any message.

```python
rate = stats.cache_hit_rate
color = self._rate_color(rate)
```

**Best Practice:**
In any `render`, `render_line`, or watch method that divides by a reactive or layout-derived value, add an explicit guard before the division and handle the "no data yet" case distinctly.

**Recommendation:** Add a check `if stats.turns == 0: display "—"` for cache hit rate instead of `0%`.

---

#### BUG-075 — `Style(meta={"@click": ...})` Uses Undocumented Textual Mechanism

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 71 |
| **Severity** | 🟢 Low |
| **Category** | Textual framework misuse |

**Description:**
`Text(model, style=Style(meta={'@click': 'app.open_model'}))` uses a Rich `Style` with a `meta` dict to embed a Textual action link. This is an undocumented internal mechanism. If Textual changes its internal event routing for meta-style clicks, this will silently stop working.

```python
model_cell = Text(model, style=Style(meta={"@click": "app.open_model"}))
```

**Best Practice:**
Always qualify `@click` action strings with an explicit namespace and use the documented `[@click=app.my_action]text[/]` markup pattern where possible.

**Recommendation:** Migrate to the documented markup approach: `Text.from_markup(f"[@click=app.open_model]{escape(model)}[/]")` to use the officially supported clickable link pattern.

---

#### BUG-076 — `ToolCard` Title May Be Corrupted by Rich Markup in `block.name`

| Field | Detail |
|-------|--------|
| **File** | `textualcode/widgets.py` |
| **Lines** | 154 |
| **Severity** | 🟢 Low |
| **Category** | Edge case not handled |

**Description:**
In `ToolCard.__init__`, `block.name` is used directly in an f-string to form a `Collapsible` title. If `block.name` contains Rich markup characters (e.g. `[`, `]`) the title string may trigger a `MarkupError` or garbled display.

```python
title = f"🔧 {block.name}  {tool_preview(block, preview_keys)}".rstrip()
super().__init__(
    Markdown(f"```json\n{body}\n```"),
    title=title,
```

**Best Practice:**
Always wrap dynamic or user-supplied title strings with `textual.markup.escape()` before passing them to `Collapsible`.

**Recommendation:** Change to `title = f"🔧 {escape(block.name)}  {escape(tool_preview(block, preview_keys))}".rstrip()`.

---

## Quick Wins

The following bugs can be fixed in under five minutes each with minimal risk of regression:

| Bug | File | Fix |
|-----|------|-----|
| BUG-004 | agent.py:104 | Wrap `disconnect()` in `try/finally` to always clear `self._client` |
| BUG-010 | agent.py:91 | Move `self.model = model` to after the SDK call |
| BUG-008 | agent.py:72 | Return `list(self._models)` instead of `self._models` |
| BUG-028 | commands.py:35 | Add `if not parts: raise UnknownCommand("")` guard |
| BUG-032 | commands.py:18 | Change `super().__init__(name)` to `super().__init__(f"Unknown command: /{name}")` |
| BUG-023 | app.py:193 | Move connectivity check before `add_markdown` |
| BUG-053 | screens.py:57 | Use `decisions.get(event.button.id)` with None check instead of direct dict access |
| BUG-056 | screens.py:40 | Wrap `self._tool_name` with `escape()` in the Static title |
| BUG-057 | screens.py:42 | Wrap `self._similar_label` with `escape()` in the hint Static |
| BUG-054 | screens.py:125 | Change `str(current)` to `current if current is not None else ""` |
| BUG-062 | stats.py:36 | Change `if cost:` to `if cost is not None:` |
| BUG-065 | stats.py:31 | Change `if usage:` to `if usage is not None:` |
| BUG-049 | renderer.py:35 | Change `for block in message.content:` to `for block in (message.content or []):` |
| BUG-067 | widgets.py:29 | Change `self.scroll_end(animate=False)` to `self.call_after_refresh(self.scroll_end, animate=False)` |
| BUG-069 | widgets.py:98 | Clamp `filled` with `min(max(0, ...), self._BAR_CELLS)` |
| BUG-033 | config.py:89 | Change `return value` to `return list(value)` in `_read_tools` |
| BUG-040 | config.py:98 | Change `str(data.get("model", "default"))` to `str(data.get("model", "default")).strip() or "default"` |
| BUG-072 | widgets.py:127 | Change `if value:` to `if value is not None:` in `tool_preview` |

---

## Refactoring Suggestions

### 1. Consolidate Agent Lifecycle Into an Async Context Manager

**Affected Files:** `agent.py`

`AgentSession.connect`, `aclose`, `reconnect`, and the associated state management (BUG-002, BUG-003, BUG-004, BUG-005, BUG-011) all stem from the absence of a principled ownership model for the `ClaudeSDKClient`. Refactor `AgentSession` to implement `__aenter__`/`__aexit__` (or use `contextlib.asynccontextmanager`) so that all resource acquisition is guarded by `try/finally` and partial initialization is impossible. The `reconnect` method can then be implemented as `await self.__aexit__(...)` followed by `await self.__aenter__()` with rollback on failure.

### 2. Replace Dict-Dispatch Permission Logic with `@on` Decorators

**Affected Files:** `screens.py`, `app.py`

The `decisions[event.button.id]` pattern in `PermissionDialog` (BUG-053, BUG-059) and similar patterns throughout the screens module are fragile. Migrate all button handlers to Textual's `@on(Button.Pressed, "#id")` decorator pattern. This eliminates `KeyError` risks, `None`-id risks, and unintended button captures in a single structural change. The `@on` approach also makes it trivial to see which handler fires for which button during code review.

### 3. Centralize Markup Escaping for SDK-Sourced Strings

**Affected Files:** `screens.py`, `widgets.py`

Multiple markup injection bugs (BUG-056, BUG-057, BUG-060, BUG-076) arise because SDK-sourced strings (tool names, model display names, command previews) are directly interpolated into Rich markup templates. Create a thin utility module `textualcode/markup_utils.py` that wraps `textual.markup.escape` and exposes helper functions like `safe_title(s: str) -> str` and `safe_inline(s: str) -> str`. All rendering code should import from this module rather than calling `escape` ad hoc, creating a single auditable location for markup safety.

### 4. Extract `PermissionPolicy` Into a Layered Strategy

**Affected Files:** `permissions.py`, `agent.py`

The current permission model combines auto-allow logic, shell-operator blacklisting, and remember-by-similarity into a single class. The security issues (BUG-006, BUG-042, BUG-043, BUG-044) suggest this needs a layered "deny first" architecture:

1. **Layer 0 — Hard deny:** Unconditionally block specific destructive tools.
2. **Layer 1 — Auto-allow:** Allow known-safe read-only tools without prompting.
3. **Layer 2 — Remember:** Check whether the user has previously approved a similar call.
4. **Layer 3 — Prompt:** Show the `PermissionDialog` for all unresolved cases.
5. **Layer 4 — Default deny:** Deny anything not resolved by layers 0–3.

Each layer should be a separate, testable function or class. This architecture also removes the need for `AgentSession._approve_tool` to have a special `None` handler fallback (BUG-006).

### 5. Replace `UsageStats` Falsy Guards with `is not None` Throughout

**Affected Files:** `stats.py`, `renderer.py`

The pattern of using `if value:` to check for `None` on numeric types appears in `stats.py` in multiple places (BUG-062, BUG-063, BUG-064, BUG-065, BUG-066). This should be resolved systematically: run a linter rule (e.g. Ruff's `SIM201`/`SIM203` for `is None` comparisons) across the entire `stats.py` file and fix all occurrences at once. Additionally, annotate all fields that can be `None` as `float | None` or `int | None` and enable `mypy --strict` on this module so the type checker enforces `is not None` guards going forward.

### 6. Add Integration Tests for Async Generator Lifecycle

**Affected Files:** `agent.py`, `app.py`

BUG-001, BUG-007, BUG-016, and BUG-025 all relate to the lifecycle of the `send()` async generator under cancellation, concurrent access, and partial iteration. These are difficult to catch in unit tests but straightforward with `pytest-asyncio` integration tests that:
- Verify that cancelling a worker mid-iteration calls `aclose()` on the generator.
- Verify that concurrent `send()` calls raise or serialize correctly.
- Verify that the `finally` block in `send_to_agent` does not mask `CancelledError`.
