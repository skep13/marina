// Fires each cue animation and confirms it actually moves the rig / face.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {}); ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

const CUES = ['nod','shake','tilt','shrug','lean','laugh','smile','wink','eyeroll',
              'sigh','pout','sad','surprised','blush','think','brow','stare','yawn','emote'];

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 420, height: 680, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  const errs = [];
  win.webContents.on('console-message', (_e, lvl, m) => { if (lvl >= 2) errs.push(m); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 11000));

  console.log('cue          peak head move   peak expr   result');
  console.log('-'.repeat(56));

  for (const name of CUES) {
    await win.webContents.executeJavaScript(
      `window.__marina.scheduleCues([{animation:${JSON.stringify(name)},fraction:0}], 0.2); true`);

    let maxMove = 0, maxExpr = 0;
    for (let i = 0; i < 14; i++) {
      await new Promise(r => setTimeout(r, 90));
      const o = await win.webContents.executeJavaScript(`(() => {
        const c = window.__marina.cueOut;
        const e = Math.max(...Object.values(c.expr).map(v => v || 0), c.blinkLeft || 0);
        return { m: Math.max(Math.abs(c.hx), Math.abs(c.hy), Math.abs(c.hz), Math.abs(c.shoulder),
                             Math.abs(c.gazeX), Math.abs(c.gazeY)), e };
      })()`);
      maxMove = Math.max(maxMove, o.m);
      maxExpr = Math.max(maxExpr, o.e);
    }
    const ok = maxMove > 0.01 || maxExpr > 0.05;
    console.log(`  ${name.padEnd(11)} ${maxMove.toFixed(3).padStart(10)} ${maxExpr.toFixed(3).padStart(11)}   ${ok ? 'ok' : 'NO EFFECT'}`);
  }
  if (errs.length) console.log('\nerrors:\n' + errs.join('\n'));
  app.quit();
});
