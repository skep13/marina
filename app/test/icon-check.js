// Captures the UI chrome with controls forced visible, to inspect the icons.
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
  const errs = [];
  win.webContents.on('console-message', (_e, l, m) => { if (l >= 2) errs.push(m); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 11000));

  const info = await win.webContents.executeJavaScript(`(() => {
    document.body.classList.add('reveal');
    const out = [];
    for (const b of document.querySelectorAll('button')) {
      const svg = b.querySelector('svg');
      const r = svg ? svg.getBoundingClientRect() : null;
      out.push({ id: b.id, hasSvg: !!svg, w: r ? Math.round(r.width) : 0, h: r ? Math.round(r.height) : 0,
                 label: b.getAttribute('aria-label') });
    }
    return out;
  })()`);
  await new Promise(r => setTimeout(r, 800));
  fs.writeFileSync(path.join(__dirname, 'icons.png'), (await win.capturePage()).toPNG());

  console.log('button            svg   size    aria-label');
  console.log('-'.repeat(52));
  for (const b of info) {
    console.log(`  ${b.id.padEnd(14)} ${(b.hasSvg?'yes':'NO ')}  ${String(b.w+'x'+b.h).padEnd(7)} ${b.label || '-'}`);
  }
  if (errs.length) console.log('\nerrors:\n' + errs.join('\n'));
  app.quit();
});
