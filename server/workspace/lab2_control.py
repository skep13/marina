"""Mouse, keyboard, windows and apps on their Linux Mint desktop. Runs on lab2.

The workspace tool sends this file over SSH on every call
(python3 - ACTION JSON), so there is nothing to install and it can't drift
from the repo. Prints one JSON object.

Actions:
  screens            the monitors and where they sit
  windows            open windows: id, desktop, geometry, title
  click              {x, y, button, double} or {target} (found by name)
  move               {x, y}
  drag               {x, y, to_x, to_y}
  type               {text}
  key                {keys}  xdotool syntax: ctrl+l, Return, super, alt+F4
  scroll             {direction, amount, x, y}
  focus              {window}  part of a window title or app name
  find               {target}  where a button, field or link is, by its name
  shot               {grid}  a screenshot, optionally with a labelled grid
  apps               {query}  installed apps matching a name
  open_app           {name, screen}  start one; screen left/right/dell/acer
  place              {window, screen, maximize}
"""
import base64
import configparser
import glob
import io
import json
import os
import re
import shutil
import subprocess
import sys
import time
from pathlib import Path

ENV = dict(os.environ, DISPLAY=os.environ.get("DISPLAY") or ":0")
uid = os.getuid()
ENV.setdefault("XDG_RUNTIME_DIR", f"/run/user/{uid}")
ENV.setdefault("DBUS_SESSION_BUS_ADDRESS", f"unix:path=/run/user/{uid}/bus")
os.environ.update(ENV)


def run(*args, timeout=15):
    p = subprocess.run(args, capture_output=True, text=True, env=ENV, timeout=timeout)
    return p.returncode, (p.stdout or "") + (p.stderr or "")


def out(obj):
    print(json.dumps(obj))
    sys.exit(0)


def fail(msg, **extra):
    out({"ok": False, "error": msg, **extra})


# ---- screens and windows -------------------------------------------------

def screens():
    code, text = run("xrandr", "--listmonitors")
    mons = []
    for m in re.finditer(r"\d+: \+\*?(\S+) (\d+)/\d+x(\d+)/\d+\+(\d+)\+(\d+)", text):
        name, w, h, x, y = m.group(1), *map(int, m.groups()[1:])
        mons.append({"name": name, "x": x, "y": y, "width": w, "height": h,
                     "portrait": h > w})
    mons.sort(key=lambda m: m["x"])
    for i, m in enumerate(mons):
        m["side"] = "left" if i == 0 else "right" if i == len(mons) - 1 else f"middle{i}"
    return mons


ALIASES = {"dell": "left", "vertical": "left", "main": "left", "acer": "right", "other": "right"}


def screen_named(name):
    name = (name or "").strip().lower()
    side = ALIASES.get(name, name)
    for m in screens():
        if side in (m["side"], m["name"].lower()):
            return m
    return None


def windows():
    code, text = run("wmctrl", "-lpGx")
    wins = []
    for line in text.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 9:
            continue
        wid, desk, pid, x, y, w, h, wmclass = parts[:8]
        title = parts[9] if len(parts) > 9 else ""
        if desk == "-1" or wmclass.lower().startswith("nemo-desktop"):
            continue           # panels and the desktop itself
        wins.append({"id": wid, "pid": int(pid), "x": int(x), "y": int(y), "width": int(w),
                     "height": int(h), "class": wmclass, "title": title})
    return wins


def window_matching(query):
    q = (query or "").strip().lower()
    if not q:
        return None
    wins = windows()
    for w in wins:
        if q == w["title"].lower() or q in w["class"].lower().split("."):
            return w
    for w in wins:
        if q in w["title"].lower() or q in w["class"].lower():
            return w
    return None


# ---- input ---------------------------------------------------------------

BUTTONS = {"left": "1", "middle": "2", "right": "3"}


def click(x, y, button="left", double=False):
    b = BUTTONS.get((button or "left").lower(), "1")
    args = ["xdotool", "mousemove", "--sync", str(int(x)), str(int(y)), "click"]
    if double:
        args += ["--repeat", "2", "--delay", "120"]
    run(*args, b)
    return {"ok": True, "clicked": [int(x), int(y)], "button": button or "left", "double": bool(double)}


