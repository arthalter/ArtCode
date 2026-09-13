const { contextBridge, ipcRenderer } = require('electron');
contextBridge.exposeInMainWorld('artcode', {
  request: (method, params = {}) => ipcRenderer.invoke('artcode:request', method, params),
  choose: (kind) => ipcRenderer.invoke('artcode:choose', kind),
  restart: () => ipcRenderer.invoke('artcode:restart'),
  onEvent: (listener) => {
    const handler = (_, event) => listener(event);
    ipcRenderer.on('artcode:event', handler);
    return () => ipcRenderer.removeListener('artcode:event', handler);
  },
});
