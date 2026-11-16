#!/bin/bash
# Build the laptop ISO: CachyOS's own desktop ISO, plus our package repo, the
# installer step that adds the AI workstation, and the Miku assets.
# Runs as root on an Arch build machine with the CachyOS repos configured
# (lab2 ct122). Output: out/cachyos-aiws-<date>.iso, for a Ventoy stick.
#
#   AUR_MODE=source  ./build-iso.sh    build Caelestia & co. from AUR PKGBUILDs here
#   AUR_MODE=chaotic ./build-iso.sh    take prebuilt binaries from Chaotic-AUR
#
# The ISO holds your wallpaper and fonts: keep it private, don't publish it.
set -euo pipefail
here=$(cd "$(dirname "$0")" && pwd)
aiws=$(dirname "$here")
W=${WORK:-/srv/aiws-iso}
CACHYOS_ISO_COMMIT=3215497            # CachyOS-Live-ISO, 2026-10-03
OHMYZSH_REF=master
CAELESTIA_DOTS_REF=b476a36            # dots, 2026-10-27
# Dependency order. quickshell-git is the real Quickshell Caelestia is written
# for (CachyOS's noctalia-qs only stands in for it); pacman prefers the exact name.
AUR_PKGS=(python-materialyoucolor caelestia-cli libcava qt6-m3shapes-git ttf-rubik-vf
          quickshell-git caelestia-shell)
: "${AUR_MODE:?set AUR_MODE=source or AUR_MODE=chaotic}"

mkdir -p "$W" && cd "$W"
id builder >/dev/null 2>&1 || { useradd -m builder; echo 'builder ALL=(ALL) NOPASSWD: /usr/bin/pacman' > /etc/sudoers.d/builder; }
repo=$W/opt/aiws/repo
rm -rf "$W/opt" && mkdir -p "$repo" "$W/opt/aiws/tree/vendor"

echo "== our packages"
rsync -a --delete --exclude __pycache__ --exclude companion/frames "$aiws/" "$W/src/"
chown -R builder: "$W/src"
for p in laptop/llama-swap laptop/aiws-core iso/pkg/aiws-laptop; do
  (cd "$W/src/$p" && runuser -u builder -- makepkg -f --nodeps --noconfirm -c >/dev/null)
  cp "$W/src/$p"/*.pkg.tar.zst "$repo/"
done

echo "== AUR packages ($AUR_MODE)"
case $AUR_MODE in
  chaotic)
    pacman -Sw --noconfirm --cachedir "$repo" "${AUR_PKGS[@]}" ;;
  source)
    mkdir -p "$W/aur" && chown builder: "$W/aur"
    for p in "${AUR_PKGS[@]}"; do      # listed in build order (deps first)
      d=$W/aur/$p
      [ -d "$d" ] || runuser -u builder -- git clone -q "https://aur.archlinux.org/$p.git" "$d"
      # two compile jobs: lab2 is small
      (cd "$d" && runuser -u builder -- env MAKEFLAGS=-j2 CMAKE_BUILD_PARALLEL_LEVEL=2 \
        makepkg -s -f --noconfirm -c && pacman -U --noconfirm --needed ./*.pkg.tar.zst) \
        > "$W/aur/$p.log" 2>&1 || { echo "!! $p failed: $W/aur/$p.log"; tail -20 "$W/aur/$p.log"; exit 1; }
      echo "   built $p"
      cp "$d"/*.pkg.tar.zst "$repo/"
    done ;;
  *) echo "AUR_MODE must be source or chaotic" >&2; exit 2 ;;
esac
rm -f "$repo"/*.sig
repo-add -q "$repo/aiws.db.tar.gz" "$repo"/*.pkg.tar.zst

echo "== setup files, vendored dotfiles, assets"
mkdir -p "$W/opt/aiws/tree/desktop"
cp -r "$aiws/desktop/rice" "$aiws/desktop/firstlogin.sh" "$W/opt/aiws/tree/desktop/"
rm -f "$W/opt/aiws/tree/desktop/rice/miku-assets.tar.gz"
git clone -q --depth 1 -b "$OHMYZSH_REF" https://github.com/ohmyzsh/ohmyzsh "$W/opt/aiws/tree/vendor/ohmyzsh"
git clone -q https://github.com/caelestia-dots/caelestia "$W/opt/aiws/tree/vendor/caelestia-dots"
git -C "$W/opt/aiws/tree/vendor/caelestia-dots" checkout -q "$CAELESTIA_DOTS_REF"
rm -rf "$W/opt/aiws/tree/vendor/"*/.git
cp "$aiws/desktop/rice/miku-assets.tar.gz" "$W/opt/aiws/miku-assets.tar.gz"

echo "== CachyOS ISO profile + our overlay"
[ -d "$W/cachyos-iso/.git" ] || git clone -q https://github.com/CachyOS/CachyOS-Live-ISO "$W/cachyos-iso"
git -C "$W/cachyos-iso" checkout -q -f "$CACHYOS_ISO_COMMIT"
air=$W/cachyos-iso/archiso/airootfs
cp -a "$here/overlay/." "$air/"
mkdir -p "$air/opt" && cp -a "$W/opt/aiws" "$air/opt/"
"$here/patch-launcher.sh" "$air/usr/local/bin/calamares-online.sh"
prof=$W/cachyos-iso/archiso/profiledef.sh
grep -q aiws-install-target "$prof" || sed -i 's|^  \["/usr/local/bin/pkexec-wrapper"\]="0:0:755"|&\n  ["/usr/local/bin/aiws-install-target"]="0:0:755"|' "$prof"
sed -i 's/^iso_name=.*/iso_name="cachyos-aiws"/' "$prof"

echo "== build"
cd "$W/cachyos-iso"
./buildiso.sh -p desktop -v -w
ls -lh "$W/cachyos-iso/out/"*.iso
