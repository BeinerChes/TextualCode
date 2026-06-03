# narrow-exception-handlers-with-care

When narrowing a blanket except: pass, verify the surrounding framework won't crash (e.g., exit_on_error=True) on unforeseen exceptions; add safety handling to surface unexpected errors instead of swallowing them silently.

_Category: Error Handling_