def type_text(text):
    if not text:
        fail("Nothing to type.")
    # xdotool type handles unicode; the delay keeps fast typing from dropping keys.
    code, msg = run("xdotool", "type", "--clearmodifiers", "--delay", "12", "--", text, timeout=120)
    if code:
        fail(f"Typing failed: {msg.strip()[:200]}")
    return {"ok": True, "typed": len(text)}


KEY_OK = re.compile(r"^[A-Za-z0-9_+\-]+$")


def press(keys):
    combos = (keys or "").split()
    if not combos or not all(KEY_OK.match(k) for k in combos):
        fail("keys must be xdotool key names like ctrl+l, Return, Tab, super, alt+F4, separated by spaces.")
    code, msg = run("xdotool", "key", "--clearmodifiers", *combos)
    if code:
        fail(f"xdotool didn't know one of those keys: {msg.strip()[:200]}")
    return {"ok": True, "pressed": combos}


def scroll(direction="down", amount=5, x=None, y=None):
    b = {"up": "4", "down": "5", "left": "6", "right": "7"}.get((direction or "down").lower())
    if not b:
        fail("direction must be up, down, left or right.")
    if x is not None and y is not None:
        run("xdotool", "mousemove", "--sync", str(int(x)), str(int(y)))
    run("xdotool", "click", "--repeat", str(max(1, min(int(amount or 5), 30))), "--delay", "40", b)
    return {"ok": True, "scrolled": direction, "amount": amount}


def drag(x, y, to_x, to_y):
    run("xdotool", "mousemove", "--sync", str(int(x)), str(int(y)), "mousedown", "1")
    time.sleep(0.15)
    run("xdotool", "mousemove", "--sync", str(int(to_x)), str(int(to_y)))
    time.sleep(0.15)
    run("xdotool", "mouseup", "1")
    return {"ok": True, "dragged": [[int(x), int(y)], [int(to_x), int(to_y)]]}


def focus(query):
    w = window_matching(query)
    if not w:
        fail(f"No open window matches {query!r}.", windows=[f"{w['class']}: {w['title']}" for w in windows()][:25])
    run("wmctrl", "-i", "-a", w["id"])
    return {"ok": True, "focused": w["title"], "window": w}


# ---- finding things by name (accessibility tree) -------------------------

ACTIONABLE = {"push button", "toggle button", "check box", "radio button", "menu item",
              "link", "entry", "text", "password text", "combo box", "page tab",
              "list item", "table cell", "icon", "menu", "spin button", "slider",
              "tree item", "check menu item", "radio menu item", "label", "heading"}


def find(target, limit=6):
    """Visible, named controls whose name matches, best first, from the apps
    that expose an accessibility tree (GTK apps do; browsers and Electron
    apps often only partly)."""
    q = (target or "").strip().lower()
    if not q:
        fail("Say what to find.")
    try:
        import pyatspi
    except ImportError:
        return {"ok": True, "matches": [], "note": "no accessibility library"}
    words = [w for w in re.split(r"\W+", q) if w]
    matches = []
    seen = [0]
    deadline = time.time() + 6.0
    active = {w["pid"] for w in windows()}

    def visit(node, depth, app_name):
        if seen[0] > 6000 or time.time() > deadline or depth > 40:
            return
        seen[0] += 1
        try:
            name = (node.name or "").strip()
            role = node.getRoleName()
            states = node.getState()
            showing = states.contains(pyatspi.STATE_SHOWING) and states.contains(pyatspi.STATE_VISIBLE)
        except Exception:
            return
        if not showing and depth > 2:
            return
        if name and role in ACTIONABLE:
            low = name.lower()
            score = 0
            if low == q:
                score = 100
            elif q in low:
                score = 70 - min(len(low) - len(q), 40) * 0.5
            elif words and all(w in low for w in words):
                score = 50
            if score:
                try:
                    ext = node.queryComponent().getExtents(pyatspi.DESKTOP_COORDS)
                    if ext.width > 0 and ext.height > 0:
                        if role in ("push button", "link", "menu item", "page tab", "check box", "entry"):
                            score += 10
                        matches.append({"name": name, "role": role, "app": app_name, "score": score,
                                        "x": ext.x + ext.width // 2, "y": ext.y + ext.height // 2,
                                        "box": [ext.x, ext.y, ext.width, ext.height]})
                except Exception:
                    pass
        try:
            for i in range(min(node.childCount, 400)):
                visit(node.getChildAtIndex(i), depth + 1, app_name)
        except Exception:
            return

    try:
        desktop = pyatspi.Registry.getDesktop(0)
        for i in range(desktop.childCount):
            app = desktop.getChildAtIndex(i)
            try:
                if app is None or (active and app.get_process_id() not in active):
                    continue
                visit(app, 0, app.name or "")
            except Exception:
                continue
    except Exception as e:
        return {"ok": True, "matches": [], "note": f"accessibility tree unavailable: {e}"}
    matches.sort(key=lambda m: -m["score"])
    return {"ok": True, "matches": matches[:limit]}


