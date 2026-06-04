# sdk-control-protocol-no-state-readback

Do not assume the Claude Agent SDK's control protocol carries active state in responses; set_permission_mode() confirms success/error only, so gate your behavior on inputs you control (model version, user choice) rather than SDK introspection.

_Category: SDK_
