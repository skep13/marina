#!/usr/bin/env python3
"""Unlock the desktop when the enrolled YubiKey is plugged in.
Runs as root from udev. Proves the key through PAM (pam_u2f, no touch) before
asking logind to unlock, so only the enrolled key works."""
import ctypes, ctypes.util, subprocess, sys, time

USER = sys.argv[1] if len(sys.argv) > 1 else "friereon"
libpam = ctypes.CDLL(ctypes.util.find_library("pam"))

class Msg(ctypes.Structure): _fields_ = [("style", ctypes.c_int), ("msg", ctypes.c_char_p)]
class Resp(ctypes.Structure): _fields_ = [("resp", ctypes.c_char_p), ("retcode", ctypes.c_int)]
CONV = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_int, ctypes.POINTER(ctypes.POINTER(Msg)),
                        ctypes.POINTER(ctypes.POINTER(Resp)), ctypes.c_void_p)
class Conv(ctypes.Structure): _fields_ = [("conv", CONV), ("appdata", ctypes.c_void_p)]

libc = ctypes.CDLL(ctypes.util.find_library("c"))
libc.calloc.restype = ctypes.c_void_p
@CONV
def conv(n, msgs, resp, _):
    # answer nothing (pam_u2f only sends info text); PAM frees this
    resp[0] = ctypes.cast(libc.calloc(n, ctypes.sizeof(Resp)), ctypes.POINTER(Resp))
    return 0

def key_ok():
    h = ctypes.c_void_p()
    c = Conv(conv, None)
    if libpam.pam_start(b"yubikey-unlock", USER.encode(), ctypes.byref(c), ctypes.byref(h)) != 0:
        return False
    rc = libpam.pam_authenticate(h, 0)
    libpam.pam_end(h, rc)
    return rc == 0

time.sleep(1)  # let all of the key's interfaces settle
if key_ok():
    out = subprocess.run(["loginctl", "list-sessions", "--no-legend"], capture_output=True, text=True).stdout
    for line in out.splitlines():
        f = line.split()
        if len(f) >= 4 and f[2] == USER and f[3].startswith("seat"):
            subprocess.run(["loginctl", "unlock-session", f[0]])
            print(f"unlocked session {f[0]}")
else:
    print("key not accepted")
