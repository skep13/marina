#!/usr/bin/env python3
"""Text to STEP: ask lab3's model for a build123d script, run it, export.

  cad "60x40x5 mm plate, 3 mm corner fillets, four M4 clearance holes 6 mm in"
  cad -o ~/CAD/bracket "L bracket, 2 mm sheet, 30 mm legs, 20 mm wide"
  cad --edit ~/CAD/bracket/part.py "make the legs 40 mm and add a gusset"
  cad --run ~/CAD/bracket/part.py          # re-run a script you edited by hand

Each job writes part.py, part.step and part.stl into its folder. In Onshape,
use Import (the up-arrow icon in the document tabs bar) and pick part.step.

The model writes code, the code runs in a separate process with a timeout,
and any error or invalid solid is sent back to the model to fix, up to
--tries times. Settings come from the environment, with defaults that match
the aiws lab3-marina entry:

  CAD_BASE_URL   http://192.168.1.15:8080
  CAD_MODEL      marina
  CAD_KEY        the API key; if unset, AIWS_KEY_LAB3 from
                 ~/.config/aiws/etc/secrets.env is used
"""
import argparse
import json
import os
import re
import subprocess
import sys
import textwrap
import time
import urllib.error
import urllib.request
from pathlib import Path

SECRETS = Path.home() / ".config/aiws/etc/secrets.env"

SYSTEM = """You write build123d (Python CAD) scripts that produce one solid part.
Rules:
- Start with `from build123d import *`. Use only build123d and the math module.
- Units are millimetres. Z is up. The part should rest on the XY plane (z >= 0)
  unless the user says otherwise.
- Use algebra mode (shapes combined with + - &). Do not use BuildPart contexts.
- Assign the final shape to a variable named `result`. Do not export, print or show.
- Also set `expected_volume`: the part's volume in mm³ worked out straight from
  the numbers in the request, as arithmetic on those literal numbers (not on
  your variables), e.g. for a 80x50x6 plate with four 4.5 mm holes:
      expected_volume = 80*50*6 - 4 * math.pi*(4.5/2)**2*6
  Ignore fillets and chamfers under 5 mm. The tool compares it with the real
  volume, so a missing or misplaced feature gets caught.
- Reply with a single ```python code block and nothing else.

Algebra-mode reference (these are the real signatures):
  Box(length, width, height)   Cylinder(radius, height)
      Both are CENTRED on their position in X, Y and Z by default. To sit one on
      z=0, pass align=(Align.CENTER, Align.CENTER, Align.MIN).
  Sphere(radius); Cone(bottom_radius, top_radius, height); Torus(major, minor)
  Pos(x, y, z) * shape        move;   Rot(x_deg, y_deg, z_deg) * shape   rotate
      (the location always goes on the LEFT: Pos(...) * Box(...), never Box(...) * Pos(...);
       chain them as Pos(...) * Rot(...) * shape)
  a + b union;  a - b cut;  a & b intersect
  fillet(shape.edges().filter_by(Axis.Z), radius=3)    round vertical edges
  chamfer(shape.edges().group_by(Axis.Z)[-1], length=1) chamfer top edges
  shape.faces().sort_by(Axis.Z)[-1]    top face;  .edges().filter_by(Axis.X)
  2D: Rectangle(w, h), Circle(r), RegularPolygon(r, sides), Polygon(*pts),
      SlotOverall(length, width), Text("abc", font_size)
  extrude(sketch, amount)  sketches live on Plane.XY; use Plane.XZ * sketch or
      Plane.XY.offset(z) * sketch to place them; revolve(sketch, Axis.Z)
  mirror(shape, about=Plane.YZ)
  Through holes: cut a centred Cylinder at mid-thickness, twice as tall as the part:
      result = plate - Pos(10, 5, plate_t / 2) * Cylinder(2.2, plate_t * 2)
  Repeated features: sum shapes from a list comprehension or loop,
      e.g. holes = [Pos(x, y, t / 2) * Cylinder(r, t * 2) for x, y in pts]
      for h in holes: result -= h
Robustness (most failures come from these):
- For brackets, profiles and anything with a constant cross-section, draw the
  section as a 2D Polygon(...) on the right plane and extrude it, instead of
  unioning boxes. Round its corners in 2D with fillet(sketch.vertices(), r)
  or by picking vertices with .sort_by / .filter_by.
- Only fillet or chamfer edges you can select unambiguously; never index a
  selection with [n] unless you know how many items it has. Keep radii below
  half the thinnest wall that touches the edge. If unsure, skip the fillet.
- Orientation: a base or plate lies flat on XY; anything "tall" or "upright"
  rises in +Z. A side profile drawn on Plane.XY and extruded goes up in Z, so
  for an L bracket either union a flat base Box and an upright Box, or draw
  the L on Plane.XZ and extrude it along Y. Place holes in the frame you built.
- Keep the script short and direct; no functions or classes needed.
Name the key dimensions as variables at the top so the script is easy to edit.
Clearance holes: M3 3.4, M4 4.5, M5 5.5, M6 6.6 mm diameter.
"""

