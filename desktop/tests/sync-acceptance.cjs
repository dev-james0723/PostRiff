// Extend the existing packaged acceptance journey with a delayed successful save.
const fs=require('node:fs');const path=require('node:path');
const evidence=path.resolve(__dirname,'../../docs/postriff-phase-3/evidence/sync-desktop');
fs.mkdirSync(evidence,{recursive:true});
let source=fs.readFileSync(path.join(__dirname,'acceptance.cjs'),'utf8').replace("path.join(root,'docs/postriff-phase-3/evidence')",JSON.stringify(evidence));
const original="await area.fill('独立編輯：保留這段文字。');await page.getByRole('button',{name:'Synchronize this edit',exact:true}).click();";
const replacement=`
 let release,committed;
 const held=new Promise(resolve=>{release=resolve;});
 const savedOnServer=new Promise(resolve=>{committed=resolve;});
 let delayed=false;
 await page.route('**/actions',async route=>{
  const body=route.request().postDataJSON();
  if(body.action!=='p3_sync_edit'||delayed)return route.continue();
  delayed=true;const response=await route.fetch();committed();await held;await route.fulfill({response});
 });
 await area.fill('First save held in transit');
 await page.getByRole('button',{name:'Synchronize this edit',exact:true}).click();
 await savedOnServer;
 await area.fill('New text typed while the first save is pending');
 release();
 await page.getByRole('button',{name:'Synchronize this edit',exact:true}).waitFor();
 assert.equal(await area.inputValue(),'New text typed while the first save is pending');
 await page.getByRole('button',{name:'Synchronize this edit',exact:true}).click();
 await page.getByText('Unsent local edit',{exact:true}).waitFor({state:'hidden'});
 assert.equal(await area.inputValue(),'New text typed while the first save is pending');
 await page.unroute('**/actions');
 console.log('Delayed acknowledgement preserves newer local text: passed');
 let responseLost=false;
 await page.route('**/actions',async route=>{
  const body=route.request().postDataJSON();
  if(body.action!=='p3_sync_edit'||responseLost)return route.continue();
  responseLost=true;await route.fetch();await route.abort('failed');
 });
 await area.fill('Saved on server but response lost');
 await page.getByRole('button',{name:'Synchronize this edit',exact:true}).click();
 await page.getByRole('button',{name:'Check previous save',exact:true}).waitFor();
 await page.unroute('**/actions');
 await page.reload();
 await page.getByText('Writing runtime & devices').click();
 await page.getByText('Offline edits & conflict recovery',{exact:true}).click();
 assert.equal(await page.locator('.p3-body textarea').first().inputValue(),'Saved on server but response lost');
 await page.getByRole('button',{name:'Check previous save',exact:true}).waitFor({state:'hidden'});
 console.log('Lost response reconciles after reload: passed');
`;
if(!source.includes(original))throw Error('Base acceptance harness changed; inspect before updating');
source=source.replace(original,replacement);
new Function('require','__dirname',source)(require,__dirname);
