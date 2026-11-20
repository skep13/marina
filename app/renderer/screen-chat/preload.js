const { contextBridge, ipcRenderer } = require('electron');

contextBridge.exposeInMainWorld('screenChat', {
  url: () => ipcRenderer.invoke('screen-chat:url'),
  setUrl: (url) => ipcRenderer.invoke('screen-chat:set-url', url),
  health: () => ipcRenderer.invoke('screen-chat:health'),
  say: (id, text) => ipcRenderer.invoke('screen-chat:say', { id, text }),
  power: () => ipcRenderer.invoke('screen-chat:power'),
  extend: (minutes) => ipcRenderer.invoke('screen-chat:extend', minutes),
  off: () => ipcRenderer.invoke('screen-chat:off'),
  stop: (chunks) => ipcRenderer.invoke('screen-chat:stop', chunks),
  onEvent: (cb) => ipcRenderer.on('screen-chat:event', (_e, ev) => cb(ev)),
});
