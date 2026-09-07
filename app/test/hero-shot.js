// Captures Marina on a transparent background for the demo page.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});
app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 520, height: 820, show: false, transparent: true, frame: false,
    backgroundColor: '#00000000',
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false },
  });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 13000));
  // Hide the chat UI so the shot is just her.
  await win.webContents.executeJavaScript(`
    for (const id of ['bar','status','chrome','notice','bubble'])
      { const e = document.getElementById(id); if (e) e.style.display='none'; }
    true`);
  await new Promise(r => setTimeout(r, 600));
  fs.writeFileSync(path.join(__dirname, 'hero.png'), (await win.capturePage()).toPNG());
  console.log('wrote hero.png');
  app.quit();
});
