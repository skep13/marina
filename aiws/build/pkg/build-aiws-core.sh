#!/usr/bin/env bash
# Package AIWS's own software (aiwsd, the CLI, the assistant, desktop glue,
# tools) as aiws-core_<ver>_all.deb.
#   build/pkg/build-aiws-core.sh OUTDIR       (run from anywhere)
set -euo pipefail
here=$(cd "$(dirname "$0")/../.." && pwd)
OUT=${1:?outdir}
ver=${AIWS_VERSION:-0.1.0~$(date -u +%Y%m%d%H%M)}
root=$(mktemp -d)
trap 'rm -rf "$root"' EXIT
cp -a "$here/pkg/aiws-core/." "$root/"
install -d "$root/usr/lib/python3/dist-packages"
rsync -a --exclude __pycache__ "$here/src/aiws" "$root/usr/lib/python3/dist-packages/"
install -m 755 "$here/tools/ai-bench" "$here/tools/ai-mem" "$root/usr/bin/"
install -d "$root/usr/share/aiws"
rsync -a "$here/examples" "$root/usr/share/aiws/"
install -d "$root/usr/share/doc/aiws-core"
cp "$here/docs/"*.md "$root/usr/share/doc/aiws-core/"
cat > "$root/DEBIAN/control" <<CTL
Package: aiws-core
Version: $ver
Architecture: all
Maintainer: AIWS <aiws@localhost>
Depends: python3 (>= 3.11), python3-fastapi, python3-uvicorn, python3-httpx, python3-yaml,
 python3-gi, gir1.2-gtk-3.0, gir1.2-webkit2-4.1, python3-pyatspi, at-spi2-core,
 xdotool, x11-utils, xclip, maim, tmux, openssh-client, adduser, llama-cpp-vulkan, llama-swap
Recommends: podman, distrobox, i3blocks, vulkan-tools
Description: AIWS workstation core: model gateway, projects, assistant, jobs
 aiwsd serves one authenticated OpenAI-compatible API over every model,
 restores project workspaces, runs jobs on homelab workers and hosts the
 AI Control Centre.
CTL
printf '/etc/aiws/aiws.yaml\n' > "$root/DEBIAN/conffiles"
[ -f "$root/etc/aiws/aiws.yaml" ] || sed -i '/aiws.yaml/d' "$root/DEBIAN/conffiles"
[ -s "$root/DEBIAN/conffiles" ] || rm "$root/DEBIAN/conffiles"
dpkg-deb --root-owner-group -Zxz --build "$root" "$OUT/aiws-core_${ver}_all.deb" >/dev/null
echo "$OUT/aiws-core_${ver}_all.deb"
