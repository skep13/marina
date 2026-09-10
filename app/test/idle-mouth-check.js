
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {}); ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

const ALL = ['aa','ih','ou','ee','oh','happy','sad','angry','relaxed','surprised','blink','blinkLeft','blinkRight','neutral'];

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 420, height: 680, show: false, backgroundColor: '#20242e',
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 12000));

  console.log('=== expression values at IDLE (no audio) ===');
  console.log('  t     ' + ALL.map(n => n.slice(0,5).padStart(6)).join(''));
  for (let i = 0; i < 6; i++) {
    const v = await win.webContents.executeJavaScript(`(() => {
      const em = window.__marina.vrm.expressionManager;
      const o = {}; for (const n of ${JSON.stringify(ALL)}) o[n] = +em.getValue(n).toFixed(2);
      o.__mouthOpen = +window.__marina.mouthOpen.toFixed(3);
      o.__speaking = window.__marina.isSpeaking();
      return o;
    })()`);
    console.log(`  ${String(i).padEnd(6)}` + ALL.map(n => String(v[n]).padStart(6)).join('') + `   mouthOpen=${v.__mouthOpen} speaking=${v.__speaking}`);
    await new Promise(r => setTimeout(r, 1200));
  }

  fs.writeFileSync(path.join(__dirname, 'idle-mouth-normal.png'), (await win.capturePage()).toPNG());
  await win.webContents.executeJavaScript(`
    window.__marina.vrm.expressionManager.setValue('happy', 0);
    window.__marina.vrm.update(0.016); true`);
  await new Promise(r => setTimeout(r, 300));
  fs.writeFileSync(path.join(__dirname, 'idle-mouth-nohappy.png'), (await win.capturePage()).toPNG());
  console.log('\nwrote idle-mouth-normal.png and idle-mouth-nohappy.png');
  app.quit();
});
