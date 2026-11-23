import json,sys,glob,statistics as st
for f in sorted(glob.glob(sys.argv[1]+"/*.json")):
    d=json.load(open(f)); T=[t for r in d["runs"] for t in r["turns"]]
    n=len(T); ok=[t for t in T if not t["reply"].startswith("[ERROR")]
    pct=lambda k: 100*sum(1 for t in ok if t[k])/max(1,len(ok))
    ops=[t["opener"] for t in ok]; dup=len(ops)-len(set(ops))
    tps=[t["tps"] for t in ok if t.get("tps")]
    print(f'{d["model"]:22} n={n} err={n-len(ok)} words={st.median([t["words"] for t in ok]):.0f} endQ={pct("ends_q"):.0f}% assistanty={pct("assistanty"):.0f}% emoji={pct("emoji"):.0f}% md={pct("markdown"):.0f}% longAct={pct("long_action"):.0f}% actOnly={pct("action_only"):.0f}% dupOpeners={dup} tok/s={st.median(tps) if tps else 0:.1f} secs={st.median([t["secs"] for t in ok]):.1f}')
    if d.get("tools"):
        tl=d["tools"]; good=sum(1 for t in tl if t["ok"])
        print(f'{"":22} tools {good}/{len(tl)} right, first reply {d.get("first_reply_secs")}s, '
              f'tool secs={st.median([t["secs"] for t in tl]):.1f}')
