// Regression test for the bug where the avatar froze whenever the window lost
// focus. Mirrors main.js's real window options, then steals focus with a second
// window and checks the animation loop is still running.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {}); ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

const sample = `(() => {
  const b = window.__marina.bones.head;
  return b ? [ +b.rotation.x.toFixed(5), +b.rotation.y.toFixed(5), +b.rotation.z.toFixed(5) ] : null;
})()`;

app.whenReady().then(async () => {
  // Exactly the options main.js uses.
  const win = new BrowserWindow({
    width: 420, height: 680, show: true,
    transparent: true, frame: false, hasShadow: false,
    backgroundColor: '#00000000', alwaysOnTop: true, skipTaskbar: true,
    titleBarStyle: 'customButtonsOnHover',
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true, nodeIntegration: false,
      backgroundThrottling: false,
    },
  });
  win.webContents.setBackgroundThrottling(false);
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 11000));

  // Steal focus, the way any other app would.
  const thief = new BrowserWindow({ width: 500, height: 400, alwaysOnTop: true });
  await thief.loadURL('data:text/html,<h1>focus thief</h1>');
  thief.focus();
  await new Promise(r => setTimeout(r, 1500));
  console.log('marina focused?', win.isFocused(), '| thief focused?', thief.isFocused());

  const samples = [];
  for (let i = 0; i < 6; i++) {
    samples.push(await win.webContents.executeJavaScript(sample));
    await new Promise(r => setTimeout(r, 700));
  }

  let moved = 0;
  for (let i = 1; i < samples.length; i++)
    for (let k = 0; k < 3; k++)
      moved = Math.max(moved, Math.abs(samples[i][k] - samples[0][k]));

  console.log('head rotation samples while UNFOCUSED:');
  samples.forEach((s, i) => console.log('  ', i, s.join(', ')));
  console.log(`\nmax movement: ${moved.toFixed(5)} rad -> ${moved > 0.001 ? 'ANIMATING (fixed)' : 'FROZEN (bug present)'}`);
  app.quit();
});
