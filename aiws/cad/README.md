# cad: text to STEP for Onshape

Describe a part, and lab3's model (Qwen3.6-35B-A3B through llama-swap) writes
a [build123d](https://build123d.readthedocs.io) script for it. The script then
runs locally and the part is exported as STEP and STL. If the script fails or
the solid is invalid, the error goes back to the model, which tries again (4 tries by default).

```
cad "60x40x5 mm plate, 3 mm corner fillets, four M4 clearance holes 6 mm in"
cad --edit ~/CAD/<name>/part.py "make it 8 mm thick"
cad --run  ~/CAD/<name>/part.py      # after editing the script by hand
```

Output goes in `~/CAD/<name>/`: `part.py`, `part.step`, `part.stl`, `prompt.txt`.
In Onshape, click **Import** and choose `part.step`.

Install (per user, needs `uv`): `bash aiws/cad/install.sh`. This creates a Python 3.12 venv in
`~/.local/share/aiws/cad/` and adds the `~/.local/bin/cad` launcher.

Settings: `CAD_BASE_URL` (default `http://192.168.1.15:8080`), `CAD_MODEL` (`marina`),
`CAD_KEY` (falls back to `AIWS_KEY_LAB3` in `~/.config/aiws/etc/secrets.env`).
Away from home the laptop reaches lab3 through Tailscale's subnet route, which
must be accepted once: `sudo tailscale set --accept-routes`.

Each script must set `expected_volume` from the request's numbers, and any part
more than 4% off is rejected and retried (`--no-check` skips this). The model's
thinking is off by default: with it on (`--think`), each reply takes 2–8 minutes
on the 780M and isn't more accurate.

Tested: flat plates with holes come out right. L-brackets and other parts with
features in more than one direction usually come out sideways or with holes
missing the material, and the volume check doesn't always catch it, so check
those in Onshape and fix them in `part.py`. Give exact dimensions and say where
each feature goes.
