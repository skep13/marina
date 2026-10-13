const { app, BrowserWindow, Menu, Tray, desktopCapturer, ipcMain, globalShortcut, nativeImage, screen, shell, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn, execFile } = require('child_process');

// She is an overlay: always on top, put where she was left, with the window
// shaped to her. A native Wayland window can't ask for any of that, so she has
// to run as an X11 client (XWayland on a Wayland desktop). Which one a window
// gets is decided before this script runs, so it takes a flag on the command
// line. The packaged app is started through a launcher that passes it
// (build/afterPack.js); a development run (`electron .`) finds it missing here
// and starts again with it. That can't be done from inside an AppImage, whose
// files vanish when the first copy exits. MARINA_WAYLAND=1 opts out.
const insideAppImage = /\/\.mount_/.test(process.execPath);
if (app.commandLine.getSwitchValue('ozone-platform') === 'wayland' && !process.env.MARINA_WAYLAND && !insideAppImage) {
  app.relaunch({ args: [...process.argv.slice(1), '--ozone-platform=x11'] });
  app.exit(0);
}

const BUNDLED_MODELS_DIR = path.join(__dirname, 'models');

function userModelsDir() {
  return path.join(app.getPath('userData'), 'models');
}

function findModel() {
  for (const dir of [userModelsDir(), BUNDLED_MODELS_DIR]) {
    let files = [];
    try {
      files = fs.readdirSync(dir).filter((f) => f.toLowerCase().endsWith('.vrm'));
    } catch {
      continue;
    }
    if (!files.length) continue;
    files.sort();
    const chosen = files.includes('model.vrm') ? 'model.vrm' : files[0];
    return { dir, name: chosen, file: path.join(dir, chosen) };
  }
  return null;
}

function readAsTransferable(file) {
  const buf = fs.readFileSync(file);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
}

// Packaged, everything the backend needs ships inside the bundle and the
// files it writes go to Application Support. In a checkout both are the repo.
function backend() {
  if (app.isPackaged) {
    const root = path.join(process.resourcesPath, 'backend');
    return {
      root,
      data: app.getPath('userData'),
      python: path.join(root, 'python', 'bin', 'python3.12'),
      script: path.join(root, 'server', 'marina_server.py'),
    };
  }
  const root = path.join(__dirname, '..');
  return {
    root,
    data: root,
    python: path.join(root, '.venv', 'bin', 'python'),
    script: path.join(root, 'server', 'marina_server.py'),
  };
}

function configFile() {
  return path.join(backend().data, 'character_config.yaml');
}

const BRIDGE_URL = 'http://127.0.0.1:8765';

async function bridgeAlive() {
  try {
    const res = await fetch(`${BRIDGE_URL}/health`, { signal: AbortSignal.timeout(1500) });
    return res.ok;
  } catch {
    return false;
  }
}

async function startBridge() {
  if (await bridgeAlive()) {
    console.log('Bridge already running; not starting another.');
    return;
  }

  const { root, data, python, script } = backend();

  if (!fs.existsSync(python) || !fs.existsSync(script)) {
    dialog.showErrorBox(
      'Marina cannot find her backend',
      `Expected:\n  ${python}\n  ${script}\n\n` +
      (app.isPackaged
        ? 'This copy of Marina looks incomplete. Build it again.'
        : 'Run ./setup-linux.sh in the project folder.'),
    );
    return;
  }

  try {
    fs.mkdirSync(data, { recursive: true });
  } catch {}

  const logPath = path.join(app.getPath('userData'), 'bridge.log');
  let out = 'ignore';
  try {
    fs.mkdirSync(path.dirname(logPath), { recursive: true });
    out = fs.openSync(logPath, 'a');
    fs.writeSync(out, `\n--- started ${new Date().toISOString()} ---\n`);
  } catch {
    out = 'ignore';
  }

  bridge = spawn(python, [script], {
    cwd: root,
    stdio: ['ignore', out, out],
    env: {
      ...process.env,
      PYTHONUNBUFFERED: '1',
      MARINA_ROOT: root,
      MARINA_DATA: data,
    },
  });
  bridge.on('exit', (code) => {
    console.log(`Bridge exited (${code})`);
    bridge = null;
    if (!quitting) scheduleRestart(code);
  });
}

