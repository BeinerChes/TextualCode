# offload-blocking-io-from-event-loop

Never open/read/write files synchronously inside an async event-loop thread; use async file I/O or offload to thread pool via asyncio.to_thread() to prevent event-loop starvation.

_Category: Performance_
