"""Keeps the Drop In to the Echo Dot open.

Every so often it checks whether the emulator is in a call. If not, it opens
the Alexa app on the Dot's page and taps Drop In, finding each control by its
label in the screen's accessibility tree rather than by position, so a layout
change only breaks it if the labels change too.

    DOT_NAME="Jacob's Echo Dot" python3 dot_call.py
"""
import os
import re
import subprocess
import time

ADB = os.environ.get("ADB", "/opt/android/platform-tools/adb")
DOT = os.environ.get("DOT_NAME", "Jacob's Echo Dot")
APP = "com.amazon.dee.app"
CHECK_EVERY = 20       # seconds between checks while the call is up
BACKOFF = [30, 60, 120, 300]  # seconds between failed redials


def log(*a):
    print(*a, flush=True)


def adb(*args, timeout=30):
    return subprocess.run([ADB, *args], capture_output=True, text=True,
                          timeout=timeout).stdout


def booted():
    return adb("shell", "getprop", "sys.boot_completed").strip() == "1"


def in_call():
    """Android puts audio in communication mode for the length of a call."""
    m = re.search(r"mAudioModeOwner: .*?mMode=(\w+)", adb("shell", "dumpsys", "audio"))
    return bool(m) and m.group(1) in ("MODE_IN_COMMUNICATION", "MODE_IN_CALL")


def screen():
    """[(label, clickable, (x, y))] for everything on screen with a label."""
    adb("shell", "uiautomator", "dump", "/sdcard/ui.xml")
    xml = adb("shell", "cat", "/sdcard/ui.xml")
    found = []
    for node in re.findall(r"<node [^>]*>", xml):
        get = lambda k: (re.search(k + r'="([^"]*)"', node) or [None, ""])[1]
        label = get("text") or get("content-desc")
        b = re.findall(r"\d+", get("bounds"))
        if label and len(b) == 4:
            x1, y1, x2, y2 = map(int, b)
            found.append((label.replace("&apos;", "'"), get("clickable") == "true",
                          ((x1 + x2) // 2, (y1 + y2) // 2)))
    return found


def tap(label, exact=False, wait=4):
    """Tap the first control whose label matches. True if one was found."""
    for text, clickable, (x, y) in screen():
        if (text == label) if exact else (label.lower() in text.lower()):
            adb("shell", "input", "tap", str(x), str(y))
            time.sleep(wait)
            return True
    return False


# Pop-ups the app puts in the way, and the button that dismisses each
# without agreeing to anything.
DISMISS = ["Decline", "LATER", "Later", "Remind Me Later", "Not now", "No thanks",
           "Get Started", "Done"]


def clear_popups():
    for _ in range(4):
        labels = {t for t, _, _ in screen()}
        hit = next((d for d in DISMISS if d in labels), None)
        if not hit:
            return
        log(f"[call] dismissing a pop-up with '{hit}'")
        tap(hit, exact=True)


def drop_in():
    """Open the Dot's page and start a Drop In. True if a call came up."""
    adb("shell", "am", "force-stop", APP)
    # Its microphone is Marina's voice (dot_mouth), so it may always have it.
    adb("shell", "pm", "grant", APP, "android.permission.RECORD_AUDIO")
    # The emulator's own switch for taking host audio as its microphone. It
    # starts off on every boot, even with -allow-host-audio, and with it off
    # the call carries silence.
    adb("emu", "avd", "hostmicon")
    adb("shell", "monkey", "-p", APP, "-c", "android.intent.category.LAUNCHER", "1")
    time.sleep(10)
    clear_popups()
    # Each step lists the labels it has had across versions of the app.
    for step in (("Tab, Devices", "Devices"), (DOT,), ("Drop In",)):
        if not any(tap(label, exact=True) for label in step) and not tap(step[0]):
            log(f"[call] couldn't find '{step[0]}' on screen")
            return False
    for _ in range(15):
        if in_call():
            return True
        time.sleep(1)
    labels = [t for t, _, _ in screen()][:8]
    log(f"[call] no call after tapping Drop In; on screen: {labels}")
    return False


def main():
    log(f"[call] keeping a Drop In open to {DOT}")
    failures = 0
    while True:
        if not booted():
            time.sleep(10)
            continue
        if in_call():
            failures = 0
            time.sleep(CHECK_EVERY)
            continue
        log("[call] not in a call; dropping in")
        if drop_in():
            log("[call] connected")
            failures = 0
            continue
        wait = BACKOFF[min(failures, len(BACKOFF) - 1)]
        failures += 1
        log(f"[call] trying again in {wait}s")
        time.sleep(wait)


if __name__ == "__main__":
    main()
