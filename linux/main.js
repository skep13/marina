// Marina on Linux (Mint, Cinnamon). The same renderer as the Mac app, drawn
// whole-body in its own window. Unlike the Mac app there's no bridge on this
// machine: a small server on 127.0.0.1 serves the page and passes everything
// else to her bridge on lab3 with the web token, so the page runs exactly as
// it does when the bridge serves it to a browser (recording here, /hear for
// hands-free), and the token never reaches the page.
//
// Settings: ~/.config/Marina/config.json (written with defaults on first run)
// Token:    ~/.config/Marina/bridge.token (the bridge's web token, mode 600)
const { app, BrowserWindow, Menu, Tray, desktopCapturer, dialog, globalShortcut, ipcMain,
  nativeImage, screen, session, shell } = require('electron');
const fs = require('fs');
const http = require('http');
const https = require('https');
const path = require('path');
const { spawn } = require('child_process');

app.setName('Marina');
// For trying it out somewhere else (the Mac) without touching that app's settings.
if (process.env.MARINA_CONFIG_DIR) app.setPath('userData', process.env.MARINA_CONFIG_DIR);
const CONFIG_DIR = app.getPath('userData');
const CONFIG_FILE = path.join(CONFIG_DIR, 'config.json');
const TOKEN_FILE = path.join(CONFIG_DIR, 'bridge.token');
const LOG_FILE = path.join(CONFIG_DIR, 'marina.log');
const RENDERER = path.join(__dirname, 'renderer');

const DEFAULTS = {
  // Tried in order; the first that answers /health is used until it stops.
  bridges: ['http://192.168.1.15:8765', 'https://lab3.tail35b6c6.ts.net'],
  audio: {
    output: {
      // Her voice: AirPods when they're connected, else the laptop's own speaker.
      prefer: ['airpods'],
      fallback: ['built-?in', 'analog', 'speaker', 'internal', 'hdmi'],
    },
    input: {
      // Your voice: a USB mic (the wireless mic's receiver) when plugged in,
      // never the AirPods' mic (it drops them to call quality), else built in.
      prefer: ['usb', 'wireless', 'receiver', 'microphone', 'mic', 'rode', 'dji', 'hollyland', 'boya', 'saramonic'],
      fallback: ['built-?in', 'analog', 'internal'],
      avoid: ['airpods', 'monitor of', 'hands-?free', 'headset', 'integrated camera', 'webcam'],
    },
  },
  handsFree: true,
  window: null,
};

function log(...args) {
  const line = `${new Date().toISOString()} ${args.join(' ')}\n`;
  process.stdout.write(line);
  try { fs.appendFileSync(LOG_FILE, line); } catch {}
}

function loadConfig() {
  fs.mkdirSync(CONFIG_DIR, { recursive: true });
  let saved = {};
  try { saved = JSON.parse(fs.readFileSync(CONFIG_FILE, 'utf8')); } catch {}
  const cfg = { ...DEFAULTS, ...saved, audio: { ...DEFAULTS.audio, ...(saved.audio || {}) } };
  if (!fs.existsSync(CONFIG_FILE)) saveConfig(cfg);
  return cfg;
}
function saveConfig(c) {
  try { fs.writeFileSync(CONFIG_FILE, JSON.stringify(c, null, 2)); } catch (e) { log('config', e.message); }
}
const config = loadConfig();

function token() {
  try { return fs.readFileSync(TOKEN_FILE, 'utf8').trim(); } catch { return ''; }
}

// ── The bridge ─────────────────────────────────────────────────────────────
let bridge = null;        // the base URL in use

function probe(base) {
  return new Promise((resolve) => {
    const url = new URL('/health', base);
    const mod = url.protocol === 'https:' ? https : http;
    const req = mod.get(url, { headers: { Authorization: `Bearer ${token()}` }, timeout: 3500 }, (res) => {
      res.resume();
      resolve(res.statusCode === 200 ? 'ok' : res.statusCode === 403 ? 'forbidden' : 'down');
    });
    req.on('timeout', () => { req.destroy(); resolve('down'); });
    req.on('error', () => resolve('down'));
  });
}

