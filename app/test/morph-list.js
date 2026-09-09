// What expressions and face morphs does the loaded model actually have?
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT,'models','model.vrm'));
  return { name:'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({canceled:true}));
ipcMain.on('quit',()=>{}); ipcMain.on('minimize',()=>{}); ipcMain.on('click-through',()=>{});
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width:600, height:800, show:false, backgroundColor:'#20242e',
    webPreferences:{ preload: path.join(ROOT,'preload.js'), contextIsolation:true, backgroundThrottling:false }});
  await win.loadFile(path.join(ROOT,'renderer','index.html'));
  await new Promise(r=>setTimeout(r,14000));
  const out = await win.webContents.executeJavaScript(`(() => {
    const em = window.__marina.vrm?.expressionManager;
    const names = em ? Object.keys(em.expressionMap || {}) : [];
    const morphs = new Set();
    window.__marina.vrm?.scene.traverse(o => {
      if (o.isMesh && o.morphTargetDictionary) Object.keys(o.morphTargetDictionary).forEach(k => morphs.add(k));
    });
    return { expressions: names, brow: [...morphs].filter(m => /BRW|brow/i.test(m)),
             eye: [...morphs].filter(m => /EYE/i.test(m)).slice(0,24), total: morphs.size };
  })()`);
  console.log('  expressions:', out.expressions.join(', '));
  console.log('  brow morphs:', out.brow.join(', ') || '(none)');
  console.log('  eye morphs :', out.eye.join(', ') || '(none)');
  console.log('  total morphs:', out.total);
  app.quit();
});
