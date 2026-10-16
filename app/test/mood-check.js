// A sentence's mood shows on her face while she says it and fades after.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('click-through', () => {}); ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

// The audio clock only runs once audio is allowed to play.
app.commandLine.appendSwitch('autoplay-policy', 'no-user-gesture-required');

const wait = (ms) => new Promise((r) => setTimeout(r, ms));

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 420, height: 680, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  const errs = [];
  win.webContents.on('console-message', (_e, lvl, m) => { if (lvl >= 2) errs.push(m); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await wait(11000);

  const read = (name) => win.webContents.executeJavaScript(
    `+window.__marina.vrm.expressionManager.getValue(${JSON.stringify(name)}).toFixed(3)`);
  const fails = [];

  for (const name of ['sad', 'angry', 'surprised']) {
    const before = await read(name);
    await win.webContents.executeJavaScript(`(() => {
      const m = window.__marina; m.ensureAudio();
      m.holdMood({ name: ${JSON.stringify(name)}, weight: 0.35 }, m.utterance.now, 1.5);
      return true; })()`);
    await wait(1500);
    const during = await read(name);
    await wait(5000);
    const after = await read(name);
    const ok = during > 0.25 && after < 0.05 && before < 0.05;
    console.log(`  ${name.padEnd(10)} before ${before}  during ${during}  after ${after}   ${ok ? 'ok' : 'FAIL'}`);
    if (!ok) fails.push(name);
  }

  const cam = await win.webContents.executeJavaScript(`!!document.getElementById('btn-cam')`);
  console.log(`  camera button present: ${cam ? 'ok' : 'FAIL'}`);
  if (!cam) fails.push('camera button');
  if (errs.length) console.log('\nerrors:\n' + errs.join('\n'));
  app.exit(fails.length || errs.length ? 1 : 0);
});
