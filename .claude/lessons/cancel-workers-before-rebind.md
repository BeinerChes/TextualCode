# cancel-workers-before-rebind

Cancel old worker groups *before* creating and binding new ones during reconnect/restart, not after; prevents old workers from reading a torn-down resource and queuing stale messages into the new pump.

_Category: Threading_