let lastProblem = '';
let finding = null;
function findBridge() {
  if (!finding) finding = findBridgeNow().finally(() => { finding = null; });
  return finding;
}
async function findBridgeNow() {
  for (const base of config.bridges) {
    const r = await probe(base);
    if (r === 'ok') {
      if (bridge !== base) log(`bridge: ${base}`);
      bridge = base; lastProblem = '';
      return base;
    }
    if (r === 'forbidden') lastProblem = `${base} refused the token in ${TOKEN_FILE}`;
  }
  if (!lastProblem) lastProblem = !token() ? `no token in ${TOKEN_FILE}` : 'lab3 does not answer';
  bridge = null;
  return null;
}

const STATIC = new Map([
  ['.html', 'text/html; charset=utf-8'], ['.js', 'text/javascript; charset=utf-8'],
  ['.css', 'text/css; charset=utf-8'], ['.png', 'image/png'], ['.webmanifest', 'application/manifest+json'],
]);

function modelFile() {
  const mine = path.join(CONFIG_DIR, 'models', 'model.vrm');
  return fs.existsSync(mine) ? mine : path.join(__dirname, 'models', 'model.vrm');
}

function serveFile(res, file, type) {
  fs.stat(file, (err, st) => {
    if (err || !st.isFile()) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { 'Content-Type': type, 'Content-Length': st.size, 'Cache-Control': 'no-cache' });
    fs.createReadStream(file).pipe(res);
  });
}

function proxy(req, res, attempt = 0) {
  const go = (base) => {
    if (!base) {
      res.writeHead(502, { 'Content-Type': 'application/json' });
      res.end(JSON.stringify({ error: `Can't reach Marina's bridge: ${lastProblem}` }));
      return;
    }
    const url = new URL(req.url, base);
    const mod = url.protocol === 'https:' ? https : http;
    const headers = { ...req.headers, host: url.host, authorization: `Bearer ${token()}` };
    delete headers.origin; delete headers.referer; delete headers.cookie;
    const up = mod.request(url, { method: req.method, headers }, (r) => {
      res.writeHead(r.statusCode, r.headers);
      r.pipe(res);
    });
    up.on('error', async () => {
      if (res.headersSent) { res.destroy(); return; }
      // The address went away (left home: LAN → Tailscale). Try the others,
      // once, for requests without a body to replay.
      if (attempt === 0 && (req.method === 'GET' || req.method === 'HEAD')) {
        bridge = null;
        proxy(req, res, 1);
      } else {
        res.writeHead(502); res.end();
        bridge = null;
      }
    });
    // The page gave up (a long poll it abandoned): stop the upstream request too.
    // Not req's 'close', which fires as soon as its body has been read.
    res.on('close', () => { if (!res.writableFinished) up.destroy(); });
    req.pipe(up);
  };
  if (bridge) go(bridge); else findBridge().then(go);
}

function startServer() {
  return new Promise((resolve) => {
    const server = http.createServer((req, res) => {
      const p = decodeURIComponent(new URL(req.url, 'http://x').pathname);
      if (p === '/' || p === '/index.html') return serveFile(res, path.join(RENDERER, 'index.html'), STATIC.get('.html'));
      if (p === '/model.vrm') return serveFile(res, modelFile(), 'model/gltf-binary');
      if (p === '/mocap.bin') return serveFile(res, path.join(__dirname, 'models', 'mocap.bin'), 'application/octet-stream');
      if (p === '/linux.css') return serveFile(res, path.join(__dirname, 'linux.css'), STATIC.get('.css'));
      const local = path.normalize(path.join(RENDERER, p));
      const type = STATIC.get(path.extname(p));
      if (type && local.startsWith(RENDERER + path.sep) && fs.existsSync(local)) return serveFile(res, local, type);
      proxy(req, res);
    });
    server.listen(0, '127.0.0.1', () => resolve(server.address().port));
  });
}

// ── Audio devices: PipeWire tells us when they come and go ─────────────────
let pactl = null;
let devicesTimer = null;
function watchDevices() {
  try {
    pactl = spawn('pactl', ['subscribe'], { stdio: ['ignore', 'pipe', 'ignore'] });
  } catch { return; }
  pactl.stdout.on('data', (buf) => {
    if (!/'(new|remove|change)' on (sink|source|card|server)/.test(buf.toString())) return;
    clearTimeout(devicesTimer);
    devicesTimer = setTimeout(() => {
      win?.webContents.send('devices-changed');
    }, 400);
  });
  pactl.on('exit', () => { pactl = null; if (!quitting) setTimeout(watchDevices, 3000); });
}

// ── Window, tray, shortcuts ────────────────────────────────────────────────
let win = null, tray = null, port = 0, quitting = false;
const state = { wake: false, call: false, openers: true, mic: '', out: '' };