# ---- screenshots ---------------------------------------------------------

def shot(grid=False, scale=0.5, crop=None):
    path = "/tmp/marina-control.png"
    code, msg = run("scrot", "-o", path)
    if code:
        fail(f"Screenshot failed: {msg.strip()[:200]}")
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        data = Path(path).read_bytes()
        return {"ok": True, "scale": 1.0, "image": base64.b64encode(data).decode()}
    im = Image.open(path).convert("RGB")
    W, H = im.size
    left = top = 0
    if crop:
        cx, cy, half = int(crop[0]), int(crop[1]), int(crop[2])
        left, top = max(0, min(cx - half, W - 2 * half)), max(0, min(cy - half, H - 2 * half))
        im = im.crop((left, top, min(W, left + 2 * half), min(H, top + 2 * half)))
    im = im.resize((max(1, int(im.width * scale)), max(1, int(im.height * scale))), Image.LANCZOS)
    if grid:
        d = ImageDraw.Draw(im)
        step = 100
        for gx in range(0, W, step):
            sx = int(gx * scale)
            d.line([(sx, 0), (sx, im.height)], fill=(255, 0, 255), width=1)
            for gy in range(0, H, 400):
                d.text((sx + 2, int(gy * scale) + 2), str(gx), fill=(255, 0, 255))
        for gy in range(0, H, step):
            sy = int(gy * scale)
            d.line([(0, sy), (im.width, sy)], fill=(255, 0, 255), width=1)
            for gx in range(0, W, 400):
                d.text((int(gx * scale) + 2, sy + 2), str(gy), fill=(255, 0, 255))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return {"ok": True, "scale": scale, "width": W, "height": H, "left": left, "top": top,
            "image_width": im.width, "image_height": im.height,
            "image": base64.b64encode(buf.getvalue()).decode()}


# ---- apps by name --------------------------------------------------------

APP_DIRS = ["/usr/share/applications", "/usr/local/share/applications",
            "/var/lib/flatpak/exports/share/applications",
            str(Path.home() / ".local/share/flatpak/exports/share/applications"),
            str(Path.home() / ".local/share/applications"),
            "/var/lib/snapd/desktop/applications"]


def installed_apps():
    apps = {}
    for d in APP_DIRS:
        for f in glob.glob(os.path.join(d, "*.desktop")):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("Type", "Application") != "Application" or e.get("NoDisplay", "").lower() == "true" \
                    or e.get("Hidden", "").lower() == "true":
                continue
            did = os.path.basename(f)[:-len(".desktop")]
            apps[did] = {"id": did, "name": e.get("Name", did), "generic": e.get("GenericName", ""),
                         "keywords": e.get("Keywords", ""), "exec": e.get("Exec", ""),
                         "comment": e.get("Comment", "")}
    return list(apps.values())


def match_apps(query):
    q = (query or "").strip().lower()
    scored = []
    for a in installed_apps():
        name = a["name"].lower()
        hay = " ".join([a["id"], a["generic"], a["keywords"], a["comment"], a["exec"]]).lower()
        if not q:
            s = 1
        elif name == q:
            s = 100
        elif name.startswith(q):
            s = 80
        elif q in name:
            s = 65
        elif q in a["id"].lower():
            s = 55
        elif q in hay:
            s = 30
        elif all(w in name + " " + hay for w in q.split()):
            s = 25
        else:
            continue
        scored.append((s, a))
    scored.sort(key=lambda t: (-t[0], t[1]["name"]))
    return [a for _, a in scored]


