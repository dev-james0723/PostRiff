const {contextBridge,ipcRenderer}=require('electron');
contextBridge.exposeInMainWorld('postriffDesktop',Object.freeze({
 status:()=>ipcRenderer.invoke('postriff:status'),
 pair:(input)=>ipcRenderer.invoke('postriff:pair',input),
}));