let quitting = false;
const RESTART_DELAYS = [1000, 2000, 5000, 10000, 30000];
let restartCount = 0;
let restartTimer = null;
let lastHealthy = Date.now();

function scheduleRestart(code) {
  if (restartTimer) return;

  if (Date.now() - lastHealthy > 60000) restartCount = 0;

  if (restartCount >= RESTART_DELAYS.length) {
    notifyRenderer('bridge-down',
      'Marina\u2019s backend keeps failing to start. See the bridge log.');
    return;
  }

  const wait = RESTART_DELAYS[restartCount++];
  notifyRenderer('bridge-down', `Backend stopped (${code}). Restarting\u2026`);
  restartTimer = setTimeout(async () => {
    restartTimer = null;
    await startBridge();
  }, wait);
}

function notifyRenderer(channel, message) {
  if (win && !win.isDestroyed()) win.webContents.send(channel, message);
}

function watchBridge() {
  setInterval(async () => {
    if (quitting) return;
    if (await bridgeAlive()) {
      if (restartCount) notifyRenderer('bridge-up', '');
      restartCount = 0;
      lastHealthy = Date.now();
      return;
    }

    if (bridge && Date.now() - lastHealthy > 45000) {
      console.log('Bridge is up but not responding; restarting it.');
      lastHealthy = Date.now();
      try { bridge.kill('SIGKILL'); } catch {}
    }
  }, 5000);
}

function stopBridge() {
  if (!bridge) return;
  bridge.kill('SIGTERM');
  bridge = null;
}

const STATE_FILE = () => path.join(app.getPath('userData'), 'window-state.json');

let win = null;
let tray = null;
let bridge = null;

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE(), 'utf8'));
  } catch {
    return null;
  }
}

function writeState() {
  if (!win || win.isDestroyed() || stage) return;
  const [x, y] = win.getPosition();
  try {
    fs.writeFileSync(STATE_FILE(), JSON.stringify({ x, y, overFullScreen }));
  } catch {}
}

// Where she sits in the stack. An always-on-top window stays above every
// ordinary window, but KDE keeps a full-screen app above even that. A window
// typed as a critical notification goes above the full-screen app as well. The
// price is that KDE then won't move or resize it, so the page drags her instead
// (see the pointer handlers in renderer/app.js). The type is set with xprop,
// since Electron has no way to ask for it.
const OVER_FULLSCREEN_TYPE = '_KDE_NET_WM_WINDOW_TYPE_CRITICAL_NOTIFICATION';
const ORDINARY_TYPE = '_NET_WM_WINDOW_TYPE_NORMAL';
let overFullScreen = readState()?.overFullScreen ?? true;

function canLayerOverFullScreen() {
  return process.platform === 'linux' && /KDE/.test(process.env.XDG_CURRENT_DESKTOP || '')
    && app.commandLine.getSwitchValue('ozone-platform') !== 'wayland';
}

function setWindowType(type) {
  return new Promise((resolve) => {
    if (!win || win.isDestroyed()) return resolve(false);
    const id = '0x' + win.getNativeWindowHandle().readUInt32LE(0).toString(16);
    execFile('xprop', ['-id', id, '-f', '_NET_WM_WINDOW_TYPE', '32a', '-set', '_NET_WM_WINDOW_TYPE', type], (err) => {
      if (err) console.log(`Could not set the window type (${err.message}). Is xprop installed?`);
      resolve(!err);
    });
  });
}

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));
const WINDOW_SIZE = { width: 420, height: 680 };
const SETTLE_MS = 300;
let pinnedSize = null;
let positionOffset = { x: 0, y: 0 };

// On a screen with fractional scaling, X11 turns every change of position into a
// change of size as well, growing the window by a couple of pixels each time, so
// restoring a saved size or moving her many times blows her up. Her size is
// pinned once it has settled, and a saved size is never restored.
function pinSize() {
  if (!win || win.isDestroyed()) return;
  pinnedSize = pinnedSize || win.getSize();
  win.setMinimumSize(...pinnedSize);
  win.setMaximumSize(...pinnedSize);
}

function unpinSize() {
  if (!win || win.isDestroyed()) return;
  win.setMinimumSize(0, 0);
  win.setMaximumSize(0, 0);
}

