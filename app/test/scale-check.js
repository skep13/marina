// Renders at an awkward window size to check the UI doesn't stretch.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('quit', () => {}); ipcMain.on('minimize', () => {});

const W = Number(process.env.W || 1710), H = Number(process.env.H || 633);
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width: W, height: H, show: false, backgroundColor: '#20242e',
    webPreferences: { preload: path.join(ROOT,'preload.js'), contextIsolation: true, backgroundThrottling: false } });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 12000));
  const m = await win.webContents.executeJavaScript(`(() => {
    document.body.classList.add('reveal');
    // #notice is display:none until something goes wrong; measure it anyway.
    const n = document.getElementById('notice'); n.classList.remove('hidden'); n.textContent = 'x';
    const g = id => { const e=document.getElementById(id); if(!e) return null;
      const r=e.getBoundingClientRect(); return {w:Math.round(r.width), l:Math.round(r.left), r:Math.round(r.right)}; };
    return { win: [window.innerWidth, window.innerHeight], bar: g('bar'), bubble: g('bubble'), notice: g('notice'), chrome: g('chrome'), status: g('status'), drag: g('drag-strip') };
  })()`);
  await new Promise(r => setTimeout(r, 500));
  fs.writeFileSync(path.join(__dirname, 'scale.png'), (await win.capturePage()).toPNG());
  console.log(`  window ${m.win[0]}x${m.win[1]}`);
  // The column the avatar sits in: everything must live inside it.
  const COL = Math.min(440, m.win[0] - 24);
  const colL = Math.round(m.win[0]/2 - COL/2), colR = Math.round(m.win[0]/2 + COL/2);
  console.log(`  column  ${colL}..${colR}`);
  for (const k of ['bar','bubble','notice','chrome','status','drag']) {
    const e = m[k]; if (!e) continue;
    const inside = e.l >= colL - 2 && e.r <= colR + 2;
    console.log(`  ${k.padEnd(7)} ${String(e.l).padStart(5)}..${String(e.r).padStart(5)}  width=${String(e.w).padStart(4)}  inColumn=${inside}${inside ? '' : '  <-- ESCAPES'}`);
  }
  app.quit();
});
