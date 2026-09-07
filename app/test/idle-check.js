// Captures several frames over time and samples bone rotations, so we can
// verify the idle animation is actually moving and the pose looks right.
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const MODELS_DIR = path.join(ROOT, 'models');

ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(MODELS_DIR, 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {});
ipcMain.on('quit', () => {});
ipcMain.on('minimize', () => {});

const SAMPLE = `(() => {
  const m = window.__marina;
  const out = { bones: {}, hair: [], springCount: 0 };
  if (!m) return out;
  for (const n of ['chest','neck','head']) {
    const b = m.bones[n];
    if (b) out.bones[n] = [ +b.rotation.x.toFixed(4), +b.rotation.y.toFixed(4), +b.rotation.z.toFixed(4) ];
  }
  const springs = m.springs || [];
  out.springCount = springs.length;
  // Sample world positions of a spread of hair joints.
  const step = Math.max(1, Math.floor(springs.length / 8));
  for (let i = 0; i < springs.length && out.hair.length < 8; i += step) {
    const n = springs[i].joint && springs[i].joint.bone;
    if (!n) continue;
    const p = new (window.__marina.THREE ? window.__marina.THREE.Vector3 : Object)();
    n.getWorldPosition(p);
    out.hair.push([ +p.x.toFixed(5), +p.y.toFixed(5), +p.z.toFixed(5) ]);
  }
  return out;
})()`;

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 420, height: 680, show: false, backgroundColor: '#20242e',
    webPreferences: {
      preload: path.join(ROOT, 'preload.js'),
      contextIsolation: true, nodeIntegration: false, backgroundThrottling: false,
    },
  });

  const errors = [];
  win.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2) errors.push(message);
  });

  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise((r) => setTimeout(r, 11000));

  const samples = [];
  for (let i = 0; i < 4; i++) {
    const s = await win.webContents.executeJavaScript(SAMPLE).catch((e) => ({ err: String(e) }));
    samples.push(s);
    const img = await win.capturePage();
    fs.writeFileSync(path.join(__dirname, `idle-${i}.png`), img.toPNG());
    if (i < 3) await new Promise((r) => setTimeout(r, 2600));
  }

  // Report how much each bone actually moved across the samples.
  console.log('spring-bone joints found:', samples[0].springCount);
  console.log('\nbone            max delta (rad) over ~8s');
  console.log('-'.repeat(46));
  for (const n of Object.keys(samples[0].bones || {})) {
    let d = 0;
    for (let a = 0; a < samples.length; a++)
      for (let b = a + 1; b < samples.length; b++)
        for (let k = 0; k < 3; k++)
          d = Math.max(d, Math.abs(samples[a].bones[n][k] - samples[b].bones[n][k]));
    console.log(`  ${n.padEnd(16)} ${d.toFixed(4)} ${d > 0.001 ? '  moving' : '  STATIC'}`);
  }
  console.log('\nhair joint      max world displacement (m)');
  console.log('-'.repeat(46));
  const hn = (samples[0].hair || []).length;
  for (let j = 0; j < hn; j++) {
    let d = 0;
    for (let a = 0; a < samples.length; a++)
      for (let b = a + 1; b < samples.length; b++)
        for (let k = 0; k < 3; k++)
          d = Math.max(d, Math.abs(samples[a].hair[j][k] - samples[b].hair[j][k]));
    console.log(`  joint ${String(j).padEnd(10)} ${d.toFixed(5)} ${d > 0.0005 ? '  swaying' : '  STATIC'}`);
  }
  if (errors.length) console.log('\nerrors:\n' + errors.join('\n'));
  app.quit();
});