// The same screens put a window a pixel or so from where it was asked to go. The
// difference is the same every time, so measure it once and ask for it back.
async function placeExactly(x, y) {
  win.setPosition(x, y);
  await sleep(SETTLE_MS);
  const [actualX, actualY] = win.getPosition();
  positionOffset = { x: x - actualX, y: y - actualY };
  if (positionOffset.x || positionOffset.y) win.setPosition(x + positionOffset.x, y + positionOffset.y);
}

async function applyLayer() {
  const above = overFullScreen && canLayerOverFullScreen() && !stage;
  const done = canLayerOverFullScreen() ? await setWindowType(above ? OVER_FULLSCREEN_TYPE : ORDINARY_TYPE) : false;
  if (win && !win.isDestroyed()) win.webContents.send('set-drag-mode', above && done);
}

// Only where she and her controls are can be seen or clicked; the rest of the
// window is see-through and lets clicks fall to whatever is behind. The
// renderer works the area out and sends it as rectangles. (Ignoring mouse
// events instead would stop the window hearing the mouse at all on Linux, so
// it could never tell when the pointer reached her.)
const MAX_SHAPE_RECTS = 2000;

ipcMain.on('shape', (_e, rects) => {
  if (!win || win.isDestroyed() || !Array.isArray(rects)) return;
  const shape = rects.slice(0, MAX_SHAPE_RECTS)
    .map((r) => ({ x: Math.round(r.x), y: Math.round(r.y), width: Math.round(r.width), height: Math.round(r.height) }))
    .filter((r) => [r.x, r.y, r.width, r.height].every(Number.isFinite) && r.width > 0 && r.height > 0);
  win.setShape(shape);
});

// Moves arrive faster than the window manager applies them, so while a drag is
// going each one is added to where the last one was sent, not to where the
// window happens to be yet.
const DRAG_PAUSE_MS = 300;
let lastMove = null;

ipcMain.on('move-by', (_e, dx, dy) => {
  if (!win || win.isDestroyed() || stage || !Number.isFinite(dx) || !Number.isFinite(dy)) return;
  const dragging = lastMove && Date.now() - lastMove.at < DRAG_PAUSE_MS;
  const [x, y] = win.getPosition();
  const from = dragging ? lastMove : { x, y };
  const next = { x: from.x + Math.round(dx), y: from.y + Math.round(dy) };
  win.setPosition(next.x + positionOffset.x, next.y + positionOffset.y);
  lastMove = { ...next, at: Date.now() };
});

// Stage view: full screen on a solid backdrop, for turning the laptop round
// to show her to people. The renderer paints the backdrop.
let stage = false;

async function setStage(on) {
  if (!win) return;
  stage = !!on;
  if (stage) {
    await applyLayer();  // KDE won't make a notification-typed window full screen
    unpinSize();
  }
  win.setFullScreen(stage);
  if (!stage) {
    await sleep(SETTLE_MS * 2);
    pinSize();
    await applyLayer();
  }
  win.webContents.send('set-stage', stage);
  if (stage) { win.show(); win.focus(); }
}

