const test=require('node:test');const assert=require('node:assert/strict');const {sender,pairInput}=require('../boundary.cjs');
const valid={workspaceId:'a'.repeat(32),enrollmentId:'b'.repeat(32),code:'A'.repeat(16),name:'My device',token:'x'.repeat(43),expectedRevision:1};
test('typed IPC rejects arbitrary execution, paths, tokens and extra fields',()=>{
 assert.deepEqual(pairInput(valid),valid);
 for(const change of [{command:'touch /tmp/owned'},{workspaceId:'../../secret'},{expectedRevision:'1'},{token:'x\nCookie: secret'},{name:'bad\u0000name'},{code:'guess'}])assert.throws(()=>pairInput({...valid,...change}));
});
test('sender must be exact top-level window and exact origin',()=>{
 const frame={url:'http://127.0.0.1:4330/'};const window={webContents:{mainFrame:frame}};
 sender({sender:window.webContents,senderFrame:frame},window,'http://127.0.0.1:4330');
 assert.throws(()=>sender({sender:window.webContents,senderFrame:{url:frame.url}},window,'http://127.0.0.1:4330'));
 assert.throws(()=>sender({sender:window.webContents,senderFrame:frame},window,'https://evil.invalid'));
});
