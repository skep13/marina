"""The page behind "What she remembers…" in her menu: everything in her
memory, with a way to add to it, keep a fact for good, or delete it."""

HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>What Marina remembers</title>
<style>
  :root { --bg:#f6f4f1; --card:#fff; --ink:#22201d; --dim:#77716a; --line:#e4dfd8; --accent:#b4476b; }
  @media (prefers-color-scheme: dark) {
    :root { --bg:#17161a; --card:#211f25; --ink:#ece8e4; --dim:#9a948d; --line:#33303a; --accent:#e08aa6; }
  }
  * { box-sizing: border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:15px/1.5 -apple-system, system-ui, sans-serif; }
  main { max-width:760px; margin:0 auto; padding:28px 16px 60px; }
  h1 { font-size:22px; margin:0 0 4px; }
  h2 { font-size:13px; text-transform:uppercase; letter-spacing:.06em; color:var(--dim);
       margin:30px 0 8px; }
  p.sub { color:var(--dim); margin:0 0 18px; }
  ul { list-style:none; margin:0; padding:0; background:var(--card);
       border:1px solid var(--line); border-radius:10px; }
  li { display:flex; gap:10px; align-items:flex-start; padding:10px 12px;
       border-top:1px solid var(--line); }
  li:first-child { border-top:0; }
  li .text { flex:1; min-width:0; overflow-wrap:anywhere; }
  li .meta { color:var(--dim); font-size:12px; }
  button { font:inherit; font-size:13px; border:1px solid var(--line); background:transparent;
           color:var(--ink); border-radius:7px; padding:3px 9px; cursor:pointer; white-space:nowrap; }
  button:hover { border-color:var(--accent); color:var(--accent); }
  .empty { padding:12px; color:var(--dim); }
  form { display:flex; gap:8px; margin-top:10px; }
  input { flex:1; font:inherit; padding:8px 10px; border:1px solid var(--line);
          border-radius:8px; background:var(--card); color:var(--ink); min-width:0; }
  .kept { color:var(--accent); font-size:12px; }
</style></head><body><main>
<h1>What Marina remembers</h1>
<p class="sub" id="sub">Loading…</p>
<h2>About you</h2><ul id="facts"></ul>
<form id="add"><input id="new" placeholder="Tell her something to remember, e.g. The user is allergic to cats" maxlength="200"><button>Add</button></form>
<h2>Things to ask you about</h2><ul id="events"></ul>
<h2>What you two have talked about</h2><ul id="episodes"></ul>
<h2>About herself</h2><ul id="self"></ul>
<script>
const $ = (id) => document.getElementById(id);
function row(f, opts) {
  const li = document.createElement('li');
  const text = document.createElement('div'); text.className = 'text';
  text.textContent = f.text;
  const meta = document.createElement('div'); meta.className = 'meta';
  meta.textContent = opts.meta(f); text.appendChild(meta);
  li.appendChild(text);
  if (opts.pin && f.source === 'auto') {
    const b = document.createElement('button'); b.textContent = 'Keep';
    b.title = 'Never forget this to make room';
    b.onclick = async () => { await fetch('/memory/' + f.id + '/pin', {method:'POST'}); load(); };
    li.appendChild(b);
  } else if (opts.pin) {
    const k = document.createElement('span'); k.className = 'kept'; k.textContent = 'kept';
    li.appendChild(k);
  }
  const d = document.createElement('button'); d.textContent = 'Forget';
  d.onclick = async () => { await fetch('/memory/' + f.id, {method:'DELETE'}); load(); };
  li.appendChild(d);
  return li;
}
function fill(id, items, opts, none) {
  const ul = $(id); ul.replaceChildren();
  if (!items.length) { const e = document.createElement('div'); e.className = 'empty';
    e.textContent = none; ul.appendChild(e); return; }
  items.forEach((f) => ul.appendChild(row(f, opts)));
}
const day = (s) => (s || '').slice(0, 10);
async function load() {
  const data = await (await fetch('/memory')).json();
  const all = data.facts || [];
  const kind = (f) => ['event','episode','self'].includes(f.source) ? f.source : 'fact';
  const of = (k) => all.filter((f) => kind(f) === k);
  fill('facts', of('fact'), {pin:true, meta:(f) => 'learned ' + day(f.created) +
       (f.mentions > 1 ? ' · heard ' + f.mentions + ' times' : '')}, 'Nothing yet.');
  fill('events', of('event'), {meta:(f) => (String(f.due||'').endsWith('~') ? 'around ' : 'on ') +
       day(f.due)}, 'Nothing coming up that she knows of.');
  fill('episodes', of('episode').reverse(), {meta:(f) => day(f.created)},
       'Nothing yet. These appear as older conversation scrolls out of her view.');
  fill('self', of('self'), {meta:(f) => 'noted ' + day(f.created)}, 'Nothing yet.');
  const r = data.ratings || {good:0, bad:0};
  $('sub').textContent = all.length + ' things remembered · replies rated: ' +
      r.good + ' good, ' + r.bad + ' bad';
}
$('add').onsubmit = async (e) => {
  e.preventDefault();
  const text = $('new').value.trim(); if (!text) return;
  await fetch('/memory', {method:'POST', headers:{'Content-Type':'application/json'},
                          body: JSON.stringify({text})});
  $('new').value = ''; load();
};
load();
</script></main></body></html>
"""
