#!/bin/sh
# Push the Kaggle notebook with docs/marina-lora/gen.py embedded in it, so the
# run never picks up a stale copy from the dataset.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$(mktemp -d)
cp "$HERE/kernel-metadata.json" "$OUT/"
python3 - "$HERE/gen_kaggle.py" "$HERE/../gen.py" "$OUT/gen_kaggle.py" <<'PY'
import sys
src, gen, out = sys.argv[1:]
s = open(src).read()
marker = "GEN_SRC = None"
assert marker in s
s = s.replace(marker, "GEN_SRC = " + repr(open(gen).read()), 1)
compile(s, out, "exec")
open(out, "w").write(s)
PY
~/.venvs/kaggle/bin/kaggle kernels push -p "$OUT"
rm -rf "$OUT"
