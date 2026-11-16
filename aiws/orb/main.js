// Marina's sphere: a small always-on-top window with an animated orb. Click
// it (or `aiws-orb --toggle`, bound to Super+Space on Hyprland) to open the
// chat above it.
//
// The main process owns everything outside the page: settings, the gateway
// (aiwsd) connection and its token, the activity log of what you're doing,
// and a long-running screen helper (python -m aiws.screen serve) for the
// focused window, selected text and screenshots.
const { app, BrowserWindow, ipcMain, screen, globalShortcut } = require('electron');
const { spawn } = require('child_process');
const fs = require('fs');
const path = require('path');
const readline = require('readline');

const GATEWAY = process.env.AIWS_URL || 'http://127.0.0.1:7300';
const TOKEN_FILE = process.env.AIWS_TOKEN_FILE || '/var/lib/aiws/desktop.token';
const PYTHON = process.env.AIWS_PYTHON || 'python3';
const ORB = 220;                       // collapsed window: just the sphere
const OPEN = { w: 440, h: 720 };       // expanded: chat panel above it
const MARGIN = 18;

if (!app.requestSingleInstanceLock()) { app.quit(); process.exit(0); }

let win, expanded = false;

// ---- settings -----------------------------------------------------------------
const settingsFile = () => path.join(app.getPath('userData'), 'settings.json');
function loadSettings() {
  try { return JSON.parse(fs.readFileSync(settingsFile(), 'utf8')); } catch { return {}; }
}
function saveSettings(s) {
  fs.mkdirSync(path.dirname(settingsFile()), { recursive: true });
  fs.writeFileSync(settingsFile(), JSON.stringify(s, null, 2));
}

// ---- window -------------------------------------------------------------------
function bounds(open) {
  const wa = screen.getPrimaryDisplay().workArea;
  const w = open ? OPEN.w : ORB, h = open ? OPEN.h : ORB;
  return { x: wa.x + wa.width - w - MARGIN, y: wa.y + wa.height - h - MARGIN, width: w, height: h };
}

function createWindow() {
  win = new BrowserWindow({
    ...bounds(false),
    // Resizable on Linux: on Wayland a fixed-size window can't be sized by
    // the compositor, which keeps her in the corner when the chat opens.
    frame: false, transparent: true, resizable: process.platform === 'linux', hasShadow: false,
    alwaysOnTop: true, skipTaskbar: true, fullscreenable: false,
    backgroundColor: '#00000000', title: 'Marina',
    // The dock and window switcher show this; the installed icon if there is one.
    icon: [path.join(require('os').homedir(), '.local/share/icons/hicolor/256x256/apps/marina.png'),
           path.join(__dirname, 'icon.png')].find((f) => fs.existsSync(f)),
    webPreferences: { preload: path.join(__dirname, 'preload.js'), contextIsolation: true },
  });
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));
}

// Wayland apps can't place their own windows. On Hyprland, ask it to keep
// the window in the bottom-right corner of the usable area after a resize.
function hyprAnchor(w, h) {
  if (!process.env.HYPRLAND_INSTANCE_SIGNATURE) return;
  const { execFile } = require('child_process');
  execFile('hyprctl', ['monitors', '-j'], (err, out) => {
    if (err) return;
    let m;
    try { m = JSON.parse(out).find((x) => x.focused) || JSON.parse(out)[0]; } catch { return; }
    const [rl, rt, rr, rb] = m.reserved || [0, 0, 0, 0];
    const mw = Math.round(m.width / (m.scale || 1)), mh = Math.round(m.height / (m.scale || 1));
    const x = m.x + mw - rr - w - MARGIN, y = m.y + mh - rb - h - MARGIN;
    // Hyprland with a Lua config takes Lua dispatchers; older ones the classic words.
    const win = 'window = "title:^Marina$"';
    execFile('hyprctl', ['dispatch', `hl.dsp.window.resize({ x = ${w}, y = ${h}, exact = true, ${win} })`], (e1, o1) => {
      if (e1 || /error/i.test(o1)) {
        execFile('hyprctl', ['--batch', `dispatch resizewindowpixel exact ${w} ${h},title:^Marina$; dispatch movewindowpixel exact ${x} ${y},title:^Marina$`]);
        return;
      }
      execFile('hyprctl', ['dispatch', `hl.dsp.window.move({ x = ${x}, y = ${y}, exact = true, ${win} })`]);
    });
  });
}

function setExpanded(open) {
  expanded = open;
  win.setBounds(bounds(open), false);
  hyprAnchor(open ? OPEN.w : ORB, open ? OPEN.h : ORB);
  win.webContents.send('expanded', open);
  if (open) win.focus();
}

