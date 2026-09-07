// Verifies the window really is transparent: mirrors main.js's BrowserWindow
// options, then samples the alpha channel of a capture.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const MODELS_DIR = path.join(ROOT, 'models');

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

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 420, height: 680,
    show: false,
    transparent: true,
    frame: false,
    hasShadow: false,
    backgroundColor: '#00000000',
    alwaysOnTop: true,
    titleBarStyle: 'customButtonsOnHover',
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true,
      nodeIntegration: false,
      backgroundThrottling: false,
    },
  });

  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise((r) => setTimeout(r, 13000));

  const img = await win.capturePage();
  const { width, height } = img.getSize();
  const bmp = img.toBitmap();   // BGRA, premultiplied
  const at = (x, y) => {
    const i = (y * width + x) * 4;
    return { b: bmp[i], g: bmp[i + 1], r: bmp[i + 2], a: bmp[i + 3] };
  };

  console.log(JSON.stringify({
    size: `${width}x${height}`,
    topLeft:     at(4, 60),                                   // empty background
    topRight:    at(width - 5, 60),                           // empty background
    midLeftEdge: at(3, Math.floor(height * 0.55)),            // empty background
    centre:      at(Math.floor(width / 2), Math.floor(height * 0.35)), // avatar
  }, null, 2));

  fs.writeFileSync(path.join(__dirname, 'shot-transparent.png'), img.toPNG());
  app.quit();
});
