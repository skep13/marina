const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT,'models','model.vrm'));
  return { name:'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({canceled:true}));
ipcMain.on('quit',()=>{}); ipcMain.on('minimize',()=>{});
app.whenReady().then(async () => {
  const win = new BrowserWindow({ width:1710, height:633, show:false, backgroundColor:'#20242e',
    webPreferences:{ preload: path.join(ROOT,'preload.js'), contextIsolation:true, backgroundThrottling:false }});
  await win.loadFile(path.join(ROOT,'renderer','index.html'));
  await new Promise(r=>setTimeout(r,12000));
  await win.webContents.executeJavaScript(`document.body.classList.add('reveal'); document.getElementById('status').click(); true`);
  await new Promise(r=>setTimeout(r,2500));
  const info = await win.webContents.executeJavaScript(`(() => {
    const p=document.getElementById('picker');
    const r=p.getBoundingClientRect();
    return { open: !p.classList.contains('hidden'),
             width: Math.round(r.width),
             centred: Math.abs((r.left+r.right)/2 - window.innerWidth/2) < 3,
             items: [...p.querySelectorAll('.pick-item')].map(i=>i.textContent.trim()),
             groups: [...p.querySelectorAll('.pick-group')].map(g=>g.textContent) };
  })()`);
  fs.writeFileSync(path.join(__dirname,'picker.png'), (await win.capturePage()).toPNG());
  console.log('  opened by clicking the status pill');
  console.log('  open:', info.open, '| width:', info.width, '| centred:', info.centred);
  console.log('  groups:', info.groups.join(' / '));
  info.items.forEach(i => console.log('   ', i));
  app.quit();
});
