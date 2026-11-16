#!/bin/bash
# Make CachyOS's installer launcher add our install step (shellprocess@aiws)
# to whatever installer version it downloads, just before CachyOS's own
# final cleanup. If the insertion doesn't take, it falls back to the stock
# settings, so installing always works.
#   patch-launcher.sh path/to/airootfs/usr/local/bin/calamares-online.sh
set -euo pipefail
f=${1:?launcher}
old='    sudo cp "/usr/share/calamares/settings_${mode}.conf" /etc/calamares/settings.conf'
grep -qF "$old" "$f" || { echo "launcher changed upstream; patch by hand" >&2; exit 1; }
python3 - "$f" <<'PY'
import sys, pathlib
p = pathlib.Path(sys.argv[1]); s = p.read_text()
old = '    sudo cp "/usr/share/calamares/settings_${mode}.conf" /etc/calamares/settings.conf'
new = r'''    # AI workstation: our step (shellprocess@aiws) before CachyOS's cleanup
    awk '/^instances:/ {print; print "- id:       aiws"; print "  module:   shellprocess"; print "  config:   shellprocess_aiws.conf"; next}
         /^  - shellprocess@cleanup_calamares/ {print "  - shellprocess@aiws"}
         {print}' "/usr/share/calamares/settings_${mode}.conf" | sudo tee /etc/calamares/settings.conf >/dev/null
    if ! grep -q 'shellprocess@aiws' /etc/calamares/settings.conf; then
        echo "aiws: couldn't add the install step; installing plain CachyOS" >> "$log"
        sudo cp "/usr/share/calamares/settings_${mode}.conf" /etc/calamares/settings.conf
    fi'''
p.write_text(s.replace(old, new))
PY
echo "patched $f"
