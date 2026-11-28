#!/bin/sh
# Pull lab3's real-chat pairs into picker/pairs.json. Prints the count.
cd "$(dirname "$0")"
ssh -o BatchMode=yes root@192.168.1.13 "pct exec 110 -- cat /root/marina-lora/pairs-v2.jsonl" 2>/dev/null > pairs-v2.jsonl.new &&
  [ -s pairs-v2.jsonl.new ] && mv pairs-v2.jsonl.new pairs-v2.jsonl
python3 -I -c "
import json
rows=[json.loads(l) for l in open('pairs-v2.jsonl') if l.strip()]
open('picker/pairs.json','w').write('[\n'+',\n'.join(json.dumps(r,ensure_ascii=False) for r in rows)+'\n]\n'); print(len(rows))"
