// Marina's sphere: chat, context, colours, and her work on your computer.
import { Orb } from './orb.js';

const $ = (id) => document.getElementById(id);
const orb = new Orb($('orb'));

// ---- colours ----------------------------------------------------------------------
const DEFAULTS = {
  core: '#2a6cff', glow: '#7fd8ff', pulse: '#bfefff',
  idle: '#9fb4ff', listening: '#6ee7ff', thinking: '#b18cff', speaking: '#7fffd4',
  acting: '#ffb35c', approval: '#ffd23f', error: '#ff4d6d',
};
const LABELS = {
  core: 'Core', glow: 'Glow & rim', pulse: 'Pulses',
  idle: 'Idle', listening: 'Listening', thinking: 'Thinking', speaking: 'Speaking / typing',
  acting: 'Working on your computer', approval: 'Waiting for you', error: 'Something went wrong',
};
let settings = { colors: { ...DEFAULTS } };

function applyColors() {
  orb.setColors(settings.colors);
  document.documentElement.style.setProperty('--accent', settings.colors.glow);
}

function buildPickers() {
  for (const [host, keys] of [['base', ['core', 'glow', 'pulse']],
                              ['states', ['idle', 'listening', 'thinking', 'speaking', 'acting', 'approval', 'error']]]) {
    $(host).innerHTML = '';
    for (const k of keys) {
      const l = document.createElement('label');
      l.innerHTML = `<input type="color" value="${settings.colors[k]}"><span>${LABELS[k]}</span><small>${settings.colors[k]}</small>`;
      const input = l.querySelector('input');
      input.addEventListener('input', () => {
        settings.colors[k] = input.value;
        l.querySelector('small').textContent = input.value;
        applyColors();
        if (['idle', 'listening', 'thinking', 'speaking', 'acting', 'approval', 'error'].includes(k)) preview(k);
      });
      input.addEventListener('change', save);
      $(host).append(l);
    }
  }
}

// Picking a state's colour shows that state for a moment.
let previewTimer;
function preview(state) {
  orb.setState(state);
  if (state === 'speaking') for (let i = 0; i < 4; i++) setTimeout(() => orb.pulse(.8, i % 2 === 1), i * 160);
  clearTimeout(previewTimer);
  previewTimer = setTimeout(() => orb.setState(busy ? busyState : 'idle'), 1600);
}

const save = () => window.orb.saveSettings(settings);

// ---- panel ---------------------------------------------------------------------------
let dragged = false;
$('orb').addEventListener('mousedown', () => { dragged = false; });
$('orb').addEventListener('click', () => { if (!dragged) window.orb.toggle(); });
$('close').onclick = () => window.orb.toggle();
window.orb.on('expanded', (open) => {
  $('panel').hidden = !open;
  if (open) setTimeout(() => $('input').focus(), 50);
});
$('gear').onclick = () => { $('settings').hidden = !$('settings').hidden; $('chat').hidden = !$('settings').hidden; };
$('done').onclick = () => { $('settings').hidden = true; $('chat').hidden = false; };
$('reset').onclick = () => { settings.colors = { ...DEFAULTS }; buildPickers(); applyColors(); save(); };

// ---- what she can see ------------------------------------------------------------------
let activity = [], lookNext = false, watching = false, lastShot = null, lastShotAt = 0;
window.orb.on('activity', (a) => {
  activity = a;
  const cur = a[a.length - 1];
  if (cur) $('seeing').textContent = `seeing: ${cur.app}${cur.title ? ' — ' + cur.title : ''}`;
});
$('look').onclick = () => { lookNext = !lookNext; $('look').classList.toggle('on', lookNext); };
$('watch').onclick = () => {
  watching = !watching;
  $('watch').classList.toggle('on', watching);
  $('seeing').classList.toggle('watching', watching);
  if (watching) refreshShot();
};
// Watch mode: keep one recent screenshot in memory (never saved), so asking
// "what's wrong here?" works without pressing look.
setInterval(() => { if (watching) refreshShot(); }, 20000);
async function refreshShot() {
  const c = await window.orb.context({ screenshot: true });
  if (c.screenshot) { lastShot = await shrink(c.screenshot); lastShotAt = Date.now(); }
}

