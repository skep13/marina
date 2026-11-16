#!/usr/bin/env bash
# Build the the AI workstation ISO. Runs on a Debian 13 host (the quay-build container
# on lab2) as root:
#
#   ./build.sh                 dev build from deb.debian.org
#   REPRODUCIBLE=1 ./build.sh  release build from snapshot.debian.org
#
# Output: out/<ISO_NAME>-<date>-amd64.iso + .packages manifest + sha256.
set -euo pipefail
cd "$(dirname "$0")"
. ./versions.env
. ./image.env
here=$(pwd)
debs=${DEBS:-/srv/aiws/debs}
work=${WORK:-/srv/aiws/lb}
mkdir -p out "$debs" "$work"
work=$(readlink -f "$work")  # the mount table shows real paths

# Pinned build date, so file times inside the image don't vary.
export SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-$(git -C "$here/.." log -1 --format=%ct 2>/dev/null || date -u +%s)}

# Our own packages.
# A llama.cpp package from before the rename: repackage it rather than
# spend an hour recompiling (new prefix, fixed RPATH, new package name).
old=$(ls "$debs"/quay-llama-cpp_*.deb 2>/dev/null | head -1 || true)
if [ -n "$old" ] && [ -z "$(ls "$debs"/llama-cpp-vulkan_*.deb 2>/dev/null)" ]; then
  apt-get install -y -qq patchelf file >/dev/null
  t=$(mktemp -d)
  dpkg-deb -R "$old" "$t"
  mv "$t/usr/lib/quay/llama.cpp" "$t/usr/lib/llama-cpp-vulkan" && rmdir "$t/usr/lib/quay"
  for l in "$t"/usr/bin/*; do ln -sf "/usr/lib/llama-cpp-vulkan/bin/$(basename "$l")" "$l"; done
  find "$t/usr/lib/llama-cpp-vulkan" -type f \( -perm -u+x -o -name '*.so*' \) -exec sh -c \
    'file -b "$1" | grep -q ELF && patchelf --set-rpath /usr/lib/llama-cpp-vulkan/lib "$1"' _ {} \;
  sed -i 's/^Package: .*/Package: llama-cpp-vulkan/; s/built for Quay/built for the AI workstation/' "$t/DEBIAN/control"
  ver=$(sed -n 's/^Version: //p' "$t/DEBIAN/control")
  dpkg-deb --root-owner-group -Zxz --build "$t" "$debs/llama-cpp-vulkan_${ver}_amd64.deb" >/dev/null
  rm -rf "$t" "$old"
fi
[ -n "$(ls "$debs"/llama-cpp-vulkan_*.deb 2>/dev/null)" ] || pkg/build-llama-cpp.sh "$debs"
rm -f "$debs"/quay-llama-swap_*.deb "$debs"/quay-core_*.deb
[ -n "$(ls "$debs"/llama-swap_*.deb 2>/dev/null)" ] || pkg/build-llama-swap.sh "$debs"
rm -f "$debs"/aiws-core_*.deb
pkg/build-aiws-core.sh "$debs"

# A clean live-build tree each time; the package cache survives in $work/cache.
rsync -a --delete --exclude cache --exclude chroot --exclude binary \
  --exclude '.build' "$here/auto" "$here/config" "$here/versions.env" "$here/image.env" "$work/"
cd "$work"
mkdir -p config/packages.chroot
cp "$debs"/llama-cpp-vulkan_*.deb "$debs"/llama-swap_*.deb "$debs"/aiws-core_*.deb config/packages.chroot/
# VSCodium as a pinned local package (fetched on this host, checksum
# verified), not a third-party apt repo inside the image build.
codium="$debs/vendor/codium_${CODIUM_VERSION}_amd64.deb"
if [ ! -f "$codium" ]; then
  mkdir -p "$debs/vendor"
  curl -fsSL -o "$codium" \
    "https://github.com/VSCodium/vscodium/releases/download/${CODIUM_VERSION}/codium_${CODIUM_VERSION}_amd64.deb"
fi
echo "$CODIUM_SHA256  $codium" | sha256sum -c --quiet
cp "$codium" config/packages.chroot/
rm -f config/archives/vscodium.*

# A failed build can leave proc/sys/dev mounted inside the chroot. Unmount
# them first, and never delete across a mount, so cleanup stays in $work.
mount | awk -v w="$work/chroot" 'index($3, w) == 1 {print $3}' | sort -r | xargs -r -n1 umount -l
rm -rf --one-file-system chroot binary .build
# Keep the package cache between builds (lb clean, not --purge).
lb clean >/dev/null 2>&1 || true
lb config
lb build

iso=$(ls -1 *.hybrid.iso | head -1)
name="${ISO_NAME}-$(date -u -d @"$SOURCE_DATE_EPOCH" +%Y%m%d)-amd64"
mv "$iso" "$here/out/$name.iso"
cp chroot.packages.live "$here/out/$name.packages" 2>/dev/null || true
(cd "$here/out" && sha256sum "$name.iso" > "$name.iso.sha256")
ls -lh "$here/out/$name.iso"
