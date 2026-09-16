'use strict';
function requireValue(ok){if(!ok)throw new Error('Desktop request denied.');}
function sender(event, window, origin){requireValue(event.sender===window.webContents && event.senderFrame===window.webContents.mainFrame && event.senderFrame.url===origin+'/');}
function pairInput(p){
 requireValue(p && Object.getPrototypeOf(p)===Object.prototype && Object.keys(p).sort().join(',')==='code,enrollmentId,expectedRevision,name,token,workspaceId');
 for(const k of ['workspaceId','enrollmentId'])requireValue(typeof p[k]==='string'&&/^[a-f0-9]{32}$/.test(p[k]));
 requireValue(Number.isSafeInteger(p.expectedRevision)&&p.expectedRevision>0);
 requireValue(typeof p.code==='string'&&/^[A-F0-9]{16}$/.test(p.code));
 requireValue(typeof p.name==='string'&&p.name.length>0&&p.name.length<=60&&!/[\x00-\x1f]/.test(p.name));
 requireValue(typeof p.token==='string'&&/^[\w-]{32,200}$/.test(p.token));
 return p;
}
module.exports={sender,pairInput};