// Screenshots go to the model as a JPEG no wider than 1600px: Retina PNGs are
// several MB and the model doesn't need that.
function shrink(b64png) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const s = Math.min(1, 1600 / img.width);
      const c = document.createElement('canvas');
      c.width = img.width * s; c.height = img.height * s;
      c.getContext('2d').drawImage(img, 0, 0, c.width, c.height);
      resolve(c.toDataURL('image/jpeg', 0.82));
    };
    img.onerror = () => resolve(null);
    img.src = 'data:image/png;base64,' + b64png;
  });
}

// ---- chat ------------------------------------------------------------------------------
const SYSTEM = `You are Marina, the assistant that lives on this laptop as a small animated sphere.
You help with whatever the user is doing: college work, code, hardware projects, anything on screen.
You get a short log of the apps and windows they've been in, what's focused now, any text they
have selected, and sometimes a screenshot. Use it: refer to what's actually there instead of
asking them to paste it. Be direct and concise; give steps or code when that's what helps.
If they want you to do something on the computer, tell them to press "do it".`;

const history = [];
let busy = false, busyState = 'idle', currentId = null, currentTask = null;

function addMsg(role, text, att) {
  const d = document.createElement('div');
  d.className = 'msg ' + (role === 'user' ? 'user' : 'ai');
  if (att) d.innerHTML = `<span class="att">${att}</span>`;
  const body = document.createElement('span');
  body.textContent = text;
  d.append(body);
  $('msgs').append(d);
  $('msgs').scrollTop = $('msgs').scrollHeight;
  return body;
}
function addLine(cls, html) {
  const d = document.createElement('div');
  d.className = cls; d.innerHTML = html;
  $('msgs').append(d); $('msgs').scrollTop = $('msgs').scrollHeight;
}
const esc = (s) => String(s ?? '').replace(/[&<>"]/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));

// Just enough markdown for chat: code blocks, inline code, bold, italics.
function md(text) {
  return esc(text)
    .replace(/```[\w-]*\n?([\s\S]*?)```/g, (_, c) => `<pre>${c}</pre>`)
    .replace(/`([^`\n]+)`/g, '<code>$1</code>')
    .replace(/\*\*([^*\n]+)\*\*/g, '<b>$1</b>')
    .replace(/(^|[^*])\*([^*\n]+)\*/g, '$1<i>$2</i>');
}

function setBusy(on, state = 'idle') {
  busy = on; busyState = state;
  orb.setState(on ? state : 'idle');
  $('stop').hidden = !on;
  $('send').disabled = on; $('doit').disabled = on;
}

async function contextBlock(withShot) {
  const c = await window.orb.context({ screenshot: withShot && !lastShotFresh() });
  let shot = null;
  if (withShot) shot = c.screenshot ? await shrink(c.screenshot) : lastShot;
  const lines = [];
  if (c.window?.app) lines.push(`Focused now: ${c.window.app}${c.window.title ? ' — ' + c.window.title : ''}`);
  if (c.selection) lines.push(`Selected text:\n${c.selection.slice(0, 3000)}`);
  if (c.activity?.length) lines.push('Recent windows (oldest first):\n' + c.activity.map((a) =>
    `- ${new Date(a.t).toLocaleTimeString()} ${a.app}${a.title ? ' — ' + a.title : ''}`).join('\n'));
  if (withShot && !shot) lines.push(`(Screenshot failed: ${c.screenshotError || 'no permission?'})`);
  return { text: lines.join('\n\n'), shot };
}
const lastShotFresh = () => watching && lastShot && Date.now() - lastShotAt < 25000;

async function send() {
  const text = $('input').value.trim();
  if (!text || busy) return;
  $('input').value = '';
  const withShot = lookNext || watching;
  lookNext = false; $('look').classList.remove('on');
  setBusy(true, 'thinking');
  const ctx = await contextBlock(withShot);
  addMsg('user', text, ctx.shot ? '👁 with a screenshot' : '');
  const content = ctx.shot
    ? [{ type: 'text', text }, { type: 'image_url', image_url: { url: ctx.shot } }]
    : text;
  history.push({ role: 'user', content });
  const messages = [{ role: 'system', content: SYSTEM + (ctx.text ? '\n\n## What the user is doing\n' + ctx.text : '') },
                    // only the latest message keeps its screenshot; older ones become text
                    ...history.slice(-16).map((m, i, a) => (i < a.length - 1 && Array.isArray(m.content))
                      ? { role: m.role, content: m.content[0].text + ' [screenshot was attached]' } : m)];
  currentId = Math.random().toString(36).slice(2);
  const out = addMsg('ai', '');
  out.dataset.id = currentId;
  window.orb.chat(currentId, messages);
}

// Streamed text: each burst sends a pulse, sized by how much arrived.
let pending = 0, lastPulse = 0;
window.orb.on('chat-delta', ({ id, piece }) => {
  if (id !== currentId) return;
  orb.setState('speaking'); busyState = 'speaking';
  const el = $('msgs').querySelector(`[data-id="${id}"]`);
  if (el) { el.dataset.raw = (el.dataset.raw || '') + piece; el.innerHTML = md(el.dataset.raw); $('msgs').scrollTop = $('msgs').scrollHeight; }
  pending += piece.length;
  const now = performance.now();
  if (now - lastPulse > 110) { orb.pulse(Math.min(1, 0.35 + pending / 40), pending > 30); pending = 0; lastPulse = now; }
});
window.orb.on('chat-done', ({ id, error }) => {
  if (id !== currentId) return;
  const el = $('msgs').querySelector(`[data-id="${id}"]`);
  if (error) {
    if (el && !el.dataset.raw) el.parentElement.remove();
    addLine('note', esc(error === 'stopped' ? 'stopped' : 'couldn’t reach the model: ' + error));
    if (error !== 'stopped') { orb.setState('error'); setTimeout(() => setBusy(false), 1500); busy = false; return; }
  } else if (el) {
    history.push({ role: 'assistant', content: el.dataset.raw || '' });
  }
  setBusy(false);
});

// ---- doing things on the computer -------------------------------------------------------
async function doIt() {
  const text = $('input').value.trim();
  if (!text || busy) return;
  $('input').value = '';
  addMsg('user', text, '▶ do it');
  setBusy(true, 'acting');
  try {
    const st = await window.orb.api('/api/status');
    let project = st.active_project;
    if (!project) {             // no project open: a desktop-only workspace (screen, keys, jobs; no files)
      await window.orb.api('/api/projects', { path: '~', spec: { name: 'desktop', agent: { tools: ['desktop', 'jobs'], paths: [] } } });
      project = 'desktop';
    }
    const ctx = await contextBlock(false);
    const t = await window.orb.api('/api/agent/tasks', { prompt: text + (ctx.text ? '\n\n(Context: ' + ctx.text + ')' : ''), project });
    currentTask = t.id;
    addLine('note', `task ${t.id} started — the sphere turns to “working”; ■ stop ends it`);
    followTask(t.id);
  } catch (e) {
    addLine('note', esc('couldn’t start it: ' + e.message));
    orb.setState('error'); setTimeout(() => setBusy(false), 1500); busy = false;
  }
}

async function followTask(id) {
  let seen = 0;
  const shown = new Set();
  while (currentTask === id) {
    try {
      const acts = (await window.orb.api(`/api/agent/actions?after=${seen}`)).actions.reverse();
      for (const a of acts) {
        if (a.status === 'running') {
          if (!shown.has(a.id)) { shown.add(a.id); orb.pulse(.9, true); addLine('act', `<b>${esc(a.tool)}</b> ${esc(a.args.slice(0, 120))}`); }
          break;
        }
        seen = Math.max(seen, a.id);
        if (!shown.has(a.id)) { shown.add(a.id); orb.pulse(.9, true); addLine('act', `<b>${esc(a.tool)}</b> ${esc(a.args.slice(0, 120))}`); }
        if (a.status !== 'ok') addLine('act', `<span class="bad">${esc(a.status)}: ${esc((a.result || '').slice(0, 160))}</span>`);
      }
      const task = (await window.orb.api('/api/agent/tasks')).tasks.find((x) => x.id === id);
      if (task && ['done', 'failed', 'stopped'].includes(task.status)) {
        addMsg('ai', '').innerHTML = md(task.result || task.status);
        currentTask = null;
        setBusy(false);
        return;
      }
    } catch (e) {
      addLine('note', esc('lost track of the task: ' + e.message));
      currentTask = null; setBusy(false); return;
    }
    await new Promise((r) => setTimeout(r, 700));
  }
}

$('stop').onclick = async () => {
  if (currentTask) {
    try { await window.orb.api('/api/agent/state', { state: 'stopped' }); } catch {}
    addLine('note', 'stopped');
    currentTask = null; setBusy(false);
  } else if (currentId) {
    window.orb.stopChat(currentId);
  }
};
$('send').onclick = send;
$('doit').onclick = doIt;

// Typing to her: she listens, with a faint ripple per keystroke.
let lastKey = 0;
$('input').addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); send(); return; }
  if (e.key === 'Escape') { window.orb.toggle(); return; }
  if (!busy) {
    orb.setState('listening');
    const now = performance.now();
    if (now - lastKey > 140) { orb.pulse(.25); lastKey = now; }
    clearTimeout(window.__idle);
    window.__idle = setTimeout(() => { if (!busy) orb.setState('idle'); }, 1500);
  }
});

// ---- first boot: connect to lab3 and Tailscale ------------------------------------------
// Shown only while something is missing; no secrets live on the install USB.
async function checkSetup() {
  let st;
  try { st = await window.orb.setupStatus(); } catch { return; }
  document.getElementById('setup')?.remove();
  const needKey = !st.lab3, needTs = st.tailscale === false;
  if (!needKey && !needTs) return;
  const d = document.createElement('div');
  d.id = 'setup'; d.className = 'msg ai';
  d.innerHTML = `<span class="att">first-time setup</span>
    ${needTs ? '<div class="row" style="margin:4px 0"><span class="grow">Tailscale isn’t logged in, so lab3 is out of reach away from home.</span><button id="ts">log in</button></div>' : ''}
    ${needKey ? '<div style="margin-top:6px">Paste lab3’s key to connect me to my model:</div><div class="row" style="margin-top:6px"><input id="key" type="password" placeholder="llama-swap key" style="flex:1;background:rgba(0,0,0,.3);border:1px solid var(--line);border-radius:8px;color:var(--ink);padding:5px 8px"><button id="savekey" class="primary">connect</button></div>' : ''}
    <div id="setupmsg" style="color:var(--dim);font-size:11.5px;margin-top:6px"></div>`;
  $('msgs').prepend(d);
  const msg = (t) => { d.querySelector('#setupmsg').textContent = t; };
  d.querySelector('#ts')?.addEventListener('click', async () => {
    msg('opening the Tailscale login in your browser…');
    const r = await window.orb.tailscaleUp();
    msg(r.ok ? 'finish logging in in the browser, then I’ll check again' : 'Tailscale didn’t start');
    setTimeout(checkSetup, 15000);
  });
  d.querySelector('#savekey')?.addEventListener('click', async () => {
    const k = d.querySelector('#key').value.trim();
    if (!k) return;
    msg('saving (asks for your password)…');
    const r = await window.orb.setKey(k);
    msg(r.ok ? 'saved, checking…' : 'couldn’t save it: ' + (r.error || 'cancelled'));
    if (r.ok) setTimeout(checkSetup, 2500);
  });
}
window.orb.on('expanded', (open) => { if (open) checkSetup(); });

// ---- start ---------------------------------------------------------------------------
window.orb.settings().then((s) => {
  if (s && s.colors) settings.colors = { ...DEFAULTS, ...s.colors };
  buildPickers(); applyColors();
});
window.__orb = orb;
