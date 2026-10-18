#!/usr/bin/env python3
# Long-running entrypoint for the systemd service.
#
# This is the integration point: wire Songbird's tool-calling loop here so
# that when the model emits a `run_action` tool call, you dispatch it to
# bridge.handle_tool_call(name, args) and return the result to the model.
#
# The skeleton below keeps the MQTT connection warm and exposes the handler.
# Replace the `while True: sleep` with your actual model loop.
import time
import bridge   # noqa: F401  (imports connect lazily on first request)


def dispatch(tool_name, tool_args):
    """Call this from Songbird's tool loop."""
    return bridge.handle_tool_call(tool_name, tool_args)


if __name__ == "__main__":
    print("songbird-bridge runner up; waiting for tool calls to dispatch()", flush=True)
    while True:
        time.sleep(3600)
