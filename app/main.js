const { app, BrowserWindow, Menu, Tray, desktopCapturer, ipcMain, globalShortcut, nativeImage, screen, shell, systemPreferences, dialog } = require('electron');
const fs = require('fs');
const path = require('path');
const { spawn } = require('child_process');

// Models bundled with the app. Inside app.asar once packaged, so read-only.
const BUNDLED_MODELS_DIR = path.join(__dirname, 'models');

// Where a model YOU choose gets stored. userData is writable in both the
// packaged app and in development, and it survives rebuilds — so swapping the
// avatar doesn't get undone the next time the app is rebuilt.
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

// Where the Python side lives. Unpackaged that's the repo above this folder;
// packaged, the build writes the absolute path into the bundle so the .app can
// still find the venv and the server script.
function projectRoot() {
  if (app.isPackaged) {
    const marker = path.join(process.resourcesPath, 'project-root.txt');
    try {
      const p = fs.readFileSync(marker, 'utf8').trim();
      if (p && fs.existsSync(p)) return p;
    } catch { /* fall through */ }
  }
  return path.join(__dirname, '..');
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

/** Start the Python bridge unless one is already listening. */
async function startBridge() {
  if (await bridgeAlive()) {
    console.log('Bridge already running; not starting another.');
    return;
  }

  const root = projectRoot();
  const python = path.join(root, '.venv', 'bin', 'python');
  const script = path.join(root, 'server', 'marina_server.py');

  if (!fs.existsSync(python) || !fs.existsSync(script)) {
    dialog.showErrorBox(
      'Marina cannot find her backend',
      `Expected:\n  ${python}\n  ${script}\n\n` +
      'Run ./setup-mac.sh in the project folder, or move the folder back.',
    );
    return;
  }

  // Send the child's output straight to a file descriptor rather than piping
  // it through Node. Launched from Finder there is no stdout attached, so
  // forwarding to process.stdout blocks as soon as the pipe buffer fills —
  // which wedged the bridge before it could bind its port.
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
    env: { ...process.env, PYTHONUNBUFFERED: '1' },
  });
  bridge.on('exit', (code) => {
    console.log(`Bridge exited (${code})`);
    bridge = null;
    if (!quitting) scheduleRestart(code);
  });
}

// ---------------------------------------------------------------------------
//  Supervision
//
//  Nothing watched the bridge before: if it died she simply went quiet, with
//  no restart and nothing on screen to say why. It is the process that does
//  all the actual work, so it is the one thing here worth supervising.
//
//  Backing off matters as much as restarting. A bridge that dies immediately
//  and forever — a broken venv, a missing model — would otherwise respawn in a
//  tight loop, and the failure it is looping on is exactly the kind you want
//  to be told about rather than have hidden by a retry.
// ---------------------------------------------------------------------------

let quitting = false;      // a deliberate quit must not look like a crash
const RESTART_DELAYS = [1000, 2000, 5000, 10000, 30000];
let restartCount = 0;
let restartTimer = null;
let lastHealthy = Date.now();

function scheduleRestart(code) {
  if (restartTimer) return;

  // A bridge that ran fine for a while and then died is a fresh incident, not
  // a continuation of an old one.
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

/** Poll health so a *hung* bridge is caught too, not only one that exited. */
function watchBridge() {
  setInterval(async () => {
    if (quitting) return;
    if (await bridgeAlive()) {
      if (restartCount) notifyRenderer('bridge-up', '');
      restartCount = 0;
      lastHealthy = Date.now();
      return;
    }
    // Alive as a process but not answering: kill it so the exit handler
    // restarts it through the same path as any other death.
    if (bridge && Date.now() - lastHealthy > 45000) {
      console.log('Bridge is up but not responding; restarting it.');
      lastHealthy = Date.now();
      try { bridge.kill('SIGKILL'); } catch { /* already gone */ }
    }
  }, 5000);
}

function stopBridge() {
  if (!bridge) return;               // we didn't start it; leave it alone
  bridge.kill('SIGTERM');
  bridge = null;
}
const STATE_FILE = () => path.join(app.getPath('userData'), 'window-state.json');

let win = null;
let tray = null;
let bridge = null;          // the Python process, when we started it

function readState() {
  try {
    return JSON.parse(fs.readFileSync(STATE_FILE(), 'utf8'));
  } catch {
    return null;
  }
}

function writeState() {
  if (!win || win.isDestroyed()) return;
  const [x, y] = win.getPosition();
  const [width, height] = win.getSize();
  try {
    fs.writeFileSync(STATE_FILE(), JSON.stringify({ x, y, width, height }));
  } catch { /* not worth crashing over */ }
}

// Set by the renderer's hit test, many times a second; the no-op guard matters
// more than the call itself. Registered once — createWindow can run again.
let ignoring = true;
ipcMain.on('click-through', (_e, ignore) => {
  if (!win || win.isDestroyed() || ignore === ignoring) return;
  ignoring = ignore;
  win.setIgnoreMouseEvents(ignore, { forward: true });
});

function createWindow() {
  const saved = readState();
  const { workArea } = screen.getPrimaryDisplay();
  const width = saved?.width ?? 420;
  const height = saved?.height ?? 680;

  win = new BrowserWindow({
    width,
    height,
    x: saved?.x ?? workArea.x + workArea.width - width - 24,
    y: saved?.y ?? workArea.y + workArea.height - height - 24,
    // The transparent-desktop-pet combination:
    transparent: true,
    frame: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    resizable: true,
    skipTaskbar: true,
    fullscreenable: false,
    // A transparent window with the default title bar style still paints a
    // rounded background on macOS; 'customButtonsOnHover' does not.
    titleBarStyle: 'customButtonsOnHover',
    webPreferences: {
      preload: path.join(__dirname, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      // Chromium throttles requestAnimationFrame in unfocused windows. This is
      // a floating widget that is almost never focused, so without this the
      // whole avatar — idle motion, hair, lip sync — freezes the moment you
      // click anything else.
      backgroundThrottling: false,
    },
  });

  // A transparent window is still a solid window as far as the mouse is
  // concerned: without this, the whole rectangle swallows every click on the
  // desktop behind it. Ignore the mouse by default and let the renderer switch
  // it back on when the cursor is actually over her or over a control.
  // `forward: true` keeps mousemove flowing to the renderer so it can tell.
  win.setIgnoreMouseEvents(true, { forward: true });

  // Float above full-screen apps and follow you between Spaces.
  win.setAlwaysOnTop(true, 'floating');
  win.setVisibleOnAllWorkspaces(true, { visibleOnFullScreen: true });

  win.webContents.setBackgroundThrottling(false);
  win.loadFile(path.join(__dirname, 'renderer', 'index.html'));

  ignoring = true;   // fresh window starts click-through again

  win.on('moved', writeState);
  win.on('resized', writeState);
  win.on('closed', () => { win = null; });

  // External links open in the real browser, never inside the avatar window.
  win.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: 'deny' };
  });
}

