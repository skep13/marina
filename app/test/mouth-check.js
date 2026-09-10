
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
  const errs = [];
  win.webContents.on('console-message', (_e, lvl, m) => { if (lvl >= 2) errs.push(m); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise(r => setTimeout(r, 11000));

  console.log('=== expression override flags ===');
  const flags = await win.webContents.executeJavaScript(`(() => {
    const em = window.__marina.vrm.expressionManager;
    const out = {};
    for (const e of em.expressions) {
      out[e.expressionName] = {
        mouth: e.overrideMouth, blink: e.overrideBlink, look: e.overrideLookAt, binary: e.isBinary,
      };
    }
    return out;
  })()`);
  for (const [k, v] of Object.entries(flags)) {
    if (v.mouth !== 'none' || v.blink !== 'none' || v.look !== 'none' || v.binary)
      console.log(`  ${k.padEnd(11)} mouth=${v.mouth} blink=${v.blink} look=${v.look} binary=${v.binary}`);
  }

  console.log('\n=== lip sync during real audio ===');
  const b64 = JSON.parse(fs.readFileSync(path.join(__dirname, 'probe-audio.json'), 'utf8')).b64;
  await win.webContents.executeJavaScript(`window.__probe = ${JSON.stringify(b64)}; true`);
  const started = await win.webContents.executeJavaScript(
    `window.__marina.speak(window.__probe).then(()=>{}); window.__marina.audioState()`);
  console.log('  audio context state:', started);

  const samples = [];
  for (let i = 0; i < 22; i++) {
    await new Promise(r => setTimeout(r, 260));
    samples.push(await win.webContents.executeJavaScript(`(() => {
      const m = window.__marina;
      const em = m.vrm.expressionManager;
      const v = {};
      for (const k of ['aa','ih','ou','ee','oh']) v[k] = +em.getValue(k).toFixed(2);
      return { open: +m.mouthOpen.toFixed(3), v, playing: m.isSpeaking() };
    })()`));
  }
  const open = samples.map(s => s.open);
  console.log('  frame   open   aa   ih   ou   ee   oh');
  samples.forEach((s, i) => {
    if (s.open < 0.02 && i > 2) return;
    console.log(`  ${String(i).padStart(4)} ${s.open.toFixed(2).padStart(7)} ${['aa','ih','ou','ee','oh'].map(k => s.v[k].toFixed(2).padStart(4)).join(' ')}`);
  });
  const peak = {};
  for (const k of ['aa','ih','ou','ee','oh']) peak[k] = Math.max(...samples.map(s => s.v[k]));
  console.log('\n  peak per viseme:', Object.entries(peak).map(([k,v]) => `${k}=${v.toFixed(2)}`).join('  '));
  console.log(`  visemes that actually fired: ${Object.values(peak).filter(v=>v>0.05).length}/5`);
  console.log(`  peak open ${Math.max(...open).toFixed(2)} | active frames ${open.filter(v=>v>0.02).length}/${open.length}`);
  if (errs.length) console.log('\nerrors:\n' + errs.join('\n'));
  app.quit();
});
