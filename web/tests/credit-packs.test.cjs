const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path');
const read=(p)=>fs.readFileSync(path.resolve(__dirname,'../src',p),'utf8');
test('billing exposes approved server-provided packs to owners only',()=>{
 const view=read('features/billing/billing-view.tsx');
 assert.ok(view.includes('data.credits && isOwner && <CreditPacks'));
 const client=read('lib/api/client.ts');assert.ok(client.includes('/billing/credit-packs'));assert.ok(client.includes('/billing/credit-checkout'));
});
test('a checkout return prompts verification rather than declaring payment success',()=>{
 const file=path.resolve(__dirname,'../src/features/billing/credit-packs.tsx');assert.ok(fs.existsSync(file));
 const text=fs.readFileSync(file,'utf8');assert.ok(text.includes('Refresh balance'));assert.ok(text.includes('Payment confirmation may still be processing'));
 assert.ok(text.includes('Confirm purchase'));assert.ok(text.includes('requestId'));
});
