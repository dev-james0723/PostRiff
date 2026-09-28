/** Real navigator.credentials + Chromium virtual authenticator; NOT real-device biometric evidence. */
const { chromium } = require('playwright');
const ts = require('typescript');
const fs = require('node:fs');
const http = require('node:http');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const source = ts.transpileModule(fs.readFileSync(require('node:path').join(__dirname, '../src/lib/auth/mfa.ts'), 'utf8'), {compilerOptions:{module:ts.ModuleKind.CommonJS,target:ts.ScriptTarget.ES2022}}).outputText;
(async()=>{
 const server=http.createServer((req,res)=>{res.setHeader('Content-Type','text/html');res.end('<title>Local WebAuthn fixture</title>');});
 await new Promise(r=>server.listen(0,'127.0.0.1',r));
 const base=`http://localhost:${server.address().port}`;
 const browser=await chromium.launch({headless:true});
 try{
  const page=await browser.newPage();await page.goto(base);
  const cdp=await page.context().newCDPSession(page);await cdp.send('WebAuthn.enable');
  const {authenticatorId}=await cdp.send('WebAuthn.addVirtualAuthenticator',{options:{protocol:'ctap2',transport:'internal',hasResidentKey:true,hasUserVerification:true,isUserVerified:true,automaticPresenceSimulation:true}});
  const key=crypto.generateKeyPairSync('ec',{namedCurve:'prime256v1'});
  const id=crypto.randomBytes(32),handle=crypto.randomBytes(16);
  await cdp.send('WebAuthn.addCredential',{authenticatorId,credential:{credentialId:id.toString('base64'),isResidentCredential:true,rpId:'localhost',privateKey:key.privateKey.export({type:'pkcs8',format:'der'}).toString('base64'),userHandle:handle.toString('base64'),signCount:0}});
  const nonce=crypto.randomBytes(32).toString('base64url');
  const result=await page.evaluate(async({source,id,nonce})=>{
   const m={exports:{}};new Function('exports','module',source)(m.exports,m);
   const calls=[];
   const client={auth:{mfa:{listFactors:async()=>({data:{all:[{id:'fixture-factor',factor_type:'webauthn',status:'verified',created_at:'now'}]}})},setSession:async(s)=>{calls.push('session');return {error:null};}}};
   let credential;
   await m.exports.verifyPasskey(client,undefined,{prepare:async factor=>{calls.push(factor);return {publicKey:{challenge:nonce,rpId:'localhost',allowCredentials:[{id,type:'public-key'}],timeout:10000}};},approve:async c=>{calls.push('approve');credential=c;return {session:{access_token:'synthetic',refresh_token:'synthetic'}};}});
   return {calls,credential};
  },{source,id:id.toString('base64url'),nonce});
  assert.deepEqual(result.calls,['fixture-factor','approve','session']);
  const response=result.credential.response;
  const clientData=Buffer.from(response.clientDataJSON,'base64url'),authData=Buffer.from(response.authenticatorData,'base64url');
  assert.equal(JSON.parse(clientData).challenge,nonce);assert.equal(JSON.parse(clientData).origin,base);
  assert.ok(authData[32]&4,'user verified flag');
  assert.ok(crypto.verify('sha256',Buffer.concat([authData,crypto.createHash('sha256').update(clientData).digest()]),key.publicKey,Buffer.from(response.signature,'base64url')));
  await cdp.send('WebAuthn.setAutomaticPresenceSimulation',{authenticatorId,enabled:false});
  const cancelled=await page.evaluate(async({source,id,nonce})=>{
   const m={exports:{}};new Function('exports','module',source)(m.exports,m);let approved=false;const abort=new AbortController();
   setTimeout(()=>abort.abort(),50);
   try{await m.exports.verifyPasskey({auth:{}},'factor',{signal:abort.signal,prepare:async()=>({publicKey:{challenge:nonce,rpId:'localhost',allowCredentials:[{id,type:'public-key'}]}}),approve:async()=>{approved=true;throw new Error('must not approve');}});}catch(e){return {approved,message:e.message};}
  },{source,id:id.toString('base64url'),nonce});
  assert.equal(cancelled.approved,false);assert.match(cancelled.message,/cancelled/);
  console.log('PASS actual verifyPasskey helper, fresh call nonce, platform assertion signature + UV flag, cancellation prevents approval; virtual device only');
 }finally{await browser.close();await new Promise(r=>server.close(r));}
})().catch(e=>{console.error(e);process.exitCode=1;});
