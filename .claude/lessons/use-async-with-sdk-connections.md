# use-async-with-sdk-connections

Always open Claude SDK ClaudeSDKClient and resource connections via async with + receive_response() idiom, not manual connect/try-finally/disconnect, to ensure cleanup and match canonical SDK patterns.

_Category: Idiom_
