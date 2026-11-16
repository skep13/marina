"""Desktop pieces: the Control Centre window and the panel readout.

`aiws-control` opens the web UI in a small WebKitGTK window (no
browser, no Electron), handing it the desktop token in the URL fragment,
which never reaches a server log. `aiws-panel i3blocks` is the bar block:
loaded model and assistant state; left click opens the centre, right click
stops the assistant.
"""
import json
import os
import sys
import urllib.request

BASE = os.environ.get("AIWS_URL", "http://127.0.0.1:7300")
TOKEN_FILE = os.environ.get("AIWS_TOKEN_FILE", "/var/lib/aiws/desktop.token")


def _token():
    try:
        return open(TOKEN_FILE).read().strip()
    except OSError:
        return ""


def control_centre():
    import gi
    gi.require_version("Gtk", "3.0")
    gi.require_version("WebKit2", "4.1")
    from gi.repository import GLib, Gtk, WebKit2
    GLib.set_prgname("aiws-control")  # window class, for the i3 rule

    win = Gtk.Window(title="AI Control Centre")
    win.set_default_size(1180, 780)
    win.set_icon_name("applications-science")
    view = WebKit2.WebView()
    view.load_uri(f"{BASE}/ui/#token={_token()}")
    win.add(view)
    win.connect("destroy", Gtk.main_quit)
    win.show_all()
    Gtk.main()


def panel(fmt="genmon"):
    if fmt == "i3blocks":
        import subprocess
        button = os.environ.get("BLOCK_BUTTON", "")
        if button == "1":
            subprocess.Popen(["aiws-control"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        elif button == "3":
            subprocess.Popen(["ai", "agent", "stop"], start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        req = urllib.request.Request(f"{BASE}/api/status",
                                     headers={"Authorization": f"Bearer {_token()}"})
        s = json.load(urllib.request.urlopen(req, timeout=2))
    except Exception:
        if fmt == "i3blocks":
            print("◇ AI offline\n◇\n#cc6666")
        else:
            print("<txt> ◇ AI offline </txt><tool>aiwsd isn't answering</tool>"
                  "<txtclick>aiws-control</txtclick>")
        return
    loaded = ", ".join(r.get("model", "?") for r in s.get("running", [])) or "no model"
    agent = s.get("agent", "running")
    mark = {"running": "◆", "paused": "❚❚", "stopped": "■"}.get(agent, "◆")
    mem = s.get("memory") or {}
    free = mem.get("available_mb")
    tip = (f"project: {s.get('active_project') or '-'}\nloaded: {loaded}\n"
           f"assistant: {agent}\nmemory free: {free} MB" if free else "")
    if fmt == "i3blocks":
        colour = {"running": "#d8dee9", "paused": "#f2c14e", "stopped": "#ef6461"}.get(agent)
        print(f"{mark} {loaded}\n{mark}\n{colour}")
        return
    print(f"<txt> {mark} {loaded} </txt><tool>{tip}</tool>"
          f"<txtclick>aiws-control</txtclick>")


if __name__ == "__main__":
    if sys.argv[1] == "panel":
        panel(sys.argv[2] if len(sys.argv) > 2 else "genmon")
    else:
        control_centre()
