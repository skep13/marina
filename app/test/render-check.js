
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const MODELS_DIR = path.join(ROOT, 'models');
const OUT = process.env.SHOT_OUT || path.join(__dirname, 'shot.png');
const BG = process.env.SHOT_BG || '#20242e';

ipcMain.handle('load-vrm', async () => {
  const files = fs.readdirSync(MODELS_DIR).filter((f) => f.toLowerCase().endsWith('.vrm'));
  if (!files.length) return { error: 'no vrm' };
  const chosen = files.includes('model.vrm') ? 'model.vrm' : files[0];
  const buf = fs.readFileSync(path.join(MODELS_DIR, chosen));
  return { name: chosen, buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {});
ipcMain.on('quit', () => {});
ipcMain.on('minimize', () => {});

app.disableHardwareAcceleration && null;

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 420,
    height: 680,
    show: false,
    backgroundColor: BG,
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  const logs = [];
  win.webContents.on('console-message', (_e, level, message) => {
    logs.push(`[console:${level}] ${message}`);
  });
  win.webContents.on('render-process-gone', (_e, d) => {
    logs.push(`[renderer gone] ${JSON.stringify(d)}`);
  });

  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));

  await new Promise((r) => setTimeout(r, Number(process.env.SHOT_WAIT || 12000)));

  const state = await win.webContents.executeJavaScript(`(() => {
    const c = document.getElementById('stage');
    const gl = c.getContext('webgl2') || c.getContext('webgl');
    return {
      status: document.getElementById('status-text').textContent,
      notice: document.getElementById('notice').classList.contains('hidden')
        ? null : document.getElementById('notice').textContent,
      canvas: c.width + 'x' + c.height,
      webgl: !!gl,
    };
  })()`).catch((e) => ({ error: String(e) }));

  const img = await win.capturePage();
  fs.writeFileSync(OUT, img.toPNG());

  console.log(JSON.stringify(state, null, 2));
  console.log(logs.join('\n'));
  console.log('wrote ' + OUT);
  app.quit();
});
