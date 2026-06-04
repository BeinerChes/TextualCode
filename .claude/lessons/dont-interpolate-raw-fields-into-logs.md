# dont-interpolate-raw-fields-into-logs

Never interpolate raw user/model-controlled fields (task IDs, commands, paths) directly into logs or markup; always repr() or escape to prevent log-injection (CWE-117) and accidental markup rendering.

_Category: Security_
