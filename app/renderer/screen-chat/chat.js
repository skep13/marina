// Type to her screen: what you write goes to the screen's bridge, she answers
// there (lab3's monitor), and her words show up here too.
const $ = (id) => document.getElementById(id);
const api = window.screenChat;

let current = null;   // { id, el, chunks }

function scroll() { $('msgs').scrollTop = $('msgs').scrollHeight; }

function add(cls, text) {
  const d = document.createElement(cls === 'note' ? 'p' : 'div');
  d.className = cls === 'note' ? 'note' : `msg ${cls}`;
  d.textContent = text;
  $('msgs').append(d);
  scroll();
  return d;
}

function setStatus(kind, text) {
  $('dot').className = `dot ${kind}`;
  $('status').textContent = text;
}

function setBusy(on) {
  $('send').disabled = on;
  $('stop').hidden = !on;
}

function showPower(p) {
  if (!p) { $('power').textContent = ''; return; }
  $('power').textContent = p.on ? `screen on until ${p.until_text}` : `screen off · ${p.reason}`;
}

async function check() {
  $('where').textContent = await api.url();
  showPower(await api.power());
  const h = await api.health();
  if (h.ok) setStatus('ok', `connected · ${h.model || 'her bridge'}`);
  else setStatus('bad', `can't reach her screen (${h.error})`);
}

function send(e) {
  e?.preventDefault();
  const text = $('input').value.trim();
  if (!text || current) return;
  $('input').value = '';
  add('you', text);
  const id = Math.random().toString(36).slice(2);
  current = { id, el: null, chunks: 0 };
  setBusy(true);
  api.say(id, text);
}

function finish() {
  if (current?.el && !current.el.textContent) current.el.remove();
  current = null;
  setBusy(false);
  $('input').focus();
}

api.onEvent((ev) => {
  if (!current || ev.id !== current.id) return;
  switch (ev.type) {
    case 'screens':
      if (!ev.count) add('note', 'Her screen isn’t showing right now. She’ll answer here only.');
      break;
    case 'start':
      current.el = add('her', '');
      break;
    case 'chunk':
      if (!current.el) current.el = add('her', '');
      if (ev.reply) {
        current.el.textContent += (current.chunks ? ' ' : '') + ev.reply;
        current.chunks++;
        scroll();
      }
      break;
    case 'activity':
      add('note', ev.text);
      break;
    case 'confirm':
      add('note', `She’s asking on her screen: ${ev.text}`);
      break;
    case 'error':
      add('note', ev.message || 'something went wrong');
      break;
    case 'failed':
      add('note', `couldn’t reach her screen: ${ev.message}`);
      setStatus('bad', 'can’t reach her screen');
      finish();
      break;
    case 'interrupted':
      add('note', 'stopped');
      break;
    case 'closed':
      finish();
      break;
  }
});

$('composer').addEventListener('submit', send);
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); }
});
$('stop').addEventListener('click', () => { if (current) api.stop(current.chunks); });
$('extend').addEventListener('click', async () => {
  $('extend').disabled = true;
  showPower(await api.extend(60));
  $('extend').disabled = false;
});

// Pointing it at another bridge (another box, or ai.local on its Wi-Fi).
$('where').addEventListener('click', async () => {
  $('url').value = await api.url();
  $('composer').hidden = true;
  $('url-form').hidden = false;
  $('url').focus();
});
$('url-cancel').addEventListener('click', () => { $('url-form').hidden = true; $('composer').hidden = false; });
$('url-form').addEventListener('submit', async (e) => {
  e.preventDefault();
  await api.setUrl($('url').value);
  $('url-form').hidden = true;
  $('composer').hidden = false;
  check();
});

check();
setInterval(() => { if (!current) check(); }, 15000);
