#!/bin/sh
# Bench each trial model as soon as its download has finished.
cd /root/bench
export KEY=$(grep -A1 apiKeys: /opt/llama-swap/config.yaml | tail -1 | tr -d ' "-' | cut -d# -f1)
for pair in test-designant:test-designant-Q4_K_M.gguf test-qwen3-instruct:test-qwen3-30b-instruct-2507-Q4_K_M.gguf; do
  m=${pair%%:*}; f=/models/${pair#*:}
  while [ ! -f "$f" ]; do sleep 30; done
  echo "== $(date +%T) bench $m"
  python3 -I /root/bench/bench.py "$m" 2
  [ "$m" = test-rpr ] && THINK=1 python3 -I /root/bench/bench.py "$m" 2
done
echo "== AUTOBENCH DONE"
