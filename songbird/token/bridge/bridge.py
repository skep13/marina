#!/usr/bin/env python3
# ====================================================================
#  Songbird approval-token bridge.
#
#  Sits between Songbird (the model) and the shell. When the model wants
#  to run something it calls run_action(command). Unless the command is
#  in the vetted ALLOWLIST, the bridge sends the EXACT command to the
#  physical token, which shows it and waits for a button press. The press
#  returns an HMAC bound to id|nonce|command, so the signature commits to
#  the exact command the human saw - the model cannot show one thing and
#  run another.
#
#  Transport is TLS, verified against the broker's cert (certs/broker.crt).
#
#  Run it UNPRIVILEGED (see songbird-bridge.service), ideally on the
#  isolated Kali box so approved commands execute there, not next to the
#  model on lab3.
#
#  Deps:  pip install paho-mqtt
#  Test:  python3 bridge.py "echo hello"
# ====================================================================
import os
import sys
import ssl
import json
import time
import uuid
import hmac
import hashlib
import secrets
import threading
import subprocess

import paho.mqtt.client as mqtt

import config as C

_secret = bytes.fromhex(C.SECRET_HEX)
_pending = {}            # id -> {"nonce", "cmd", "event", "approved"}
_lock = threading.Lock()

# allow LAN testing before the Funnel is up, without editing config
_BROKER = os.environ.get("MQTT_BROKER_OVERRIDE", C.MQTT_BROKER)
_PORT = int(os.environ.get("MQTT_PORT_OVERRIDE", C.MQTT_PORT))


def _sign(rid, nonce, command):
    return hmac.new(_secret, f"{rid}|{nonce}|{command}".encode(),
                    hashlib.sha256).hexdigest()


def _on_message(client, userdata, m):
    try:
        r = json.loads(m.payload)
    except Exception:
        return
    rid = r.get("id")
    with _lock:
        slot = _pending.get(rid)
    if not slot or r.get("nonce") != slot["nonce"]:
        return                                   # unknown / stale
    approved = False
    if r.get("approved") and r.get("token"):
        expected = _sign(rid, slot["nonce"], slot["cmd"])
        approved = hmac.compare_digest(expected, r["token"])
    slot["approved"] = approved
    slot["event"].set()


def _tls_context():
    ctx = ssl.create_default_context(cafile=C.BROKER_CERT)
    # We connect by the Funnel DNS name in production (cert CN matches) and
    # by LAN IP in testing (no name match) - either way the cert chain is
    # verified, so a MITM would need the broker's private key.
    ctx.check_hostname = False
    return ctx


def _make_client():
    c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2,
                    client_id=f"bridge-{uuid.uuid4().hex[:8]}")
    if C.MQTT_USER:
        c.username_pw_set(C.MQTT_USER, C.MQTT_PASS)
    if C.MQTT_TLS:
        c.tls_set_context(_tls_context())
    c.on_message = _on_message
    c.connect(_BROKER, _PORT, keepalive=30)
    c.subscribe(C.RESP_TOPIC)
    c.loop_start()
    return c


_client = None


def _client_once():
    global _client
    if _client is None:
        _client = _make_client()
    return _client


def request_approval(command: str, timeout: float = None) -> bool:
    """Ask the physical device to approve THIS command. True only on a valid press."""
    timeout = C.APPROVE_TIMEOUT_S if timeout is None else timeout
    c = _client_once()
    rid = uuid.uuid4().hex[:12]
    nonce = secrets.token_hex(8)
    ev = threading.Event()
    with _lock:
        _pending[rid] = {"nonce": nonce, "cmd": command, "event": ev, "approved": False}
    c.publish(C.REQ_TOPIC, json.dumps({"id": rid, "nonce": nonce, "cmd": command}))
    ev.wait(timeout)
    with _lock:
        slot = _pending.pop(rid, None)
    return bool(slot and slot["approved"])


def run_action(command: str) -> dict:
    """Entry point the model's tool call lands on. Gated unless allowlisted."""
    if command in C.ALLOWLIST:
        return _execute(command, gated=False)
    if request_approval(command):
        return _execute(command, gated=True)
    return {"ok": False, "approved": False, "error": "denied or timed out at the token device"}


def _execute(command: str, gated: bool) -> dict:
    try:
        p = subprocess.run(command, shell=True, capture_output=True,
                           text=True, timeout=600)
        return {"ok": p.returncode == 0, "approved": gated, "code": p.returncode,
                "stdout": p.stdout[-8000:], "stderr": p.stderr[-4000:]}
    except subprocess.TimeoutExpired:
        return {"ok": False, "approved": gated, "error": "command timed out"}


# ---- tool definition to register with Songbird's tool-calling harness ----
TOOL_SPEC = {
    "type": "function",
    "function": {
        "name": "run_action",
        "description": "Run a shell command on the operator host. Anything not "
                       "pre-approved requires a physical button press on the "
                       "operator's approval token, which displays the exact "
                       "command. There is no separate label - the operator sees "
                       "and signs the command itself.",
        "parameters": {
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "exact command to run"},
            },
            "required": ["command"],
        },
    },
}


def handle_tool_call(name, args):
    if name == "run_action":
        return run_action(args["command"])
    raise ValueError(f"unknown tool: {name}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "echo hello from songbird-token"
    print(f"requesting approval for: {cmd!r}", flush=True)
    print(json.dumps(run_action(cmd), indent=2), flush=True)
    sys.stdout.flush()
    os._exit(0)
