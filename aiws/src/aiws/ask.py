"""Super+Space: ask AIWS about whatever you're doing.

Before its window takes focus it notes what you were in: the focused
window and app, the text you'd selected, and the open project. That goes
with the question, so "what does this do?" means the selection and "why
is this failing?" means the terminal you were looking at. Nothing is
captured until you press the key.

  Enter         answer here (streams, ai:code)
  Ctrl+Enter    hand it to the assistant as a task; its actions show here
  Esc           close
"""
import json
import os
import threading
import time
import urllib.request

import gi

gi.require_version("Gtk", "3.0")
from gi.repository import Gdk, GLib, Gtk, Pango  # noqa: E402

from aiws import screen  # noqa: E402

GLib.set_prgname("ai-ask")  # window class: i3 floats and centres it

BASE = os.environ.get("AIWS_URL", "http://127.0.0.1:7300")
TOKEN_FILE = os.environ.get("AIWS_TOKEN_FILE", "/var/lib/aiws/desktop.token")
SELECTION_LIMIT = 4000


def capture():
    """What the user was looking at when they pressed the key."""
    w = screen.active_window()
    return {"window": w.get("title", ""), "app": w.get("app", ""),
            "selection": screen.selection(SELECTION_LIMIT)}


def _token():
    try:
        return open(TOKEN_FILE).read().strip()
    except OSError:
        return ""


def _req(path, payload=None, method=None):
    url = f"{BASE}/{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    return urllib.request.Request(url, data, method=method or ("POST" if data else "GET"),
                                  headers={"Authorization": f"Bearer {_token()}",
                                           "Content-Type": "application/json"})


def _json(path, payload=None, method=None):
    with urllib.request.urlopen(_req(path, payload, method), timeout=30) as r:
        return json.load(r)


def context_text(ctx, project):
    parts = [f"The user pressed the Ask key while in: {ctx['app'] or 'unknown app'}"
             f" — window \"{ctx['window']}\"."]
    if project:
        parts.append(f"Open project: {project}.")
    if ctx["selection"]:
        parts.append(f"They had this selected:\n```\n{ctx['selection']}\n```")
    return "\n".join(parts)


class Ask(Gtk.Window):
    def __init__(self, ctx):
        super().__init__(title="Ask AIWS")
        self.ctx = ctx
        self.set_default_size(720, 120)
        self.set_position(Gtk.WindowPosition.CENTER)
        self.set_keep_above(True)
        self.set_icon_name("applications-science")
        box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin=10)
        hint = f"in {ctx['app'] or 'desktop'}"
        if ctx["selection"]:
            hint += f" · {len(ctx['selection'])} chars selected"
        self.label = Gtk.Label(label=hint + "   ·   Enter: answer   Ctrl+Enter: let the assistant do it",
                               xalign=0)
        self.label.get_style_context().add_class("dim-label")
        self.entry = Gtk.Entry(placeholder_text="Ask about what you're doing…")
        self.entry.modify_font(Pango.FontDescription("Noto Sans 13"))
        self.view = Gtk.TextView(editable=False, wrap_mode=Gtk.WrapMode.WORD_CHAR,
                                 left_margin=6, right_margin=6)
        self.view.modify_font(Pango.FontDescription("JetBrains Mono 10"))
        self.scroll = Gtk.ScrolledWindow(min_content_height=0)
        self.scroll.add(self.view)
        self.scroll.set_no_show_all(True)
        box.pack_start(self.label, False, False, 0)
        box.pack_start(self.entry, False, False, 0)
        box.pack_start(self.scroll, True, True, 0)
        self.add(box)
        self.connect("key-press-event", self.on_key)
        self.connect("destroy", Gtk.main_quit)
        try:
            self.project = _json("api/status").get("active_project")
        except Exception:
            self.project = None

    def on_key(self, _w, ev):
        if ev.keyval == Gdk.KEY_Escape:
            self.destroy()
            return True
        if ev.keyval in (Gdk.KEY_Return, Gdk.KEY_KP_Enter):
            q = self.entry.get_text().strip()
            if not q:
                return True
            self.scroll.show_all()
            self.resize(720, 460)
            self.view.get_buffer().set_text("")
            agent = bool(ev.state & Gdk.ModifierType.CONTROL_MASK)
            threading.Thread(target=self.task if agent else self.answer, args=(q,),
                             daemon=True).start()
            return True
        return False

    def write(self, text):
        def _do():
            buf = self.view.get_buffer()
            buf.insert(buf.get_end_iter(), text)
            self.view.scroll_to_iter(buf.get_end_iter(), 0, False, 0, 0)
        GLib.idle_add(_do)

    def answer(self, q):
        body = {"model": "ai:code", "stream": True, "temperature": 0.4, "max_tokens": 1500,
                "chat_template_kwargs": {"enable_thinking": False},
                "messages": [
                    {"role": "system", "content": "You are AIWS, the assistant built into the "
                     "user's Linux workstation. Answer briefly and concretely.\n\n"
                     + context_text(self.ctx, self.project)},
                    {"role": "user", "content": q}]}
        try:
            with urllib.request.urlopen(_req("v1/chat/completions", body), timeout=600) as r:
                for raw in r:
                    line = raw.decode("utf-8", "replace").strip()
                    if not line.startswith("data:") or line.endswith("[DONE]"):
                        continue
                    for ch in json.loads(line[5:]).get("choices") or []:
                        piece = (ch.get("delta") or {}).get("content")
                        if piece:
                            self.write(piece)
        except Exception as e:
            self.write(f"\n[ai: {e}]")

    def task(self, q):
        prompt = f"{q}\n\n(Context: {context_text(self.ctx, self.project)})"
        try:
            t = _json("api/agent/tasks", {"prompt": prompt})
        except Exception as e:
            self.write(f"[ai: {e}]")
            return
        self.write(f"task {t['id']} — the assistant is working. Super+Esc stops it.\n\n")
        seen = 0
        while True:
            acts = _json(f"api/agent/actions?after={seen}")["actions"]
            for a in reversed(acts):
                if a["status"] == "running":
                    break
                seen = max(seen, a["id"])
                self.write(f"· {a['tool']} {a['args'][:90]} → {a['status']}\n")
            task = next((x for x in _json("api/agent/tasks")["tasks"] if x["id"] == t["id"]), {})
            if task.get("status") in ("done", "failed", "stopped"):
                self.write(f"\n{task.get('result') or task['status']}\n")
                return
            time.sleep(0.7)


def main():
    ctx = capture()  # before our window steals focus and the selection context
    Ask(ctx).show_all()
    Gtk.main()


if __name__ == "__main__":
    main()
