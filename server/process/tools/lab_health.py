"""How the lab is doing: lab1, lab2, lab3 and the internet.

Checked from where the bridge runs (ct110 on lab3), so lab3's own numbers
are first-hand: its temperatures (the container can read the host's hwmon),
its disk and load, and whether llama-swap answers. lab2 is asked over the
same SSH she uses to work on it. Anything else is a machine that should
answer a ping and, if a port is given, a connection on it.

A watcher checks every few minutes. Something going wrong is said like a
reminder going off (once, not every check), and so is it coming right.

Set up by `lab_health:` in character_config.yaml; off unless enabled, so the
Mac app's own bridge doesn't warn about the lab twice.
"""
import re
import socket
import subprocess
import threading
import time
import urllib.request
from pathlib import Path

from process.config import load_config

_cfg = load_config().get("lab_health") or {}

ENABLED = bool(_cfg.get("enabled", False))
EVERY = max(60.0, float(_cfg.get("check_minutes", 5)) * 60)
DISK_WARN = float(_cfg.get("disk_warn_percent", 92))
TEMP_WARN = float(_cfg.get("temp_warn_c", 85))
LOAD_WARN = float(_cfg.get("load_warn_per_core", 2.0))
# A problem has to be there on two checks running before she says anything,
# so a blip (a reboot, a busy minute) doesn't become a message.
CONFIRM = int(_cfg.get("confirm_checks", 2))
LOCAL_NAME = str(_cfg.get("local_name") or "lab3")
# Failed units that mean nothing: casper-md5check is the install USB's
# self-check, which fails on every Mint install once it's on a disk.
IGNORE_UNITS = set(_cfg.get("ignore_units") or ["casper-md5check.service"])
LLAMA = str(_cfg.get("llama_url") or "http://127.0.0.1:8080/health")
MACHINES = _cfg.get("machines") or [
    {"name": "lab1", "host": "192.168.1.10", "port": 8006},
    {"name": "lab3", "host": "192.168.1.13", "port": 8006},
]

on_change = None          # set by the registry: announce(text)
_lock = threading.Lock()
_last = {"at": 0.0, "report": None}
_watcher = None


def enabled():
    return ENABLED


# ---- the checks --------------------------------------------------------------

def _ping(host):
    try:
        r = subprocess.run(["ping", "-c", "1", "-W", "2", host],
                           capture_output=True, timeout=5)
        return r.returncode == 0
    except Exception:
        return False


def _port(host, port, timeout=3):
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


def _internet():
    try:
        socket.getaddrinfo("cloudflare.com", 443)
    except OSError:
        return "can't look up names (DNS is down)"
    if not (_port("1.1.1.1", 443) or _port("8.8.8.8", 443)):
        return "can't reach the internet"
    return None


def _temps():
    """{sensor: °C} from hwmon, highest reading per chip."""
    out = {}
    for d in Path("/sys/class/hwmon").glob("hwmon*"):
        try:
            name = (d / "name").read_text().strip()
        except OSError:
            continue
        best = None
        for f in d.glob("temp*_input"):
            try:
                c = int(f.read_text().strip()) / 1000
            except (OSError, ValueError):
                continue
            best = c if best is None else max(best, c)
        if best is not None and 0 < best < 150:
            out[name] = best
    return out


_FRIENDLY = {"k10temp": "CPU", "coretemp": "CPU", "amdgpu": "GPU", "nvme": "SSD",
             "acpitz": "board", "iwlwifi_1": "wifi"}


