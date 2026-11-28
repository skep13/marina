// Loads the renderer with the Mac preload, runs JS steps and saves PNGs.
//   electron test/shot-harness.js <script.js>
// The script exports async (h) => {...}; h.js(code), h.shot(name), h.wait(ms).
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('load-mocap', async () => {
  const f = process.env.MOCAP_FILE || path.join(ROOT, 'models', 'mocap.bin');
  if (!fs.existsSync(f)) return null;
  const buf = fs.readFileSync(f);
  return buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength);
});
for (const ch of ['pick-vrm', 'capture-screen', 'camera-access']) ipcMain.handle(ch, async () => ({ canceled: true }));
for (const ch of ['click-through', 'quit', 'minimize', 'openers-changed', 'wake-changed', 'call-changed']) ipcMain.on(ch, () => {});

const script = require(path.resolve(process.argv[process.argv.length - 1]));
const OUT = process.env.SHOT_DIR || path.join(ROOT, 'test');
app.whenReady().then(async () => {
  const [w, hgt] = (process.env.SHOT_SIZE || '540x960').split('x').map(Number);
  const win = new BrowserWindow({ width: w, height: hgt, show: false, backgroundColor: '#20242e',
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  win.webContents.on('console-message', (e) => { if (e.level === 'error' || e.level === 'warning') console.log('[page]', e.message); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'), { search: 'debug' + (process.env.SHOT_QUERY || '') });
  const h = {
    js: (code) => win.webContents.executeJavaScript(code),
    wait: (ms) => new Promise((r) => setTimeout(r, ms)),
    shot: async (name) => {
      const img = await win.webContents.capturePage();
      fs.writeFileSync(path.join(OUT, `${name}.png`), img.toPNG());
    },
  };
  for (let i = 0; i < 60; i++) { if (await h.js('!!window.__marina?.vrm')) break; await h.wait(250); }
  try { await script(h); } catch (e) { console.log('script error', e.stack || e); }
  app.quit();
});
