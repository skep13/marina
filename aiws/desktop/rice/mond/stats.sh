#!/bin/bash
# Mond clock stats on Linux -> "cpu|ram|gpu|disk|bat" (percent each).
# The Mac's Übersicht stats.sh has the same fields minus GPU. CPU is the busy share since
# the previous call (the widget asks every 2 s), kept in a small state file.
state="${XDG_RUNTIME_DIR:-/tmp}/mond-clock.cpu"

read -r _ u n s i w q sq st _ < /proc/stat
busy=$((u + n + s + q + sq + st)); total=$((busy + i + w))
cpu=0
if [ -f "$state" ]; then
  read -r pb pt < "$state"
  dt=$((total - pt))
  [ "$dt" -gt 0 ] && cpu=$(( (busy - pb) * 100 / dt ))
fi
echo "$busy $total" > "$state"

ram=$(awk '/MemTotal/{t=$2} /MemAvailable/{a=$2} END {printf "%d", (t-a)*100/t}' /proc/meminfo)
disk=$(df -P / | awk 'NR==2 {gsub(/%/,"",$5); print $5}')

bat=100
for b in /sys/class/power_supply/BAT*/capacity; do
  [ -r "$b" ] && { bat=$(cat "$b"); break; }
done

# NVIDIA GPU load, without waking a sleeping card: nvidia-smi would power it
# up every 2 s and drain the battery, so a suspended card just reads 0.
gpu=0
for d in /sys/bus/pci/devices/*; do
  [ "$(cat "$d/vendor" 2>/dev/null)" = 0x10de ] || continue
  case "$(cat "$d/class")" in 0x03*) ;; *) continue ;; esac
  if [ "$(cat "$d/power/runtime_status" 2>/dev/null)" = active ] && command -v nvidia-smi >/dev/null; then
    gpu=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -dc 0-9)
  fi
  break
done

printf '%s|%s|%s|%s|%s\n' "$cpu" "$ram" "${gpu:-0}" "$disk" "$bat"