def _local():
    """lab3's own numbers, from inside ct110."""
    facts, problems = [], []
    temps = _temps()
    for chip, c in sorted(temps.items(), key=lambda kv: -kv[1]):
        label = _FRIENDLY.get(chip)
        if not label:
            continue
        facts.append(f"{label} {c:.0f}°C")
        if c >= TEMP_WARN:
            problems.append(f"{LOCAL_NAME}'s {label} is at {c:.0f}°C")
    try:
        st = __import__("os").statvfs("/")
        used = 100 * (1 - st.f_bavail / st.f_blocks)
        free_gb = st.f_bavail * st.f_frsize / 1e9
        facts.append(f"disk {used:.0f}% used ({free_gb:.0f} GB free)")
        if used >= DISK_WARN:
            problems.append(f"{LOCAL_NAME}'s model disk is {used:.0f}% full, "
                            f"{free_gb:.0f} GB left")
    except OSError:
        pass
    try:
        load = float(Path("/proc/loadavg").read_text().split()[1])
        cores = __import__("os").cpu_count() or 1
        facts.append(f"load {load:.1f} on {cores} cores")
        if load / cores >= LOAD_WARN:
            problems.append(f"{LOCAL_NAME} is overloaded (load {load:.1f})")
    except (OSError, ValueError, IndexError):
        pass
    if LLAMA:
        try:
            with urllib.request.urlopen(LLAMA, timeout=4) as r:
                ok = r.status == 200
        except Exception:
            ok = False
        facts.append("models " + ("answering" if ok else "NOT answering"))
        if not ok:
            problems.append(f"the model server on {LOCAL_NAME} isn't answering")
    return facts, problems


_LAB2 = r"""df -P / | awk 'NR==2{print "disk", $5, int($4/1048576)}'
for f in /sys/class/hwmon/hwmon*; do n=$(cat $f/name 2>/dev/null)
  t=$(cat $f/temp*_input 2>/dev/null | sort -n | tail -1); [ -n "$t" ] && echo temp $n $t; done
echo load $(cut -d' ' -f2 /proc/loadavg) $(nproc)
echo failed $(systemctl --failed --no-legend --plain 2>/dev/null | awk '{print $1}' | tr '\n' ' ')
echo up $(cut -d. -f1 /proc/uptime)"""


def _lab2():
    from process.tools import workspace
    if not workspace.available():
        return None
    name = workspace.NAME
    # ping needs a capability the bridge's user may not have in a container,
    # so the SSH port answering counts as up too.
    if not (_port(workspace.HOST, workspace.PORT) or _ping(workspace.HOST)):
        return name, [], [f"{name} is off or unreachable"]
    code, out = workspace._ssh(_LAB2, timeout=20)
    if code != 0:
        return name, ["answers ping"], [f"{name} is up but won't let her in over SSH"]
    facts, problems = [], []
    for line in out.splitlines():
        bits = line.split()
        if not bits:
            continue
        try:
            if bits[0] == "disk":
                pct, free = int(bits[1].rstrip("%")), int(bits[2])
                facts.append(f"disk {pct}% used ({free} GB free)")
                if pct >= DISK_WARN:
                    problems.append(f"{name}'s disk is {pct}% full, {free} GB left")
            elif bits[0] == "temp" and len(bits) >= 3:
                label = _FRIENDLY.get(bits[1])
                c = int(bits[2]) / 1000
                if label and 0 < c < 150:
                    facts.append(f"{label} {c:.0f}°C")
                    if c >= TEMP_WARN:
                        problems.append(f"{name}'s {label} is at {c:.0f}°C")
            elif bits[0] == "load":
                load, cores = float(bits[1]), int(bits[2])
                facts.append(f"load {load:.1f}")
                if load / max(cores, 1) >= LOAD_WARN:
                    problems.append(f"{name} is overloaded (load {load:.1f})")
            elif bits[0] == "failed" and len(bits) > 1:
                units = [u for u in bits[1:] if u.endswith((".service", ".mount", ".timer"))
                         and u not in IGNORE_UNITS]
                if units:
                    facts.append("failed: " + ", ".join(units[:4]))
                    problems.append(f"on {name}, {', '.join(units[:3])} "
                                    f"{'has' if len(units) == 1 else 'have'} failed")
            elif bits[0] == "up":
                secs = int(bits[1])
                facts.append(f"up {secs // 86400}d {secs % 86400 // 3600}h")
        except (ValueError, IndexError):
            continue
    return name, facts, problems