// Whether she is allowed to speak first. Mirrored here so the tray can show
// the right label without asking the renderer.
let openersOn = true;

function buildTray() {
  const icon = nativeImage.createFromPath(path.join(__dirname, 'assets', 'trayTemplate.png'));
  icon.setTemplateImage(true);
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
      { type: 'separator' },
      { label: 'Change model…', click: () => { win?.show(); win?.webContents.send('pick-model'); } },
      { label: 'Reset position', click: () => { if (win) { win.setBounds({ x: 60, y: 60, width: 420, height: 680 }); win.show(); } } },
      { label: 'Reload', click: () => win?.reload() },
      { label: 'Open bridge log', click: () => shell.openPath(path.join(app.getPath('userData'), 'bridge.log')) },
      { type: 'separator' },
      { label: 'Quit Marina', accelerator: 'Command+Shift+Q', click: () => app.quit() },
    ]));
  };

  refresh();
  tray.on('mouse-move', refresh);
  return refresh;
}

app.whenReady().then(() => {
  startBridge();
  watchBridge();
  createWindow();
  buildTray();

  // An always-on-top transparent window with hover-only controls is very easy
  // to get stuck with. These always work, whatever the renderer is doing.
  globalShortcut.register('CommandOrControl+Shift+Q', () => app.quit());
  globalShortcut.register('CommandOrControl+Shift+H', () => {
    if (!win) return createWindow();
    win.isVisible() ? win.hide() : win.show();
  });
  // Push to talk works even when the window is hidden.
  // Cut her off from anywhere, without having to find the window first.
  globalShortcut.register('CommandOrControl+Shift+.', () => {
    win?.webContents.send('interrupt');
  });
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

// ---------- IPC ----------

ipcMain.handle('load-vrm', async () => {
  // Reading in the main process and shipping bytes over IPC avoids file://
  // fetch being blocked by CORS in the renderer.
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
    // Clear old ones so the new pick is unambiguously the one that loads.
    for (const f of fs.readdirSync(dir)) {
      if (f.toLowerCase().endsWith('.vrm')) fs.rmSync(path.join(dir, f), { force: true });
    }
    const dest = path.join(dir, 'model.vrm');
    fs.copyFileSync(src, dest);
    return { name: path.basename(src), buffer: readAsTransferable(dest) };
  } catch (e) {
    dialog.showErrorBox('Could not save that model', `${dir}

${e.message}`);
    return { canceled: true };
  }
});

/** Grab the screen once, on demand.
 *
 *  Deliberately one-shot: there is no continuous capture anywhere in this app.
 *  Marina's own window is hidden for the shot, both so she doesn't photograph
 *  herself into a hall of mirrors and so the screenshot is what YOU see.
 */
ipcMain.handle('capture-screen', async () => {
  if (process.platform === 'darwin') {
    const status = systemPreferences.getMediaAccessStatus('screen');
    if (status !== 'granted') {
      return {
        error: 'macOS has not granted screen recording permission.\n\n'
             + 'System Settings > Privacy & Security > Screen & System Audio '
             + 'Recording > enable Marina, then restart her.',
      };
    }
  }

  const wasVisible = win && !win.isDestroyed() && win.isVisible();
  if (wasVisible) win.hide();

  try {
    // Let the compositor actually remove the window before grabbing.
    await new Promise((r) => setTimeout(r, 220));

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

    // JPEG keeps the payload small; a 1400px screenshot is ~200 KB.
    return { image: shot.toJPEG(72).toString('base64'), mime: 'image/jpeg' };
  } catch (e) {
    return { error: `Screen capture failed: ${e.message}` };
  } finally {
    if (wasVisible) win.show();
  }
});

ipcMain.on('openers-changed', (_e, on) => { openersOn = !!on; });
ipcMain.on('quit', () => app.quit());
ipcMain.on('minimize', () => win?.hide());
