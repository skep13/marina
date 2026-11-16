#!/bin/sh
# usage: runbench.sh model [model...]  (runs in order, logs to /root/bench/run.log)
cd /root/bench
export KEY=$(grep -A1 apiKeys: /opt/llama-swap/config.yaml | tail -1 | tr -d ' "-' | cut -d# -f1)
for m in "$@"; do python3 -I /root/bench/bench.py "$m" 2; done
echo "== BENCH DONE $*"
