# Override Textual `_on_*` handlers with `event.prevent_default()`, not `event.stop()`

## Rule
When you override a private framework handler like `_on_paste`/`_on_key` on a
Textual widget subclass, call `event.prevent_default()` to suppress the base
class behavior — `event.stop()` does NOT do this.

## Why
`MessagePump._get_dispatch_methods` walks the **entire MRO** and dispatches the
event to the `_on_<event>` defined on *every* class. So `Subclass._on_paste`
**and** the inherited `Input._on_paste` both run for a single event. The
dispatch loop only breaks early when `message._no_default_action` is set, which
is what `event.prevent_default()` does. `event.stop()` only sets
`_stop_propagation`, which controls **bubbling to parent widgets** — it has no
effect on sibling handlers along the same widget's MRO.

## Symptom that exposed it
Ctrl+V (bracketed paste) of a file path inserted the path **twice**: the
subclass handler inserted the cleaned path, then the framework also ran
`Input._on_paste`, inserting it again. `event.stop()` looked like it should
prevent this but didn't.

## Pattern
```python
def _on_paste(self, event: events.Paste) -> None:
    if handled_specially(event):
        do_custom_thing()
        event.prevent_default()  # suppress base Input._on_paste
        event.stop()             # (optional) also stop bubbling
        return
    # else: do nothing, let the base handler run via MRO dispatch —
    # do NOT call super()._on_paste(event) (that runs it twice).
```

## Anti-pattern
- Relying on `event.stop()` to skip the base handler.
- Calling `super()._on_paste(event)` for the fall-through case — the framework
  already calls it via the MRO, so you get a double action.
- Misattributing the duplicate to `action_paste`: `Input` has no `ctrl+v`
  binding, so `action_paste` never fires on Ctrl+V. A no-op `action_paste`
  override is dead code, not a fix.