function createWindow() {
  const { workArea } = screen.getPrimaryDisplay();
  const saved = config.window;
  const height = Math.min(saved?.height || Math.round(workArea.height * 0.82), workArea.height);
  const width = saved?.width || Math.round(Math.min(workArea.width * 0.9, height * 0.58));
  win = new BrowserWindow({
    width, height,
    x: saved?.x ?? workArea.x + workArea.width - width - 20,
    y: saved?.y ?? workArea.y + Math.round((workArea.height - height) / 2),
    minWidth: 320, minHeight: 480,
    title: 'Marina',
    backgroundColor: '#14161c',
    icon: path.join(__dirname, 'build', 'icon.png'),
    autoHideMenuBar: true,
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });
  win.setMenuBarVisibility(false);
  const remember = () => {
    if (!win || win.isMinimized() || win.isMaximized()) return;
    config.window = win.getBounds();
    saveConfig(config);
  };
  win.on('moved', remember);
  win.on('resized', remember);
  win.on('close', (e) => {
    if (!quitting) { e.preventDefault(); win.hide(); refreshTray(); }
  });
  win.webContents.on('console-message', (e) => {
    if (/^\[audio\]|hands-free|setSinkId|mic swap/.test(e.message) || e.level === 'error') log('[page]', e.message);
  });
  win.webContents.setWindowOpenHandler(({ url }) => { shell.openExternal(url); return { action: 'deny' }; });
  const debug = process.argv.includes('--debug') || !!process.env.MARINA_SELFTEST;
  win.loadURL(`http://127.0.0.1:${port}/${debug ? '?debug' : ''}`);
  // MARINA_SELFTEST=steps.js: run a script against the page (tests, screenshots).
  if (process.env.MARINA_SELFTEST) {
    win.webContents.once('did-finish-load', async () => {
      const h = {
        win, log,
        js: (code) => win.webContents.executeJavaScript(code),
        wait: (ms) => new Promise((r) => setTimeout(r, ms)),
        shot: async (file) => fs.writeFileSync(file, (await win.webContents.capturePage()).toPNG()),
      };
      try { await require(path.resolve(process.env.MARINA_SELFTEST))(h); } catch (e) { log('selftest', e.stack || e); }
      if (!process.env.MARINA_SELFTEST_STAY) { quitting = true; app.quit(); }
    });
  }
}

function toggleWindow() {
  if (!win) return createWindow();
  if (win.isVisible() && win.isFocused()) win.hide(); else { win.show(); win.focus(); }
  refreshTray();
}

const AUTOSTART = path.join(app.getPath('home'), '.config', 'autostart', 'marina.desktop');
function autostartOn() { return fs.existsSync(AUTOSTART); }
function setAutostart(on) {
  if (!on) { try { fs.unlinkSync(AUTOSTART); } catch {} return; }
  const exec = process.env.APPIMAGE || process.execPath;
  fs.mkdirSync(path.dirname(AUTOSTART), { recursive: true });
  fs.writeFileSync(AUTOSTART, `[Desktop Entry]\nType=Application\nName=Marina\nExec="${exec}" --hidden\nIcon=marina\nX-GNOME-Autostart-enabled=true\n`);
}

function refreshTray() {
  if (!tray || tray.isDestroyed()) return;
  tray.setContextMenu(Menu.buildFromTemplate([
    { label: win?.isVisible() ? 'Hide Marina' : 'Show Marina', click: toggleWindow },
    { label: state.call ? 'Hang up' : 'Call Marina', click: () => { win?.show(); win?.webContents.send('toggle-call'); } },
    { type: 'separator' },
    { label: 'Listen for “Marina”', type: 'checkbox', checked: state.wake,
      click: (i) => win?.webContents.send('set-wake', i.checked) },
    { label: 'Let her speak first', type: 'checkbox', checked: state.openers,
      click: (i) => { state.openers = i.checked; win?.webContents.send('set-openers', i.checked); } },
    { type: 'separator' },
    { label: `Mic: ${state.mic || '…'}`, enabled: false },
    { label: `Her voice: ${state.out || '…'}`, enabled: false },
    { label: `Bridge: ${bridge || lastProblem || 'looking…'}`, enabled: false },
    { type: 'separator' },
    { label: 'Start at login', type: 'checkbox', checked: autostartOn(), click: (i) => setAutostart(i.checked) },
    { label: 'Settings…', click: () => shell.openPath(CONFIG_FILE) },
    { label: 'Log', click: () => shell.openPath(LOG_FILE) },
    { label: 'Reload', click: () => win?.reload() },
    { type: 'separator' },
    { label: 'Quit Marina', click: () => app.quit() },
  ]));
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'build', 'icon.png')).resize({ width: 22, height: 22 });
  tray = new Tray(icon);
  tray.setToolTip('Marina');
  tray.on('click', toggleWindow);
  refreshTray();
}

