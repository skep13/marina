import sqlite3, json, time
DB = "/var/lib/open-webui/webui.db"
db = sqlite3.connect(DB); c = db.cursor()
u = c.execute("select id from user where role='admin' limit 1").fetchone()
m = c.execute("select id, meta from model where id='songbird'").fetchone()
assert u and m, "DB missing admin/model - aborting"
uid = u[0]
print("integrity OK: admin=%s" % uid[:8])
content = open("/tmp/kali_tool.py").read()
tid = "songbird_kali"
specs = [{
    "name": "run_on_kali",
    "description": ("Run a single command on the operator's isolated Kali box and return its "
                    "output. Use this when a task needs a Kali security tool. Recon tools run "
                    "immediately; offensive tools require the operator to approve first. Decide "
                    "from intent - the operator should not have to name the tool."),
    "parameters": {"type": "object", "properties": {
        "command": {"type": "string", "description": "the exact command line to run (no shell pipes or chaining)"}},
        "required": ["command"]}
}]
meta = {"description": "Run approval-gated commands on the isolated Kali box.",
        "manifest": {"title": "Songbird Kali", "author": "skep13", "version": "0.1.0", "requirements": "paho-mqtt"}}
now = int(time.time())
c.execute("delete from tool where id=?", (tid,))
c.execute("""insert into tool (id,user_id,name,content,specs,meta,valves,updated_at,created_at)
             values (?,?,?,?,?,?,?,?,?)""",
          (tid, uid, "Songbird Kali", content, json.dumps(specs), json.dumps(meta), json.dumps({}), now, now))
mm = json.loads(m[1]) if m[1] else {}
tids = mm.get("toolIds") or []
if tid not in tids:
    tids.append(tid)
mm["toolIds"] = tids
c.execute("update model set meta=?, updated_at=? where id='songbird'", (json.dumps(mm), now))
db.commit()
print("kali tool registered | songbird toolIds:", tids)