function createWindow() {
  const saved = readState();
  const { workArea } = screen.getPrimaryDisplay();
  const { width, height } = WINDOW_SIZE;
  const x = saved?.x ?? workArea.x + workArea.width - width - 24;
  const y = saved?.y ?? workArea.y + workArea.height - height - 24;

  win = new BrowserWindow({
    width,
    height,
    x,
    y,

    transparent: true,
    frame: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: true,
    fullscreenable: true,
    icon: path.join(__dirname, 'assets', 'icon.png'),
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  win.setAlwaysOnTop(true);
  win.setVisibleOnAllWorkspaces(true);

  win.webContents.setBackgroundThrottling(false);
  win.webContents.on('did-finish-load', applyLayer);
  win.webContents.once('did-finish-load', async () => {
    pinSize();
    await placeExactly(x, y);
  });
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  // 'moved' is only sent on macOS and Windows, so save the position when the
  // moving stops instead.
  let saveTimer = null;
  const saveSoon = () => { clearTimeout(saveTimer); saveTimer = setTimeout(writeState, 400); };
  win.on('move', saveSoon);
  win.on('closed', () => { win = null; });

  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

let openersOn = true;
let wakeOn = false;

// The personalities the bridge offers, for the tray menu. Fetched when the
// menu is about to show, since the bridge owns the current choice.
let presetState = { preset: null, presets: [] };

// Whether she may use this computer, and whether the desktop has what she
// needs to (a screenshot tool, xdotool or ydotool). `available` is set once
// the bridge has answered.
let computerState = { available: false, enabled: false, screen: false, control: false };

async function fetchComputer() {
  try {
    const res = await fetch(`${BRIDGE_URL}/computer`, { signal: AbortSignal.timeout(1500) });
    if (res.ok) computerState = { ...(await res.json()), available: true };
  } catch {}
}

async function setComputer(enabled) {
  try {
    const res = await fetch(`${BRIDGE_URL}/computer`, {
      method: 'POST', headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ enabled }), signal: AbortSignal.timeout(5000),
    });
    if (res.ok) computerState = { ...(await res.json()), available: true };
  } catch {}
}

async function fetchPresets() {
  try {
    const res = await fetch(`${BRIDGE_URL}/preset`, { signal: AbortSignal.timeout(1500) });
    if (res.ok) presetState = await res.json();
  } catch {}
}

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'assets', 'icon.png'))
    .resize({ width: 32, height: 32 });
  tray = new Tray(icon);
  tray.setToolTip('Marina');

  const refresh = () => {
    tray.setContextMenu(Menu.buildFromTemplate([
      {
        label: win && win.isVisible() ? 'Hide Marina' : 'Show Marina',
        click: () => {
          if (!win || win.isDestroyed()) return createWindow();
          win.isVisible() ? win.hide() : win.show();
        },
      },
      { type: 'separator' },
      {
        label: 'Let her speak first',
        type: 'checkbox',
        checked: openersOn,
        click: (item) => {
          openersOn = item.checked;
          win?.webContents.send('set-openers', openersOn);
        },
      },
      ...(canLayerOverFullScreen() ? [{
        label: 'Show over full-screen apps',
        type: 'checkbox',
        checked: overFullScreen,
        click: (item) => { overFullScreen = item.checked; writeState(); applyLayer(); },
      }] : []),
      ...(computerState.available ? [{
        label: computerState.enabled && !(computerState.screen && computerState.control)
          ? 'Let her use this computer (needs setup)'
          : 'Let her use this computer',
        type: 'checkbox',
        checked: computerState.enabled,
        click: (item) => { setComputer(item.checked).then(refresh); },
      }] : []),
      {
        label: 'Listen for \u201cMarina\u201d',
        type: 'checkbox',
        checked: wakeOn,
        click: (item) => {
          wakeOn = item.checked;
          win?.webContents.send('set-wake', wakeOn);
        },
      },
      { type: 'separator' },
      ...presetState.presets.map((p) => ({
        label: `${p.label} mode`,
        type: 'radio',
        checked: p.name === presetState.preset,
        click: () => {
          presetState.preset = p.name;
          win?.webContents.send('set-preset', p.name);
        },
      })),
      ...(presetState.presets.length ? [{ type: 'separator' }] : []),
      {
        label: 'Stage view (full screen)',
        type: 'checkbox',
        checked: stage,
        accelerator: 'CommandOrControl+Shift+F',
        click: (item) => setStage(item.checked),
      },
      { type: 'separator' },
      { label: 'Change model…', click: () => { win?.show(); win?.webContents.send('pick-model'); } },
      { label: 'Reset position', click: () => { if (win) { placeExactly(60, 60); win.show(); } } },
      { label: 'Reload', click: () => win?.reload() },
      { label: 'Edit config…', click: () => shell.openPath(configFile()) },
      { label: 'Open bridge log', click: () => shell.openPath(path.join(app.getPath('userData'), 'bridge.log')) },
      { type: 'separator' },
      { label: 'Quit Marina', accelerator: 'CommandOrControl+Shift+Q', click: () => app.quit() },
    ]));
  };

  refresh();
  // Linux trays don't say when their menu is about to open, so keep it up to
  // date by asking the bridge every few seconds. It takes a while to start,
  // so the first answers may be missing.
  const update = () => Promise.all([fetchPresets(), fetchComputer()]).then(refresh);
  update();
  setInterval(update, 5000);
  return refresh;
}