// ── Page ↔ app ─────────────────────────────────────────────────────────────
ipcMain.on('quit', () => app.quit());
ipcMain.on('minimize', () => { win?.hide(); refreshTray(); });
ipcMain.on('wake-changed', (_e, on) => { state.wake = !!on; refreshTray(); });
ipcMain.on('call-changed', (_e, on) => { state.call = !!on; refreshTray(); });
ipcMain.on('openers-changed', (_e, on) => { state.openers = !!on; refreshTray(); });
ipcMain.on('route-changed', (_e, r) => {
  if (r?.mic !== state.mic || r?.out !== state.out) log(`audio: mic ← ${r?.mic} · voice → ${r?.out}`);
  state.mic = r?.mic || ''; state.out = r?.out || '';
  refreshTray();
});
ipcMain.on('config-sync', (e) => { e.returnValue = { audio: config.audio, handsFree: config.handsFree !== false }; });

ipcMain.handle('pick-vrm', async () => {
  const r = await dialog.showOpenDialog(win, { title: 'Choose a VRM model', filters: [{ name: 'VRM', extensions: ['vrm'] }], properties: ['openFile'] });
  if (r.canceled || !r.filePaths.length) return { canceled: true };
  const dest = path.join(CONFIG_DIR, 'models', 'model.vrm');
  fs.mkdirSync(path.dirname(dest), { recursive: true });
  fs.copyFileSync(r.filePaths[0], dest);
  const buf = fs.readFileSync(dest);
  return { name: path.basename(r.filePaths[0]), buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});

ipcMain.handle('capture-screen', async () => {
  const visible = win?.isVisible();
  if (visible) win.hide();
  try {
    await new Promise((r) => setTimeout(r, 250));
    const { width, height } = screen.getPrimaryDisplay().size;
    const scale = Math.min(1, 1400 / Math.max(width, height));
    const [src] = await desktopCapturer.getSources({ types: ['screen'], thumbnailSize: { width: Math.round(width * scale), height: Math.round(height * scale) } });
    if (!src || src.thumbnail.isEmpty()) return { error: 'Could not capture the screen.' };
    return { image: src.thumbnail.toJPEG(72).toString('base64'), mime: 'image/jpeg' };
  } catch (e) {
    return { error: `Screen capture failed: ${e.message}` };
  } finally {
    if (visible) win.show();
  }
});

// ── Start ──────────────────────────────────────────────────────────────────
if (!app.requestSingleInstanceLock()) {
  app.quit();
} else {
  app.on('second-instance', () => { win?.show(); win?.focus(); });

  app.whenReady().then(async () => {
    // Her page may use the mic and pick speakers; nothing else is loaded here.
    const ses = session.defaultSession;
    const ours = (url) => { try { return new URL(url).host === `127.0.0.1:${port}`; } catch { return false; } };
    ses.setPermissionRequestHandler((wc, perm, cb, details) => cb(ours(details.requestingUrl || wc.getURL())));
    ses.setPermissionCheckHandler((wc, perm, origin) => ours(origin || wc?.getURL() || ''));
    ses.setDevicePermissionHandler(() => true);

    port = await startServer();
    log(`serving her page on 127.0.0.1:${port}`);
    findBridge().then(() => refreshTray());
    setInterval(() => findBridge().then(refreshTray), 30000);

    createWindow();
    if (process.argv.includes('--hidden')) win.once('ready-to-show', () => win.hide());
    buildTray();
    watchDevices();

    globalShortcut.register('CommandOrControl+Shift+Space', () => win?.webContents.send('toggle-listen'));
    globalShortcut.register('CommandOrControl+Shift+C', () => { win?.show(); win?.webContents.send('toggle-call'); });
    globalShortcut.register('CommandOrControl+Shift+H', toggleWindow);
    globalShortcut.register('CommandOrControl+Shift+.', () => win?.webContents.send('interrupt'));
  });
}

app.on('before-quit', () => { quitting = true; });
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  try { pactl?.kill(); } catch {}
});
app.on('window-all-closed', () => {});
