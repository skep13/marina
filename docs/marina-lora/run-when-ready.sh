#!/bin/sh
# Wait for the dataset runs (lab3 and the Kaggle T4 notebook) to finish, clean
# her tics out of the merged data, then train on Modal and fetch the adapter.
# Run from the Mac; the Mac must stay awake and on the home LAN.
set -u
HERE=$(cd "$(dirname "$0")" && pwd)
MODAL=~/.venvs/modal/bin/modal
KAGGLE=~/.venvs/kaggle/bin/kaggle
KERNEL=skype13/marina-lora-gen-t4
MAX_CONVOS=${MAX_CONVOS:-2600}      # ~2 h on the H100, well inside the $30 limit
KAGGLE_GRACE=${KAGGLE_GRACE:-14400} # wait up to 4 h after lab3 for Kaggle
LAB3="ssh -o ConnectTimeout=10 -o BatchMode=yes root@192.168.1.13"
cd "$HERE"

echo "$(date +%T) waiting for marina-lora-gen on lab3"
while :; do
  state=$($LAB3 'pct exec 110 -- systemctl is-active marina-lora-gen' </dev/null 2>/dev/null)
  case "$state" in
    active|activating) sleep 600 ;;
    "") echo "$(date +%T) lab3 not answering, retrying"; sleep 300 ;;
    *) break ;;
  esac
done
echo "$(date +%T) generator is $state; last log lines:"
$LAB3 'pct exec 110 -- tail -2 /root/marina-lora/gen.log' </dev/null 2>/dev/null

$LAB3 'pct exec 110 -- cat /root/marina-lora/data.jsonl' </dev/null 2>/dev/null > data-lab3.jsonl.new &&
  $LAB3 'pct exec 110 -- cat /root/marina-lora/snapshot.json' </dev/null 2>/dev/null > snapshot.json &&
  mv data-lab3.jsonl.new data-lab3.jsonl || { echo "copy from lab3 failed"; exit 1; }
echo "$(date +%T) lab3: $(wc -l < data-lab3.jsonl) conversations"

# Kaggle: wait while it runs (bounded), then take whatever it wrote.
deadline=$(( $(date +%s) + KAGGLE_GRACE ))
while :; do
  ks=$($KAGGLE kernels status $KERNEL 2>/dev/null | sed 's/.*KernelWorkerStatus\.//; s/".*//')
  case "$ks" in
    RUNNING|QUEUED|"")    # "" = the status check itself failed; ask again
      [ "$(date +%s)" -ge "$deadline" ] && { echo "$(date +%T) Kaggle still $ks; going without it"; break; }
      sleep 600 ;;
    *) break ;;
  esac
done
echo "$(date +%T) Kaggle notebook is ${ks:-unknown}"
rm -rf kaggle-out && mkdir kaggle-out
$KAGGLE kernels output $KERNEL -p kaggle-out >/dev/null 2>&1
[ -s kaggle-out/data-kaggle.jsonl ] && echo "$(date +%T) Kaggle: $(wc -l < kaggle-out/data-kaggle.jsonl) conversations" \
  || echo "$(date +%T) no Kaggle data; lab3 data only"

# Merge, keep at most MAX_CONVOS, and thin out her tics.
cat data-lab3.jsonl kaggle-out/data-kaggle.jsonl 2>/dev/null | grep . |
  python3 -c "import random,sys; l=sys.stdin.readlines(); random.Random(0).shuffle(l); sys.stdout.writelines(l[:$MAX_CONVOS])" > merged.jsonl
python3 clean_data.py merged.jsonl > data.jsonl || { echo "cleaning failed"; exit 1; }
echo "$(date +%T) $(wc -l < data.jsonl) conversations after cleaning; starting Modal training"

$MODAL run modal_train.py::main || { echo "training failed"; exit 1; }
$MODAL volume get --force marina-lora out/marina-voice-f16.gguf "$HERE/marina-voice-f16.gguf" &&
  echo "$(date +%T) == ADAPTER READY: $HERE/marina-voice-f16.gguf"