app.whenReady().then(() => {
  startBridge();
  watchBridge();
  createWindow();
  buildTray();

  globalShortcut.register('CommandOrControl+Shift+Q', () => app.quit());
  globalShortcut.register('CommandOrControl+Shift+H', () => {
    if (!win) return createWindow();
    win.isVisible() ? win.hide() : win.show();
  });

  globalShortcut.register('CommandOrControl+Shift+.', () => {
    win?.webContents.send('interrupt');
  });
  globalShortcut.register('CommandOrControl+Shift+F', () => setStage(!stage));
  globalShortcut.register('CommandOrControl+Shift+Space', () => {
    win?.webContents.send('toggle-listen');
  });

  app.on('activate', () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on('before-quit', () => { quitting = true; });
app.on('will-quit', () => {
  globalShortcut.unregisterAll();
  if (restartTimer) clearTimeout(restartTimer);
  stopBridge();
});
app.on('window-all-closed', () => app.quit());

ipcMain.handle('load-vrm', async () => {
  const found = findModel();
  if (!found) {
    return { error: `No .vrm found in ${userModelsDir()} or ${BUNDLED_MODELS_DIR}` };
  }
  return { name: found.name, buffer: readAsTransferable(found.file) };
});

ipcMain.handle('pick-vrm', async () => {
  const res = await dialog.showOpenDialog(win, {
    title: 'Choose a VRM model',
    filters: [{ name: 'VRM', extensions: ['vrm'] }],
    properties: ['openFile'],
  });
  if (res.canceled || res.filePaths.length === 0) return { canceled: true };

  const src = res.filePaths[0];
  const dir = userModelsDir();
  try {
    fs.mkdirSync(dir, { recursive: true });

    for (const f of fs.readdirSync(dir)) {
      if (f.toLowerCase().endsWith('.vrm')) fs.rmSync(path.join(dir, f), { force: true });
    }
    const dest = path.join(dir, 'model.vrm');
    fs.copyFileSync(src, dest);
    return { name: path.basename(src), buffer: readAsTransferable(dest) };
  } catch (e) {
    dialog.showErrorBox('Could not save that model', `${dir}\n\n${e.message}`);
    return { canceled: true };
  }
});

// The bridge takes the screenshot where it can: spectacle, grim and the like
// work on Wayland, and Electron's own capture doesn't. Electron's is the
// fallback on X11.
async function bridgeScreenshot() {
  try {
    const res = await fetch(`${BRIDGE_URL}/screenshot`, { signal: AbortSignal.timeout(20000) });
    return await res.json();
  } catch (e) {
    return { error: `Screen capture failed: ${e.message}` };
  }
}

async function electronScreenshot() {
  const { width, height } = screen.getPrimaryDisplay().size;
  const scale = Math.min(1, 1400 / width);
  const sources = await desktopCapturer.getSources({
    types: ['screen'],
    thumbnailSize: {
      width: Math.round(width * scale),
      height: Math.round(height * scale),
    },
  });

  if (!sources.length) return { error: 'No screen source available.' };
  const shot = sources[0].thumbnail;
  if (shot.isEmpty()) return { error: 'Screen capture came back empty.' };
  return { image: shot.toJPEG(72).toString('base64'), mime: 'image/jpeg' };
}

ipcMain.handle('capture-screen', async () => {
  const wasVisible = win && !win.isDestroyed() && win.isVisible();
  if (wasVisible) win.hide();

  try {
    await new Promise((r) => setTimeout(r, 220));

    let shot = await bridgeScreenshot();
    if (!shot.image) {  // the first call can be slow when the machine is busy
      await sleep(1000);
      shot = await bridgeScreenshot();
    }
    if (shot.image || process.env.XDG_SESSION_TYPE === 'wayland') return shot;
    return await electronScreenshot().catch((e) => ({ error: `Screen capture failed: ${e.message}` }));
  } finally {
    if (wasVisible) win.show();
  }
});

ipcMain.on('openers-changed', (_e, on) => { openersOn = !!on; });
ipcMain.on('wake-changed', (_e, on) => { wakeOn = !!on; });
ipcMain.on('quit', () => app.quit());
ipcMain.on('minimize', () => win?.hide());
