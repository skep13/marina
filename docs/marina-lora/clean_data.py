"""Thin out her verbal tics before training, so the adapter doesn't learn them.

The generator copies the live model, tics included: "actually" in ~43% of her
replies and an *action* in ~98%. Trained on as-is, an adapter would make both
stickier. This walks the data in order and, once a crutch word is over its
share of replies, deletes it (the sentence still reads fine without it), and
once actions are over their share, or one action is worn out, drops the action.

  python clean_data.py in.jsonl [more.jsonl ...] > data.jsonl
"""
import collections
import json
import re
import sys

CRUTCH = ("actually", "honestly", "literally", "lowkey", "genuinely")
CRUTCH_SHARE = 0.05          # of her replies may keep each crutch word
ACTION_SHARE = 0.85          # of her replies may keep an *action* (the owner likes them)
ONE_ACTION_SHARE = 0.03      # of her replies may use the same action
WARMUP = 30                  # replies before the shares apply
LONG_WORDS = 60              # replies longer than this stay as context but aren't trained on

ACTION = re.compile(r"\*([^*\n]+)\*")
crutch_re = {w: re.compile(rf"\b({w})\b,?\s*(\w?)", re.I) for w in CRUTCH}


def _cut(m):
    # "Actually, it was" -> "It was": the capital moves to the next word
    nxt = m.group(2)
    return nxt.upper() if m.group(1)[0].isupper() else nxt


def tidy(text):
    text = re.sub(r"[ \t]+([,!?]|\.(?!\.))", r"\1", text)   # not before "..."
    text = re.sub(r",\s*([.!?])", r"\1", text)
    text = re.sub(r"(^|[.!?]\s+|\n)\s*,\s*", r"\1", text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    text = re.sub(r"[ \t]+\n", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


class Cleaner:
    def __init__(self):
        self.n = 0
        self.words = collections.Counter()
        self.with_action = 0
        self.actions = collections.Counter()
        self.changes = collections.Counter()

    def __call__(self, text):
        warm = self.n >= WARMUP
        for w, rx in crutch_re.items():
            if rx.search(text):
                if warm and self.words[w] >= CRUTCH_SHARE * self.n:
                    text = rx.sub(_cut, text)
                    self.changes[f"dropped {w}"] += 1
                else:
                    self.words[w] += 1
        acts = [a.strip().lower() for a in ACTION.findall(text)]
        if acts:
            over_all = warm and self.with_action >= ACTION_SHARE * self.n
            for a in acts:
                if over_all or (warm and self.actions[a] >= ONE_ACTION_SHARE * self.n):
                    stripped = tidy(re.sub(r"\*" + re.escape(a) + r"\*", "", text, count=1, flags=re.I))
                    if ACTION.sub("", stripped).strip():      # never leave her wordless
                        text = stripped
                        self.changes["dropped action"] += 1
                        continue
                self.actions[a] += 1
            if ACTION.search(text):
                self.with_action += 1
        self.n += 1
        return tidy(text)


def main():
    clean = Cleaner()
    rows = dropped = long_ = 0
    for path in sys.argv[1:]:
        for line in open(path):
            if not line.strip():
                continue
            rec = json.loads(line)
            if rec.get("tool_right") is False:        # wrong tool, or none: don't teach it
                dropped += 1
                continue
            for m in rec["messages"]:
                if m["role"] == "assistant" and m.get("content") and not m.get("tool_calls"):
                    m["content"] = clean(m["content"])
                    if len(ACTION.sub("", m["content"]).split()) > LONG_WORDS:
                        m["train"] = False
                        long_ += 1
            print(json.dumps(rec, ensure_ascii=False))
            rows += 1
    share = {w: f"{clean.words[w] / max(1, clean.n):.0%}" for w in CRUTCH}
    print(f"{rows} conversations, {clean.n} replies; kept {share}; "
          f"actions in {clean.with_action / max(1, clean.n):.0%}; {dict(clean.changes)}; "
          f"dropped {dropped} wrong-tool conversations; {long_} long replies not trained",
          file=sys.stderr)


if __name__ == "__main__":
    main()
