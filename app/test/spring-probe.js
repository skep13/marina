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
  const win = new BrowserWindow({ width: 420, height: 680, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 11000));
  const out = await win.webContents.executeJavaScript(`(() => {
    const springs = window.__marina.springs || [];
    const powers = {}, stiff = {}, drag = {};
    for (const s of springs) {
      const st = s.joint.settings;
      powers[st.gravityPower.toFixed(3)] = (powers[st.gravityPower.toFixed(3)]||0)+1;
      stiff[st.stiffness.toFixed(3)] = (stiff[st.stiffness.toFixed(3)]||0)+1;
      drag[st.dragForce.toFixed(3)] = (drag[st.dragForce.toFixed(3)]||0)+1;
    }
    const s0 = springs[4] && springs[4].joint.settings;
    return { count: springs.length, gravityPower: powers, stiffness: stiff, dragForce: drag,
             sampleDir: s0 ? [s0.gravityDir.x, s0.gravityDir.y, s0.gravityDir.z] : null };
  })()`);
  console.log(JSON.stringify(out, null, 2));
  app.quit();
});