// ---- screen helper ---------------------------------------------------------------
let helper, pending = [];
function startHelper() {
  const src = path.resolve(__dirname, '..', 'src');
  helper = spawn(PYTHON, ['-m', 'aiws.screen', 'serve'], {
    env: { ...process.env, PYTHONPATH: [src, process.env.PYTHONPATH].filter(Boolean).join(path.delimiter) },
    stdio: ['pipe', 'pipe', 'inherit'],
  });
  readline.createInterface({ input: helper.stdout }).on('line', (line) => {
    const p = pending.shift();
    if (p) { try { p(JSON.parse(line)); } catch { p({ ok: false, error: 'bad reply' }); } }
  });
  helper.on('exit', () => { helper = null; for (const p of pending.splice(0)) p({ ok: false, error: 'helper exited' }); });
}
function ask(cmd) {
  return new Promise((resolve) => {
    if (!helper) startHelper();
    pending.push(resolve);
    helper.stdin.write(cmd + '\n');
  });
}

// ---- what you're doing: focus changes, kept as a short rolling log -------------------
const activity = [];
let lastKey = '';
async function pollActivity() {
  const w = await ask('window');
  if (w.ok && w.app) {
    const key = `${w.app}\u0000${w.title}`;
    if (key !== lastKey) {
      lastKey = key;
      activity.push({ t: Date.now(), app: w.app, title: w.title || '' });
      if (activity.length > 40) activity.shift();
      win?.webContents.send('activity', activity.slice(-12));
    }
  }
}

// ---- gateway ---------------------------------------------------------------------
function token() {
  try { return fs.readFileSync(TOKEN_FILE, 'utf8').trim(); } catch { return ''; }
}
async function api(pathname, body, method) {
  const r = await fetch(GATEWAY + pathname, {
    method: method || (body ? 'POST' : 'GET'),
    headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
  return r.json();
}

// Streams a chat reply to the page as 'chat-delta' events; returns when done.
const streams = new Map();
async function chat(id, messages) {
  const ctl = new AbortController();
  streams.set(id, ctl);
  try {
    const r = await fetch(GATEWAY + '/v1/chat/completions', {
      method: 'POST', signal: ctl.signal,
      headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'ai:chat', stream: true, messages, temperature: 0.6, max_tokens: 1200,
                             chat_template_kwargs: { enable_thinking: false } }),
    });
    if (!r.ok) throw new Error(`${r.status} ${(await r.text()).slice(0, 200)}`);
    const dec = new TextDecoder();
    let buf = '';
    for await (const chunk of r.body) {
      buf += dec.decode(chunk, { stream: true });
      let i;
      while ((i = buf.indexOf('\n')) >= 0) {
        const line = buf.slice(0, i).trim(); buf = buf.slice(i + 1);
        if (!line.startsWith('data:')) continue;
        const data = line.slice(5).trim();
        if (data === '[DONE]') continue;
        try {
          const piece = JSON.parse(data).choices?.[0]?.delta?.content;
          if (piece) win.webContents.send('chat-delta', { id, piece });
        } catch {}
      }
    }
    win.webContents.send('chat-done', { id });
  } catch (e) {
    win.webContents.send('chat-done', { id, error: ctl.signal.aborted ? 'stopped' : String(e.message || e) });
  } finally {
    streams.delete(id);
  }
}

// ---- ipc --------------------------------------------------------------------------
ipcMain.handle('settings:get', () => loadSettings());
ipcMain.handle('settings:set', (_e, s) => { saveSettings(s); return true; });
ipcMain.handle('toggle', () => setExpanded(!expanded));
ipcMain.handle('context', async (_e, { screenshot } = {}) => {
  const [w, sel] = await Promise.all([ask('window'), ask('selection')]);
  const out = { window: w.ok ? w : null, selection: sel.ok ? sel.text : '', activity: activity.slice(-12) };
  if (screenshot) {
    const c = await ask('capture');
    out.screenshot = c.ok ? c.png : null;
    out.screenshotError = c.ok ? null : c.error;
  }
  return out;
});
ipcMain.handle('chat', (_e, { id, messages }) => { chat(id, messages); return true; });
ipcMain.handle('chat:stop', (_e, id) => { streams.get(id)?.abort(); return true; });
ipcMain.handle('api', (_e, { pathname, body, method }) => api(pathname, body, method));

