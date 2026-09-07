const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {}); ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 300, height: 300, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 12000));
  const out = await win.webContents.executeJavaScript(`(() => {
    const v = window.__marina.vrm;
    let dict = null, influences = null, meshName = null;
    v.scene.traverse(o => { if (!dict && o.isSkinnedMesh && o.morphTargetDictionary) {
      dict = o.morphTargetDictionary; influences = o.morphTargetInfluences; meshName = o.name; } });
    const entries = Object.entries(dict).map(([k, i]) => [k, +(influences[i] || 0).toFixed(3)]);
    return { meshName, entries };
  })()`);
  console.log('mesh:', out.meshName);
  console.log('\nmouth-related morphs:');
  for (const [n, val] of out.entries) if (/MTH|mouth/i.test(n)) console.log(`  ${n.padEnd(30)} ${val}`);
  const nz = out.entries.filter(([, v]) => v > 0);
  console.log('\nnon-zero right now:', nz.length ? nz.map(([n,v]) => `${n}=${v}`).join(', ') : '(none)');
  app.quit();
});
