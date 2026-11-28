// Stands in for the Mac app's preload.js. The page is served from 127.0.0.1
// by main.js, which passes bridge calls on to lab3, so app.js runs as it does
// in a browser (window.marina.web): it records its own audio and talks to
// the bridge by relative URLs. On top of that: her whole body, choosing the
// mic and speaker itself, and hands-free listening through /hear.
const { contextBridge, ipcRenderer } = require('electron');

const cfg = ipcRenderer.sendSync('config-sync');
const on = (channel) => (cb) => ipcRenderer.on(channel, (_e, v) => cb(v));

contextBridge.exposeInMainWorld('marina', {
  web: true,
  linux: true,
  framing: 'full',
  handsFree: cfg.handsFree,
  wakeByDefault: cfg.handsFree,
  audioRoute: cfg.audio,

  loadVRM: async () => {
    const res = await fetch('/model.vrm');
    if (!res.ok) return { error: 'Her model is missing from the app.' };
    return { name: 'model.vrm', buffer: await res.arrayBuffer() };
  },
  loadMocap: async () => {
    const res = await fetch('/mocap.bin');
    return res.ok ? res.arrayBuffer() : null;
  },
  pickVRM: () => ipcRenderer.invoke('pick-vrm'),
  quit: () => ipcRenderer.send('quit'),
  minimize: () => ipcRenderer.send('minimize'),
  clickThrough: () => {},
  captureScreen: () => ipcRenderer.invoke('capture-screen'),
  cameraAccess: async () => true,

  onToggleListen: on('toggle-listen'),
  onToggleCall: on('toggle-call'),
  onPickModel: on('pick-model'),
  onLookAtScreen: on('look-at-screen'),
  onBridgeDown: on('bridge-down'),
  onBridgeUp: on('bridge-up'),
  onSetOpeners: on('set-openers'),
  onInterrupt: on('interrupt'),
  onSetPreset: on('set-preset'),
  onSetStage: on('set-stage'),
  onSetWake: on('set-wake'),
  onDevicesChanged: on('devices-changed'),

  openersChanged: (v) => ipcRenderer.send('openers-changed', v),
  callChanged: (v) => ipcRenderer.send('call-changed', v),
  wakeChanged: (v) => ipcRenderer.send('wake-changed', v),
  routeChanged: (r) => ipcRenderer.send('route-changed', r),
});

window.addEventListener('DOMContentLoaded', () => {
  document.documentElement.classList.add('linux');
  const link = document.createElement('link');
  link.rel = 'stylesheet';
  link.href = '/linux.css';
  document.head.append(link);
});
