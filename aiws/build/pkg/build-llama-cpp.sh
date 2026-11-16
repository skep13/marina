#!/usr/bin/env bash
# Build llama.cpp (Vulkan) at a pinned commit into llama-cpp-vulkan_<ver>_amd64.deb.
# Portable: CPU code is built for every x86-64 level and picked at runtime,
# so the same .deb runs in a VM and on the Ryzen.
#
#   build/pkg/build-llama-cpp.sh OUTDIR
set -euo pipefail
source "$(dirname "$0")/../versions.env"
OUT=${1:?outdir}
WORK=${WORK:-/var/tmp/aiws-pkg}
mkdir -p "$OUT" "$WORK"

export DEBIAN_FRONTEND=noninteractive
apt-get install -y -qq build-essential clang cmake ninja-build git libvulkan-dev glslc spirv-headers \
  libssl-dev pkg-config >/dev/null

src=$WORK/llama.cpp
if [ ! -d "$src/.git" ]; then
  git clone -q https://github.com/ggml-org/llama.cpp "$src"
fi
git -C "$src" fetch -q origin
git -C "$src" checkout -q "$LLAMA_CPP_COMMIT"
ver="0.$(git -C "$src" rev-list --count HEAD).$(git -C "$src" rev-parse --short=7 HEAD)"

# Clang: GCC needs >2.5 GB for the generated Vulkan shader arrays
# (mul_mm.comp.cpp); Clang compiles them in a fraction of that.
cmake -S "$src" -B "$WORK/llama-build" -G Ninja \
  -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ \
  -DCMAKE_BUILD_TYPE=Release -DCMAKE_INSTALL_PREFIX=/usr/lib/llama-cpp-vulkan \
  -DCMAKE_INSTALL_RPATH=/usr/lib/llama-cpp-vulkan/lib \
  -DGGML_VULKAN=ON -DGGML_NATIVE=OFF -DGGML_BACKEND_DL=ON -DGGML_CPU_ALL_VARIANTS=ON \
  -DLLAMA_BUILD_TESTS=OFF -DLLAMA_BUILD_EXAMPLES=OFF -DLLAMA_BUILD_SERVER=ON \
  -DLLAMA_CURL=OFF >/dev/null
# The Vulkan shader sources need ~900 MB per compiler; keep jobs low on small hosts.
cmake --build "$WORK/llama-build" -j"${JOBS:-2}"

root=$WORK/llama-root
rm -rf "$root"
DESTDIR=$root cmake --install "$WORK/llama-build" >/dev/null
rm -rf "$root/usr/lib/llama-cpp-vulkan/include" "$root/usr/lib/llama-cpp-vulkan/lib/cmake" \
       "$root/usr/lib/llama-cpp-vulkan/lib/pkgconfig"
mkdir -p "$root/usr/bin" "$root/DEBIAN"
for b in llama-server llama-bench llama-cli llama-quantize llama-gguf-split; do
  [ -e "$root/usr/lib/llama-cpp-vulkan/bin/$b" ] && ln -sf "/usr/lib/llama-cpp-vulkan/bin/$b" "$root/usr/bin/$b"
done
cat > "$root/DEBIAN/control" <<EOF
Package: llama-cpp-vulkan
Version: $ver
Architecture: amd64
Maintainer: AIWS <aiws@localhost>
Depends: libvulkan1, mesa-vulkan-drivers, libgomp1, libssl3t64
Description: llama.cpp built for AIWS (Vulkan, runtime CPU dispatch)
 Commit $LLAMA_CPP_COMMIT.
EOF
dpkg-deb --root-owner-group -Zxz --build "$root" "$OUT/llama-cpp-vulkan_${ver}_amd64.deb"
echo "$OUT/llama-cpp-vulkan_${ver}_amd64.deb"
