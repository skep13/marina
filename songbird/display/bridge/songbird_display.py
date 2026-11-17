#!/usr/bin/env python3
# ====================================================================
#  Songbird display publisher + tool.
#
#  Gives Songbird a physical screen. Register `show_on_display` as a tool
#  in Songbird's harness; when the model calls it, the text appears on the
#  OLED. Output only - nothing executes.
#
#  Deps:  pip install paho-mqtt
#  Test:  python3 songbird_display.py "hello from songbird" "STATUS"
# ====================================================================
import os
import sys
import ssl
import json
import uuid

import paho.mqtt.client as mqtt

# --- broker (same ct102 broker; override host/port via env for LAN test) ---
BROKER = os.environ.get("MQTT_BROKER", "homelab.tail35b6c6.ts.net")
PORT = int(os.environ.get("MQTT_PORT", "10000"))
USER = os.environ.get("MQTT_USER", "token-bridge")
PW = os.environ.get("MQTT_PASS", "change-me")
CERT = os.environ.get("BROKER_CERT",
                      os.path.join(os.path.dirname(__file__), "..", "device", "broker.crt"))
TOPIC = "songbird/display"


def _client():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"songbird-disp-{uuid.uuid4().hex[:8]}")
    c.username_pw_set(USER, PW)
    ctx = ssl.create_default_context(cafile=CERT)
    ctx.check_hostname = False
    c.tls_set_context(ctx)
    c.connect(BROKER, PORT, 30)
    return c


def show_on_display(text: str, title: str = "SONGBIRD") -> dict:
    """Show a short message on Songbird's physical OLED. Output only."""
    c = _client()
    c.loop_start()
    c.publish(TOPIC, json.dumps({"title": title[:21], "text": text}), qos=1)
    import time
    time.sleep(0.4)
    c.loop_stop()
    c.disconnect()
    return {"ok": True, "shown": text[:200]}


TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "show_on_display",
        "description": "Display a short message on Songbird's physical OLED screen. "
                       "Use for status, what you're working on, alerts, or a note to "
                       "the operator. Display only - it does not run anything.",
        "parameters": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "the message to show (wraps/scrolls)"},
                "title": {"type": "string", "description": "short header in the top strip"},
            },
            "required": ["text"],
        },
    },
}


def handle_tool_call(name, args):
    if name == "show_on_display":
        return show_on_display(args["text"], args.get("title", "SONGBIRD"))
    raise ValueError(f"unknown tool: {name}")


if __name__ == "__main__":
    text = sys.argv[1] if len(sys.argv) > 1 else "hello from Songbird"
    title = sys.argv[2] if len(sys.argv) > 2 else "SONGBIRD"
    print(show_on_display(text, title))
