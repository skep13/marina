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
  const win = new BrowserWindow({ width: 420, height: 680, show: false, backgroundColor: '#20242e',
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 12000));

  const info = await win.webContents.executeJavaScript(`(() => {
    const v = window.__marina.vrm;
    const h = v.humanoid;
    const bones = ['jaw','head','neck'].map(n => ({ n, has: !!h.getNormalizedBoneNode(n) }));
    const names = v.expressionManager.expressions.map(e => e.expressionName);
    // Which meshes carry mouth morph targets?
    const morphs = [];
    v.scene.traverse(o => { if (o.isSkinnedMesh && o.morphTargetDictionary)
      morphs.push({ mesh: o.name, targets: Object.keys(o.morphTargetDictionary).length }); });
    return { bones, expressions: names, morphs };
  })()`);
  console.log('humanoid bones:', info.bones.map(b => `${b.n}=${b.has}`).join(' '));
  console.log('expressions   :', info.expressions.join(', '));
  console.log('morph meshes  :', info.morphs.map(m => `${m.mesh}(${m.targets})`).join(', '));

  const measure = async (label) => {
    await new Promise(r => setTimeout(r, 400));
    const img = await win.capturePage();
    fs.writeFileSync(path.join(__dirname, `close-${label}.png`), img.toPNG());
    return label;
  };

  await win.webContents.executeJavaScript(`window.__marina.freezeIdle = true; true`).catch(()=>{});

  for (const [label, js] of [
    ['00-base',    `true`],
    ['01-neutral', `window.__marina.vrm.expressionManager.setValue('neutral',1)`],
    ['02-aa1',     `window.__marina.vrm.expressionManager.setValue('neutral',0); window.__marina.vrm.expressionManager.setValue('aa',1)`],
    ['03-reset',   `window.__marina.vrm.expressionManager.setValue('aa',0)`],
  ]) {
    await win.webContents.executeJavaScript(`${js}; window.__marina.vrm.update(0.016); true`);
    await measure(label);
  }
  console.log('\ncaptured close-00-base / 01-neutral / 02-aa1 / 03-reset');
  app.quit();
});