def place(w, screen_name, maximize=True):
    m = screen_named(screen_name)
    if not m:
        fail(f"No screen called {screen_name!r}.", screens=screens())
    run("wmctrl", "-i", "-r", w["id"], "-b", "remove,maximized_vert,maximized_horz")
    run("wmctrl", "-i", "-r", w["id"], "-e", f"0,{m['x'] + 40},{m['y'] + 40},-1,-1")
    time.sleep(0.3)
    if maximize:
        run("wmctrl", "-i", "-r", w["id"], "-b", "add,maximized_vert,maximized_horz")
    run("wmctrl", "-i", "-a", w["id"])
    return m


def open_app(name, screen=""):
    found = match_apps(name)
    if not found:
        fail(f"No installed app matches {name!r}.",
             suggestions=[a["name"] for a in match_apps(name.split()[0] if name.split() else "")][:8])
    app = found[0]
    before = {w["id"] for w in windows()}
    code, msg = run("bash", "-c", f"setsid -f gtk-launch {app['id']!r} >/dev/null 2>&1 || "
                                  f"setsid -f flatpak run {app['id']!r} >/dev/null 2>&1")
    result = {"ok": True, "opened": app["name"], "id": app["id"]}
    if len(found) > 1:
        result["other_matches"] = [a["name"] for a in found[1:5]]
    # Wait for its window: either a new one, or an existing one it raised.
    w = None
    for _ in range(40):
        time.sleep(0.5)
        new = [x for x in windows() if x["id"] not in before]
        if new:
            w = new[-1]
            break
    if w is None:
        w = window_matching(app["name"]) or window_matching(app["id"].split(".")[-1])
        result["note"] = ("It was already open; brought it up." if w else
                          "Started it, but no window has appeared yet (some apps take a while, "
                          "or only open in the tray).")
    if w:
        result["window"] = w["title"]
        if screen:
            m = place(w, screen)
            result["screen"] = m["side"] + f" ({m['name']})"
        else:
            run("wmctrl", "-i", "-a", w["id"])
    return result


# ---- main ----------------------------------------------------------------

def main():
    action = sys.argv[1] if len(sys.argv) > 1 else "screens"
    try:
        a = json.loads(sys.argv[2]) if len(sys.argv) > 2 else {}
    except ValueError:
        fail("Arguments weren't valid JSON.")
    if action == "screens":
        out({"ok": True, "screens": screens()})
    if action == "windows":
        out({"ok": True, "windows": windows()})
    if action == "click":
        if a.get("x") is None or a.get("y") is None:
            fail("click needs x and y (or a target, resolved before this runs).")
        out(click(a["x"], a["y"], a.get("button", "left"), a.get("double", False)))
    if action == "move":
        run("xdotool", "mousemove", "--sync", str(int(a["x"])), str(int(a["y"])))
        out({"ok": True, "moved": [int(a["x"]), int(a["y"])]})
    if action == "drag":
        out(drag(a["x"], a["y"], a["to_x"], a["to_y"]))
    if action == "type":
        out(type_text(a.get("text", "")))
    if action == "key":
        out(press(a.get("keys", "")))
    if action == "scroll":
        out(scroll(a.get("direction", "down"), a.get("amount", 5), a.get("x"), a.get("y")))
    if action == "focus":
        out(focus(a.get("window", "")))
    if action == "find":
        out(find(a.get("target", "")))
    if action == "shot":
        out(shot(bool(a.get("grid")), float(a.get("scale", 0.5)), a.get("crop")))
    if action == "apps":
        out({"ok": True, "apps": [{"name": x["name"], "id": x["id"]} for x in match_apps(a.get("query", ""))][:20]})
    if action == "open_app":
        out(open_app(a.get("name", ""), a.get("screen", "")))
    if action == "place":
        w = window_matching(a.get("window", ""))
        if not w:
            fail(f"No open window matches {a.get('window')!r}.")
        m = place(w, a.get("screen", ""), a.get("maximize", True))
        out({"ok": True, "placed": w["title"], "screen": m["side"]})
    fail(f"Unknown action {action!r}.")


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception as e:
        out({"ok": False, "error": f"{type(e).__name__}: {e}"})
