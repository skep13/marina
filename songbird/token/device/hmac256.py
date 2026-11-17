# Minimal HMAC-SHA256 for MicroPython (no hmac module on-device).
import hashlib

_BLOCK = 64


def hmac_sha256(key, msg):
    if isinstance(key, str):
        key = key.encode()
    if isinstance(msg, str):
        msg = msg.encode()
    if len(key) > _BLOCK:
        key = hashlib.sha256(key).digest()
    key = key + b"\x00" * (_BLOCK - len(key))
    o_key = bytes(b ^ 0x5C for b in key)
    i_key = bytes(b ^ 0x36 for b in key)
    inner = hashlib.sha256(i_key + msg).digest()
    return hashlib.sha256(o_key + inner).digest()


def hexdigest(key, msg):
    return "".join("{:02x}".format(b) for b in hmac_sha256(key, msg))
