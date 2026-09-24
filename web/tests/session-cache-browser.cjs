/** Real React/browser race test; synthetic identities and deferred transports, no API/DB claim. */
const assert=require('node:assert/strict');
const path=require('node:path');const http=require('node:http');
const root=path.resolve(__dirname,'../..');
const deps=process.env.WEB_DEPENDENCIES||path.join(root,'.codex/consumer-ready/web/node_modules');
const {build}=require(process.env.ESBUILD_MODULE||path.join(root,'.codex/consumer-ready/vercel/node_modules/esbuild'));
const {chromium}=require(path.join(deps,'playwright'));
(async()=>{
 const result=await build({stdin:{contents:`
 import React,{useState,useEffect} from 'react';import {createRoot} from 'react-dom/client';
 import {useQuery,useQueryClient} from '@tanstack/react-query';
 import {SessionQueryBoundary} from './src/lib/auth/session-query-boundary';
 window.clients=[];window.revoked=[];const revoke=URL.revokeObjectURL;URL.revokeObjectURL=url=>{window.revoked.push(url);revoke(url)};
 function Workspace({identity}) {const [draft,setDraft]=useState('');const client=useQueryClient();
 useEffect(()=>{window.clients.push(client);if(identity==='alpha'){const url=URL.createObjectURL(new Blob(['private-alpha']));window.privateMedia=url;client.setQueryData(['media','alpha'],url);}},[client]);
 const me=useQuery({queryKey:['me'],queryFn:()=>identity==='alpha'?new Promise(resolve=>{window.finishAlpha=()=>resolve('PRIVATE ALPHA')}):Promise.resolve('BETA'),retry:false});
 return <><output>{me.data??'Loading'}</output><input aria-label='Draft' value={draft} onChange={e=>setDraft(e.target.value)}/></>;
 }
 function App(){const [identity,setIdentity]=useState('alpha');return <><button onClick={()=>setIdentity('beta')}>Switch identity</button><SessionQueryBoundary identity={identity}><Workspace identity={identity}/></SessionQueryBoundary></>}
 createRoot(document.getElementById('root')).render(<App/>);
 `,resolveDir:path.join(root,'web'),loader:'tsx'},bundle:true,write:false,platform:'browser',jsx:'automatic',define:{'process.env.NODE_ENV':'"production"'},alias:{'@':path.join(root,'web/src'),react:path.join(deps,'react'),'react-dom':path.join(deps,'react-dom'),'@tanstack/react-query':path.join(deps,'@tanstack/react-query')},nodePaths:[deps]});
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type',req.url==='/app.js'?'application/javascript':'text/html');res.end(req.url==='/app.js'?result.outputFiles[0].contents:'<div id="root"></div><script src="/app.js"></script>')});
 await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const base='http://127.0.0.1:'+server.address().port;
 const browser=await chromium.launch({headless:true,...(process.env.BROWSER_EXECUTABLE?{executablePath:process.env.BROWSER_EXECUTABLE}:{})});
 try{const page=await browser.newPage();const errors=[];page.on('pageerror',e=>errors.push(e.message));await page.route('**/*',r=>new URL(r.request().url()).origin===base?r.continue():r.abort());
 await page.goto(base);await page.waitForFunction(()=>Boolean(window.finishAlpha));await page.getByLabel('Draft').fill('private alpha draft');await page.getByRole('button',{name:'Switch identity'}).click();await page.getByText('BETA',{exact:true}).waitFor();
 await page.evaluate(()=>window.finishAlpha());await page.waitForFunction(()=>window.revoked.includes(window.privateMedia));
 assert.equal(await page.getByLabel('Draft').inputValue(),'');assert.equal(await page.locator('output').textContent(),'BETA');assert.equal(await page.getByText('PRIVATE ALPHA',{exact:true}).count(),0);
 assert.equal(await page.evaluate(()=>window.clients.length===2&&window.clients[0]!==window.clients[1]&&window.clients[0].getQueryData(['me'])===undefined&&window.clients[0].getQueryData(['media','alpha'])===undefined),true);assert.deepEqual(errors,[]);
 console.log('PASS real browser: identity switch resets workspace fields, isolates identical cache keys, cancels late private response, revokes private media URL');
 }finally{await browser.close();await new Promise(resolve=>server.close(resolve))}
})().catch(e=>{console.error(e);process.exitCode=1});
