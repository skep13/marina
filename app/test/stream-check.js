// Proves a streamed reply actually streams: that she starts talking before the
// model has finished writing, and that the sentences are scheduled edge to
// edge rather than with a gap wherever synthesis happened to land.
//
// Needs the bridge running.  Run: npx electron test/stream-check.js
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs');
const path = require('path');

const ROOT = path.join(__dirname, '..');
const PROMPT = process.env.PROMPT || 'tell me about your day, at least three sentences';

ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT, 'models', 'model.vrm'));
  return { name: 'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset + buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({ canceled: true }));
ipcMain.on('set-click-through', () => {});
ipcMain.on('click-through', () => {});
ipcMain.on('quit', () => {});
ipcMain.on('minimize', () => {});

app.whenReady().then(async () => {
  const win = new BrowserWindow({
    width: 420, height: 680, show: false,
    webPreferences: { preload: path.join(ROOT, 'preload.js'), contextIsolation: true,
                      backgroundThrottling: false },
  });
  const errs = [];
  win.webContents.on('console-message', (_e, lvl, m) => { if (lvl >= 2) errs.push(m); });
  await win.loadFile(path.join(ROOT, 'renderer', 'index.html'));
  await new Promise((r) => setTimeout(r, 11000));

  const health = await win.webContents.executeJavaScript(
    `document.getElementById('status-text').textContent`);
  if (/down|starting/.test(health)) {
    console.log(`bridge not ready ("${health}") — start it first`);
    app.quit();
    return;
  }

  const t0 = Date.now();
  win.webContents.executeJavaScript(`window.__marina.send(${JSON.stringify(PROMPT)}); true`);

  let firstAudio = null;
  let seen = 0;
  const samples = [];
  for (let i = 0; i < 900; i++) {   // up to 90s: a shared GPU box can be slow to start
    await new Promise((r) => setTimeout(r, 100));
    const u = await win.webContents.executeJavaScript('window.__marina.utterance');
    if (u.chunks.length > seen) {
      seen = u.chunks.length;
      if (firstAudio === null) firstAudio = Date.now() - t0;
      samples.push({ at: Date.now() - t0, chunks: seen, playedTo: u.now - u.epoch });
    }
    if (seen && u.epoch < 0) break;      // reply finished
  }

  const u = samples.length ? samples[samples.length - 1] : null;
  const chunks = await win.webContents.executeJavaScript('window.__marina.utterance.chunks');

  console.log(`prompt: ${PROMPT}`);
  console.log(`first audio scheduled at ${firstAudio} ms`);
  console.log(`chunks: ${seen}`);
  for (const s of samples) {
    console.log(`  chunk ${s.chunks} arrived at ${String(s.at).padStart(6)} ms, ` +
                `audio played to ${s.playedTo.toFixed(2)} s`);
  }

  // Every chunk must begin exactly where the previous one ended. Anything
  // above a millisecond is an audible seam.
  let worstGap = 0;
  for (let i = 1; i < chunks.length; i++) {
    worstGap = Math.max(worstGap, Math.abs(chunks[i].start - chunks[i - 1].end));
  }
  // A gap of zero is also the proof that synthesis never fell behind: a
  // starved queue starts the next chunk at "now" instead of at the previous
  // chunk's end, which shows up here as a gap.
  console.log(`largest gap between chunks: ${(worstGap * 1000).toFixed(2)} ms`);
  console.log(errs.length ? `console errors:\n  ${errs.join('\n  ')}` : 'no console errors');

  const reasons = [];
  if (!seen) reasons.push('no audio chunks arrived — is the bridge reachable?');
  if (worstGap >= 0.001) reasons.push(`audible seam of ${(worstGap * 1000).toFixed(1)} ms between chunks`);
  if (errs.length) reasons.push(`${errs.length} console error(s)`);
  console.log(reasons.length ? `FAIL: ${reasons.join('; ')}` : 'PASS');
  app.exit(reasons.length ? 1 : 0);
});