RUNNER = r'''
import json, sys, traceback
out = sys.argv[2]
ns = {}
try:
    src = open(sys.argv[1]).read()
    exec(compile(src, sys.argv[1], "exec"), ns)
    from build123d import Shape, Compound, export_step, export_stl
    r = ns.get("result")
    if r is None:
        raise RuntimeError("the script did not assign `result`")
    exp = ns.get("expected_volume")
    exp = float(exp) if isinstance(exp, (int, float)) else None
    if isinstance(r, (list, tuple)):
        r = Compound(list(r))
    if not isinstance(r, Shape):
        raise RuntimeError(f"`result` is a {type(r).__name__}, not a build123d shape")
    solids = r.solids()
    if not solids:
        raise RuntimeError("`result` has no solids (did a cut remove everything, or is it 2D?)")
    valid = r.is_valid() if callable(r.is_valid) else r.is_valid
    if not valid:
        raise RuntimeError("the solid is not valid (self-intersecting or broken geometry)")
    vol = sum(s.volume for s in solids)
    if vol <= 0:
        raise RuntimeError("the solid has zero volume")
    bb = r.bounding_box()
    from build123d import GeomType
    def gt(f):
        g = f.geom_type
        return g() if callable(g) else g
    cyl = sum(1 for f in r.faces() if gt(f) == GeomType.CYLINDER)
    export_step(r, out + ".step")
    export_stl(r, out + ".stl")
    print(json.dumps({"ok": True, "solids": len(solids), "volume_mm3": round(vol, 2),
        "size_mm": [round(bb.size.X, 3), round(bb.size.Y, 3), round(bb.size.Z, 3)],
        "min_mm": [round(bb.min.X, 3), round(bb.min.Y, 3), round(bb.min.Z, 3)],
        "cyl_faces": cyl, "expected_volume": exp}))
except Exception:
    tb = traceback.format_exc().splitlines()
    print(json.dumps({"ok": False, "error": "\n".join(tb[-12:])}))
'''


def load_key():
    key = os.environ.get("CAD_KEY")
    if key:
        return key
    if SECRETS.exists():
        for line in SECRETS.read_text().splitlines():
            m = re.match(r"\s*(?:export\s+)?AIWS_KEY_LAB3=(.*)", line)
            if m:
                return m.group(1).strip().strip("'\"")
    return os.environ.get("AIWS_KEY_LAB3", "")


def chat(messages, args):
    body = {"model": args.model, "messages": messages, "temperature": 0.3,
            "max_tokens": args.max_tokens}
    if not args.think:
        body["chat_template_kwargs"] = {"enable_thinking": False}
    req = urllib.request.Request(
        args.base.rstrip("/") + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + args.key})
    try:
        with urllib.request.urlopen(req, timeout=args.timeout) as r:
            data = json.load(r)
    except urllib.error.HTTPError as e:
        sys.exit(f"cad: the model server said {e.code}: {e.read().decode()[:300]}")
    except (urllib.error.URLError, TimeoutError) as e:
        sys.exit(f"cad: can't reach {args.base} ({e}). On the laptop, lab3 needs "
                 "Tailscale subnet routes: sudo tailscale set --accept-routes")
    msg = data["choices"][0]["message"]
    return msg.get("content") or ""


def extract_code(text):
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)
    blocks = re.findall(r"```(?:python|py)?\s*\n(.*?)```", text, flags=re.S)
    if blocks:
        return max(blocks, key=len).strip() + "\n"
    if "from build123d" in text:
        return text.strip() + "\n"
    return None


def run_script(path, stem, timeout):
    try:
        p = subprocess.run([sys.executable, "-c", RUNNER, str(path), str(stem)],
                           capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"the script took longer than {timeout}s"}
    for line in reversed(p.stdout.strip().splitlines()):
        try:
            return json.loads(line)
        except ValueError:
            continue
    return {"ok": False, "error": (p.stderr or p.stdout or "no output")[-1500:]}


def slug(text):
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return "-".join(s.split("-")[:5]) or "part"


