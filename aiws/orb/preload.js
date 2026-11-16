const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('orb', {
  settings: () => ipcRenderer.invoke('settings:get'),
  saveSettings: (s) => ipcRenderer.invoke('settings:set', s),
  toggle: () => ipcRenderer.invoke('toggle'),
  context: (opts) => ipcRenderer.invoke('context', opts),
  chat: (id, messages) => ipcRenderer.invoke('chat', { id, messages }),
  stopChat: (id) => ipcRenderer.invoke('chat:stop', id),
  api: (pathname, body, method) => ipcRenderer.invoke('api', { pathname, body, method }),
  setupStatus: () => ipcRenderer.invoke('setup:status'),
  setKey: (key) => ipcRenderer.invoke('setup:key', key),
  tailscaleUp: () => ipcRenderer.invoke('setup:tailscale'),
  on: (channel, fn) => {
    const ok = ['expanded', 'activity', 'chat-delta', 'chat-done'];
    if (ok.includes(channel)) ipcRenderer.on(channel, (_e, v) => fn(v));
  },
});
