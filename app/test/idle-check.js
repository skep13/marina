// Samples the idle layer over time: does she actually move, and do the head
// and eyes move together rather than as two unrelated mechanisms?
const { app, BrowserWindow, ipcMain } = require('electron');
const fs = require('fs'); const path = require('path');
const ROOT = path.join(__dirname, '..');
ipcMain.handle('load-vrm', async () => {
  const buf = fs.readFileSync(path.join(ROOT,'models','model.vrm'));
  return { name:'model.vrm', buffer: buf.buffer.slice(buf.byteOffset, buf.byteOffset+buf.byteLength) };
});
ipcMain.handle('pick-vrm', async () => ({canceled:true}));
ipcMain.on('quit',()=>{}); ipcMain.on('minimize',()=>{}); ipcMain.on('click-through',()=>{});

app.whenReady().then(async () => {
  const win = new BrowserWindow({ width:600, height:800, show:false, backgroundColor:'#20242e',
    webPreferences:{ preload: path.join(ROOT,'preload.js'), contextIsolation:true, backgroundThrottling:false }});
  const errors = [];
  win.webContents.on('console-message', (_e, level, message) => {
    if (level >= 2) errors.push(message);
  });

  await win.loadFile(path.join(ROOT,'renderer','index.html'));
  await new Promise(r=>setTimeout(r,14000));

  await win.webContents.executeJavaScript(`
    window.__marinaVec = window.__marina.camera.position.constructor;   // THREE.Vector3
    window.__samples = [];
    window.__sampler = setInterval(() => {
      const v = window.__marina.vrm; if (!v) return;
      const head = v.humanoid.getNormalizedBoneNode('head');
      const body = {};
      for (const n of ['hips','spine','chest','upperChest','leftUpperArm','rightUpperArm','leftLowerArm','leftHand']) {
        const b = v.humanoid.getNormalizedBoneNode(n);
        if (b) body[n] = [b.rotation.x, b.rotation.y, b.rotation.z];
      }
      const look = v.lookAt;
      let brow = 0;
      v.scene.traverse(o => {
        const d = o.morphTargetDictionary;
        if (o.isSkinnedMesh && d && 'Fcl_BRW_Fun' in d)
          brow = Math.max(brow, o.morphTargetInfluences[d['Fcl_BRW_Fun']] || 0);
      });
      const em = v.expressionManager;
      window.__samples.push({
        hx: head.rotation.x, hy: head.rotation.y, hz: head.rotation.z,
        gx: look.target ? look.target.position.x : 0,
        gy: look.target ? look.target.position.y : 0,
        blink: em ? em.getValue('blink') : 0,
        cues: window.__marina.activeCues,
        body,
        hair: (() => {
          const sp = window.__marina.springs || [];
          const out = []; const step = Math.max(1, Math.floor(sp.length / 6));
          const p = new window.__marinaVec();
          for (let i = 0; i < sp.length && out.length < 6; i += step) {
            const n = sp[i].joint && sp[i].joint.bone; if (!n) continue;
            n.getWorldPosition(p); out.push([p.x, p.y, p.z]);
          }
          return out;
        })(),
        brow,
      });
    }, 50);
    true`);

  await new Promise(r=>setTimeout(r,25000));

  const r = await win.webContents.executeJavaScript(`(() => {
    clearInterval(window.__sampler);
    const s = window.__samples;
    const col = k => s.map(o => o[k]);
    const range = a => Math.max(...a) - Math.min(...a);
    const mean = a => a.reduce((x,y)=>x+y,0)/a.length;
    const corr = (a,b) => {
      const ma=mean(a), mb=mean(b);
      let n=0, da=0, db=0;
      for (let i=0;i<a.length;i++){ const x=a[i]-ma, y=b[i]-mb; n+=x*y; da+=x*x; db+=y*y; }
      return n/Math.sqrt(da*db || 1e-12);
    };
    // blinks = rising edges
    let blinks=0; const bl=col('blink');
    for (let i=1;i<bl.length;i++) if (bl[i]>0.5 && bl[i-1]<=0.5) blinks++;
    // Smoothness: how spiky is the motion? Compare the largest frame-to-frame
    // acceleration against the typical one. A signal with jumps has a high
    // ratio; smooth motion stays low.
    const DEG = 180 / Math.PI;
    const step = k => {
      const a = col(k); let mx = 0, sum = 0;
      for (let i = 1; i < a.length; i++) { const d = Math.abs(a[i]-a[i-1]); mx = Math.max(mx, d); sum += d; }
      // sampled at 50ms; scale to a 16.7ms frame
      return { max: mx * DEG / 3, mean: (sum/(a.length-1)) * DEG / 3 };
    };
    const jerk = (k, quietOnly) => {
      const a = col(k), c = col('cues'); const acc = [];
      for (let i = 2; i < a.length; i++) {
        if (quietOnly && (c[i] || c[i-1] || c[i-2])) continue;   // skip gestures
        acc.push(Math.abs(a[i] - 2*a[i-1] + a[i-2]));
      }
      if (!acc.length) return { peak: 0, mean: 0, n: 0 };
      const m = mean(acc);
      return { peak: Math.max(...acc) / (m || 1e-9), mean: m, n: acc.length };
    };
    return {
      jerkYaw: jerk('hy'), jerkPitch: jerk('hx'),
      // What the eye actually notices: the largest single-frame jump.
      stepYaw: step('hy'), stepPitch: step('hx'), stepRoll: step('hz'),
      driftYaw: jerk('hy', true), driftPitch: jerk('hx', true),
      body: (() => {
        const names = Object.keys(s[0].body || {});
        const out = {};
        for (const n of names) {
          let mx = 0, step = 0;
          for (let k = 0; k < 3; k++) {
            const a = s.map(o => o.body[n][k]);
            mx = Math.max(mx, Math.max(...a) - Math.min(...a));
            for (let i = 1; i < a.length; i++) step = Math.max(step, Math.abs(a[i]-a[i-1]));
          }
          out[n] = { range: mx, step: step * 180 / Math.PI / 3 };
        }
        return out;
      })(),
      hairJoints: (s[0].hair || []).length,
      hairMoving: (() => {
        const h = s.map(o => o.hair || []); let moving = 0;
        for (let j = 0; j < (h[0]||[]).length; j++) {
          let d = 0;
          for (let i = 1; i < h.length; i++)
            for (let k = 0; k < 3; k++) d = Math.max(d, Math.abs(h[i][j][k] - h[0][j][k]));
          if (d > 0.0005) moving++;
        }
        return moving;
      })(),
      hairMax: (() => {
        const h = s.map(o => o.hair || []); let d = 0;
        for (let j = 0; j < (h[0]||[]).length; j++)
          for (let i = 1; i < h.length; i++)
            for (let k = 0; k < 3; k++) d = Math.max(d, Math.abs(h[i][j][k] - h[0][j][k]));
        return d;
      })(),
      n: s.length,
      headYaw: range(col('hy')), headPitch: range(col('hx')), headRoll: range(col('hz')),
      gazeX: range(col('gx')), gazeY: range(col('gy')),
      coupling: corr(col('gx'), col('hy')),
      blinks,
      browRange: range(col('brow')), browMean: mean(col('brow')),
    };
  })()`);

  // Gesture ordering: a bag should cover everything before repeating, and
  // never hand back the same gesture twice running.
  const g = await win.webContents.executeJavaScript(`(() => {
    const seq = []; for (let i = 0; i < 300; i++) seq.push(window.__marina.drawGesture());
    let immediate = 0;
    for (let i = 1; i < seq.length; i++) if (seq[i] === seq[i-1]) immediate++;
    const counts = {}; for (const x of seq) counts[x] = (counts[x]||0)+1;
    const n = Object.values(counts);
    return { distinct: Object.keys(counts).length, immediate,
             min: Math.min(...n), max: Math.max(...n), first: seq.slice(0,12) };
  })()`);
  console.log(`  gestures         ${g.distinct} distinct, ${g.immediate} immediate repeats, per-gesture ${g.min}-${g.max} of 300`);
  console.log(`  first draws      ${g.first.join(' ')}`);

  const secs = 25;
  console.log(`  samples          ${r.n} over ${secs}s`);
  console.log(`  head yaw range   ${r.headYaw.toFixed(4)} rad   pitch ${r.headPitch.toFixed(4)}   roll ${r.headRoll.toFixed(4)}`);
  console.log(`  gaze range       x ${r.gazeX.toFixed(3)}   y ${r.gazeY.toFixed(3)}`);
  console.log(`  head/eye coupling r=${r.coupling.toFixed(2)}  ${Math.abs(r.coupling) > 0.5 ? '(head follows eyes)' : '(UNCOUPLED)'}`);
  console.log(`  blinks           ${r.blinks}  (${(r.blinks/secs*60).toFixed(0)}/min)`);
  console.log(`  brow             mean ${r.browMean.toFixed(3)}  range ${r.browRange.toFixed(3)}`);
  console.log(`  smoothness (all) yaw ${r.jerkYaw.peak.toFixed(1)}x  pitch ${r.jerkPitch.peak.toFixed(1)}x   peak/mean accel`);
  console.log(`  drift only       yaw ${r.driftYaw.peak.toFixed(1)}x  pitch ${r.driftPitch.peak.toFixed(1)}x   (${r.driftYaw.n} gesture-free samples)`);
  console.log(`  per-frame step   yaw max ${r.stepYaw.max.toFixed(3)}deg  pitch max ${r.stepPitch.max.toFixed(3)}deg  roll max ${r.stepRoll.max.toFixed(3)}deg`);
  console.log('  body bones       range (rad) / max per-frame step (deg)');
  for (const [n, b] of Object.entries(r.body)) {
    const flag = b.range < 0.0015 ? ' STATIC' : (b.step > 0.5 ? ' JUMPY' : '');
    console.log(`    ${n.padEnd(15)} ${b.range.toFixed(4)}   ${b.step.toFixed(3)}${flag}`);
  }
  console.log(`  hair             ${r.hairMoving} of ${r.hairJoints} sampled joints swaying (max ${r.hairMax.toFixed(4)}m)`);
  if (errors.length) console.log('  renderer errors  ' + errors.length + '\n    ' + errors.slice(0,4).join('\n    '));
  else console.log('  renderer errors  none');
  console.log(`                   (a visible jump would be >0.5deg in one frame)`);
  app.quit();
});