def report(res, outdir):
    sx, sy, sz = res["size_mm"]
    print(f"\n  {res['solids']} solid, {sx} x {sy} x {sz} mm, "
          f"{res['volume_mm3'] / 1000:.2f} cm³")
    print(f"  {outdir / 'part.step'}   <- import this into Onshape")
    print(f"  {outdir / 'part.stl'}")
    print(f"  {outdir / 'part.py'}     <- edit and `cad --run` it, or `cad --edit` it")


def main():
    ap = argparse.ArgumentParser(prog="cad", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("prompt", nargs="*", help="what to make, or what to change with --edit")
    ap.add_argument("-o", "--out", help="output folder (default ~/CAD/<name>)")
    ap.add_argument("--edit", metavar="PART_PY", help="change an existing script")
    ap.add_argument("--run", metavar="PART_PY", help="just run a script and export")
    ap.add_argument("--tries", type=int, default=4)
    ap.add_argument("--base", default=os.environ.get("CAD_BASE_URL", "http://192.168.1.15:8080"))
    ap.add_argument("--model", default=os.environ.get("CAD_MODEL", "marina"))
    ap.add_argument("--max-tokens", type=int, default=12000)
    ap.add_argument("--timeout", type=int, default=600, help="seconds per model reply")
    ap.add_argument("--run-timeout", type=int, default=120, help="seconds per script run")
    ap.add_argument("--no-check", action="store_true",
                    help="skip the expected-volume check")
    ap.add_argument("--think", action="store_true",
                    help="let the model reason first (minutes per try on lab3, rarely better)")
    args = ap.parse_args()
    prompt = " ".join(args.prompt).strip()

    if args.run:
        path = Path(args.run).expanduser().resolve()
        res = run_script(path, path.with_suffix(""), args.run_timeout)
        if not res["ok"]:
            sys.exit("cad: " + res["error"])
        report(res, path.parent)
        return

    if not prompt:
        ap.error("say what to make")
    args.key = load_key()

    if args.edit:
        src = Path(args.edit).expanduser().resolve()
        outdir = src.parent
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": "Here is the current script:\n```python\n"
                     + src.read_text() + "```\nChange it: " + prompt
                     + "\nReply with the whole updated script."}]
    else:
        outdir = Path(args.out).expanduser() if args.out else Path.home() / "CAD" / slug(prompt)
        messages = [{"role": "system", "content": SYSTEM},
                    {"role": "user", "content": prompt}]
    outdir.mkdir(parents=True, exist_ok=True)
    script = outdir / "part.py"

    for attempt in range(1, args.tries + 1):
        t = time.time()
        print(f"[{attempt}/{args.tries}] asking {args.model}...", end="", flush=True)
        reply = chat(messages, args)
        code = extract_code(reply)
        print(f" {time.time() - t:.0f}s", end="", flush=True)
        if not code:
            print(", no code in the reply" + (" (reasoning ran out of tokens; next try skips it)"
                                              if args.think else ""))
            args.think = False
            messages += [{"role": "assistant", "content": reply},
                         {"role": "user", "content": "Reply with the script in one ```python block."}]
            continue
        script.write_text(code)
        res = run_script(script, outdir / "part", args.run_timeout)
        if res["ok"] and not args.no_check:
            exp, vol = res.get("expected_volume"), res["volume_mm3"]
            if exp is None:
                res = {"ok": False, "error": "the script must set expected_volume (see the rules)"}
            elif exp <= 0 or abs(vol - exp) / exp > 0.04:
                sx, sy, sz = res["size_mm"]
                res = {"ok": False, "error": (
                    f"Volume check failed: the part is {vol:.0f} mm³ but expected_volume is "
                    f"{exp:.0f} mm³ ({(vol - exp) / exp:+.0%}). Bounding box {sx} x {sy} x {sz} mm. "
                    "Usually a hole or cut misses the material or is the wrong size "
                    "(diameter used as radius, or radius as diameter), or a feature faces "
                    "the wrong way. Re-check every feature against the request, and recompute "
                    "expected_volume from the request's own numbers.")}
        if res["ok"]:
            print(", built")
            (outdir / "prompt.txt").open("a").write(
                ("edit: " if args.edit else "") + prompt + "\n")
            report(res, outdir)
            return
        err = res["error"]
        print(", failed: " + err.strip().splitlines()[-1][:120])
        messages += [{"role": "assistant", "content": "```python\n" + code + "```"},
                     {"role": "user", "content": "Running it failed:\n```\n" + err
                      + "\n```\nFix the script. Reply with the whole script."}]
    sys.exit(f"cad: gave up after {args.tries} tries; the last script is in {script}")


if __name__ == "__main__":
    main()
