
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT,'models','model.vrm'));
  return { name:'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({canceled:true}));
ipcMain.on('quit',()=>{}); ipcMain.on('minimize',()=>{}); ipcMain.on('click-through',()=>{});

const W = Number(process.env.W || 1710), H = Number(process.env.H || 633);
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width:W, height:H, show:false, backgroundColor:'#20242e',
    webPreferences:{ preload: path.join(ROOT,'preload.js'), contextIsolation:true, backgroundThrottling:false }});
  await win.loadFile(path.join(ROOT,'renderer','index.html'));
  await new Promise(r=>setTimeout(r,14000));
  const m = await win.webContents.executeJavaScript(`(() => {
    document.body.classList.add('reveal');
    const step = 8, W = window.innerWidth, H = window.innerHeight;
    let solid = 0, total = 0; const cols = new Set();
    for (let y = 4; y < H; y += step) for (let x = 4; x < W; x += step) {
      total++;
      if (window.__marina.hitTest(x,y)) { solid++; cols.add(x); }
    }
    const xs = [...cols].sort((a,b)=>a-b);
    return { W, H, total, solid, minX: xs[0], maxX: xs[xs.length-1] };
  })()`);
  const pct = (m.solid / m.total * 100).toFixed(1);
  console.log(`  window        ${m.W}x${m.H}`);
  console.log(`  solid         ${pct}% of the window (${m.solid}/${m.total} probes)`);
  console.log(`  solid span    x ${m.minX}..${m.maxX}  (${m.maxX - m.minX}px of ${m.W})`);
  console.log(`  clicks through everywhere else`);
  app.quit();
});
