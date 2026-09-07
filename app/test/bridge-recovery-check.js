// Verifies the renderer waits for a slow bridge instead of giving up, and
// recovers if the bridge dies and comes back.
const { app, BrowserWindow, ipcMain } = require('electron');
const http = require('http');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

// A stand-in bridge we can switch on and off at will.
function fakeBridge() {
  return http.createServer((req, res) => {
    res.setHeader('Access-Control-Allow-Origin', '*');
    res.setHeader('Access-Control-Allow-Headers', '*');
    if (req.method === 'OPTIONS') { res.writeHead(204); return res.end(); }
    res.writeHead(200, { 'Content-Type': 'application/json' });
    res.end(JSON.stringify({ ok: true, model: 'fake-model', tts: 'fake', whisper_loaded: true }));
  });
}

const state = () => `(() => ({
  status: document.getElementById('status-text').textContent,
  notice: document.getElementById('notice').classList.contains('hidden') ? null
        : document.getElementById('notice').textContent.split('\\n')[0],
}))()`;

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: 420, height: 680, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));

  console.log('PHASE 1 — no bridge at all (simulating a slow cold start)');
  for (const t of [2, 6, 12]) {
    await new Promise(r => setTimeout(r, t * 1000 - (t === 2 ? 0 : (t === 6 ? 2000 : 6000))));
    const s = await win.webContents.executeJavaScript(state());
    console.log(`  t=${t}s  status="${s.status}"  notice=${s.notice ? JSON.stringify(s.notice) : 'none'}`);
  }

  console.log('\nPHASE 2 — bridge appears at ~14s');
  const srv = fakeBridge();
  await new Promise(r => srv.listen(8765, '127.0.0.1', r));
  for (const t of [2, 5]) {
    await new Promise(r => setTimeout(r, t * 1000));
    const s = await win.webContents.executeJavaScript(state());
    console.log(`  +${t}s  status="${s.status}"  notice=${s.notice ? JSON.stringify(s.notice) : 'none'}`);
  }

  console.log('\nPHASE 3 — bridge dies');
  await new Promise(r => srv.close(r));
  await win.webContents.executeJavaScript(`send('hello'); true`).catch(() => {});
  await new Promise(r => setTimeout(r, 4000));
  let s = await win.webContents.executeJavaScript(state());
  console.log(`  status="${s.status}"  notice=${s.notice ? JSON.stringify(s.notice) : 'none'}`);

  console.log('\nPHASE 4 — bridge comes back');
  const srv2 = fakeBridge();
  await new Promise(r => srv2.listen(8765, '127.0.0.1', r));
  await new Promise(r => setTimeout(r, 4000));
  s = await win.webContents.executeJavaScript(state());
  console.log(`  status="${s.status}"  notice=${s.notice ? JSON.stringify(s.notice) : 'none'}`);
  srv2.close();
  app.quit();
});