def check():
    """Look at everything now. {"machines": {name: [facts]}, "problems": [...]}."""
    report = {"machines": {}, "problems": [], "at": time.time()}
    for m in MACHINES:
        name, host, port = m.get("name"), m.get("host"), m.get("port")
        if not host:
            continue
        if name == LOCAL_NAME:
            continue   # its own numbers come from _local, below
        up = (port and _port(host, port)) or _ping(host)
        report["machines"][name] = ["up" if up else "DOWN"]
        if not up:
            report["problems"].append(f"{name} is off or unreachable")
        elif port and not _port(host, port):
            report["machines"][name].append(f"port {port} closed")
            report["problems"].append(f"{name} is up but its port {port} isn't answering")
    facts, problems = _local()
    report["machines"][LOCAL_NAME] = facts
    report["problems"] += problems
    lab2 = _lab2()
    if lab2:
        name, facts, problems = lab2
        report["machines"][name] = facts or ["DOWN"]
        report["problems"] += problems
    net = _internet()
    report["machines"]["internet"] = [net or "fine"]
    if net:
        report["problems"].append(f"the lab {net}")
    with _lock:
        _last.update(at=report["at"], report=report)
    return report


def _recent(max_age=None):
    with _lock:
        r = _last["report"]
        if r and time.time() - _last["at"] < (max_age or EVERY):
            return r
    return check()


def lab_status():
    if not ENABLED:
        return "Lab health checks aren't set up on this bridge."
    r = check()
    lines = [f"- {name}: {', '.join(facts)}" for name, facts in r["machines"].items()]
    head = ("Problems: " + "; ".join(r["problems"]) + ".") if r["problems"] \
        else "Nothing wrong."
    return head + "\n" + "\n".join(lines)


def brief():
    """One line for the morning brief, or "" when all is well."""
    if not ENABLED:
        return ""
    try:
        r = _recent()
    except Exception:
        return ""
    return ("in the lab, " + "; ".join(r["problems"])) if r["problems"] else ""


# ---- watching ----------------------------------------------------------------

def _key(problem):
    """The same problem with different numbers is the same problem."""
    return re.sub(r"\d+(\.\d+)?", "#", problem)


def _watch():
    from process import state
    seen = {}                                   # key -> checks in a row
    told = set(state.get("lab_health_told", []) or [])
    while True:
        try:
            r = check()
            now = {_key(p): p for p in r["problems"]}
            for k in list(seen):
                if k not in now:
                    seen.pop(k)
            for k in now:
                seen[k] = seen.get(k, 0) + 1
            new = [now[k] for k in now if seen[k] >= CONFIRM and k not in told]
            fixed = [k for k in told if k not in now]
            if new and on_change:
                on_change("Something's wrong in their lab: " + "; ".join(new) + ". "
                          "Tell them, in your own words, in one or two sentences, and "
                          "say what you'd do about it.")
            if fixed and on_change:
                on_change("A lab problem you told them about has cleared up ("
                          + "; ".join(k.replace("#", "…") for k in fixed) + "). "
                          "Let them know in one short sentence.")
            if new or fixed:
                told = (told | {_key(p) for p in new}) - set(fixed)
                state.put("lab_health_told", sorted(told))
        except Exception as e:
            print(f"[lab] check failed: {type(e).__name__}: {e}", flush=True)
        time.sleep(EVERY)


def start(announce):
    global on_change, _watcher
    on_change = announce
    if not ENABLED or (_watcher and _watcher.is_alive()):
        return
    _watcher = threading.Thread(target=_watch, daemon=True, name="lab-health")
    _watcher.start()
    print(f"[lab] watching the lab every {int(EVERY // 60)} min", flush=True)


SPECS = [
    ("lab_status", lab_status, {
        "description": "Check on their homelab right now: whether lab1, lab2 and "
                       "lab3 are up, their temperatures, disks and load, whether the "
                       "model server answers, and whether the internet works. Use for "
                       "'is everything OK at home?' and before blaming the lab for "
                       "something.",
        "parameters": {"type": "object", "properties": {}}}),
]