// ---- first boot: lab3 key and Tailscale --------------------------------------------
const { spawn: spawnProc } = require('child_process');
const run = (cmd, args, input) => new Promise((resolve) => {
  const p = spawnProc(cmd, args, { stdio: ['pipe', 'pipe', 'pipe'] });
  let out = '', err = '';
  p.stdout.on('data', (d) => (out += d)); p.stderr.on('data', (d) => (err += d));
  p.on('error', (e) => resolve({ code: -1, out, err: String(e) }));
  p.on('close', (code) => resolve({ code, out, err }));
  if (input !== undefined) p.stdin.end(input); else p.stdin.end();
});
ipcMain.handle('setup:status', async () => {
  const st = { platform: process.platform, lab3: false, tailscale: null };
  try {             // a one-token request through the gateway proves the key works
    const r = await fetch(GATEWAY + '/v1/chat/completions', {
      method: 'POST', headers: { Authorization: `Bearer ${token()}`, 'Content-Type': 'application/json' },
      body: JSON.stringify({ model: 'lab3-marina', max_tokens: 1, messages: [{ role: 'user', content: 'hi' }] }),
    });
    st.lab3 = r.ok;
  } catch {}
  const ts = await run('tailscale', ['status', '--json']);
  if (ts.code !== -1) { try { st.tailscale = JSON.parse(ts.out).BackendState === 'Running'; } catch { st.tailscale = false; } }
  return st;
});
ipcMain.handle('setup:key', async (_e, key) => {
  const r = await run('pkexec', ['/usr/lib/aiws/set-key'], key + '\n');
  return { ok: r.code === 0, error: (r.err || '').trim().slice(-200) };
});
ipcMain.handle('setup:tailscale', async () => {
  // `tailscale up` prints a login link; open it and let it finish in the background.
  const { shell } = require('electron');
  return new Promise((resolve) => {
    const p = spawnProc('pkexec', ['tailscale', 'up', '--accept-routes']);
    let opened = false;
    const look = (d) => {
      const m = String(d).match(/https:\/\/login\.tailscale\.com\/\S+/);
      if (m && !opened) { opened = true; shell.openExternal(m[0]); resolve({ ok: true, url: m[0] }); }
    };
    p.stdout.on('data', look); p.stderr.on('data', look);
    p.on('close', (code) => { if (!opened) resolve({ ok: code === 0 }); });
  });
});

app.on('second-instance', (_e, argv) => {
  if (argv.includes('--toggle')) setExpanded(!expanded);
});

app.whenReady().then(() => {
  createWindow();
  startHelper();
  setInterval(pollActivity, 1500);
  // On the Mac, a global shortcut for testing. On Hyprland, Super+Space runs
  // `aiws-orb --toggle` instead (global shortcuts need a portal on Wayland).
  if (process.platform === 'darwin') globalShortcut.register('CommandOrControl+Shift+Space', () => setExpanded(!expanded));
  if (process.env.AIWS_ORB_SNAPDIR) snapshots(process.env.AIWS_ORB_SNAPDIR);
});

// Test aid: capture the window itself (no screen recording needed) in a few
// states, write PNGs to AIWS_ORB_SNAPDIR, then quit.
async function snapshots(dir) {
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));
  const shot = async (name) => fs.writeFileSync(path.join(dir, name), (await win.webContents.capturePage()).toPNG());
  const js = (code) => win.webContents.executeJavaScript(code);
  await wait(2500);
  if (process.env.AIWS_ORB_DO) {           // live task: hand it to the assistant
    setExpanded(true); await wait(600);
    await js(`document.getElementById('input').value = ${JSON.stringify(process.env.AIWS_ORB_DO)}; document.getElementById('doit').click()`);
    for (let i = 0; i < 180; i++) { await wait(1000); if (await js("document.getElementById('stop').hidden")) break; }
    await shot('6-task.png');
    console.log('TASK: ' + await js("[...document.querySelectorAll('.msg.ai, .act, .note')].map(e => e.textContent).join(' | ')"));
    app.quit(); return;
  }
  if (process.env.AIWS_ORB_ASK) {          // live round trip: ask with a screenshot
    setExpanded(true); await wait(600);
    await js(`document.getElementById('look').click(); document.getElementById('input').value = ${JSON.stringify(process.env.AIWS_ORB_ASK)}; document.getElementById('send').click()`);
    for (let i = 0; i < 120; i++) { await wait(1000); if (await js("document.getElementById('stop').hidden")) break; }
    await shot('5-live.png');
    console.log('REPLY: ' + await js("[...document.querySelectorAll('.msg.ai, .note')].map(e => e.textContent).join(' | ')"));
    console.log('ATT: ' + await js("[...document.querySelectorAll('.att')].map(e => e.textContent).join(',')"));
    app.quit(); return;
  }
  await shot('1-idle.png');
  await js("__orb.setState('speaking'); for (let i = 0; i < 6; i++) setTimeout(() => __orb.pulse(.9, i % 2), i * 120)");
  await wait(500); await shot('2-speaking.png');
  setExpanded(true); await wait(800);
  await js(`document.getElementById('msgs').innerHTML = '<div class="msg user"><span class="att">👁 with a screenshot</span><span>why is my merge test failing?</span></div><div class="msg ai"><span>Your merge loop stops as soon as one list runs out and never adds what is left of the other. Add out.extend(a[i:]) and out.extend(b[j:]) before the return.</span></div><div class="act"><b>read_file</b> {"path": "mergesort.py"}</div>';
    document.getElementById('seeing').textContent = 'seeing: VSCodium — mergesort.py'; __orb.setState('thinking')`);
  await wait(700); await shot('3-chat.png');
  await js("document.getElementById('gear').click()"); await wait(400); await shot('4-colours.png');
  app.quit();
}
app.on('will-quit', () => { globalShortcut.unregisterAll(); helper?.kill(); });
app.on('window-all-closed', () => app.quit());
