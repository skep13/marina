#!/usr/bin/env bash
# Repackage the pinned llama-swap release binary as llama-swap.
set -euo pipefail
source "$(dirname "$0")/../versions.env"
OUT=${1:?outdir}
v=$LLAMA_SWAP_VERSION
tmp=$(mktemp -d); trap 'rm -rf "$tmp"' EXIT
curl -fsSL -o "$tmp/ls.tgz" \
  "https://github.com/mostlygeek/llama-swap/releases/download/v$v/llama-swap_${v}_linux_amd64.tar.gz"
got=$(sha256sum "$tmp/ls.tgz" | cut -d' ' -f1)
if [ -n "${LLAMA_SWAP_SHA256:-}" ] && [ "$got" != "$LLAMA_SWAP_SHA256" ]; then
  echo "llama-swap checksum mismatch: $got" >&2; exit 1
fi
echo "llama-swap v$v sha256 $got"
mkdir -p "$tmp/root/usr/bin" "$tmp/root/DEBIAN"
tar -xzf "$tmp/ls.tgz" -C "$tmp" llama-swap
install -m 755 "$tmp/llama-swap" "$tmp/root/usr/bin/llama-swap"
cat > "$tmp/root/DEBIAN/control" <<CTL
Package: llama-swap
Version: $v
Architecture: amd64
Maintainer: AIWS <aiws@localhost>
Description: llama-swap model switcher (upstream release v$v, repackaged)
CTL
dpkg-deb --root-owner-group --build "$tmp/root" "$OUT/llama-swap_${v}_amd64.deb" >/dev/null
echo "$OUT/llama-swap_${v}_amd64.deb"
