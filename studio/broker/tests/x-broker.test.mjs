import assert from 'node:assert/strict';
import {mkdtemp,rm} from 'node:fs/promises';
import path from 'node:path';
import test from 'node:test';
import {createXBroker,X_SCOPE} from '../x-broker.mjs';

const clientId='client_id_for_pkce_test_123';
const capability='a'.repeat(64);
const token={access_token:'access-token-for-x-test',refresh_token:'refresh-token-for-x-test',token_type:'bearer',expires_in:7200,scope:X_SCOPE};

test('X broker completes PKCE identity connection without enabling publishing',async()=>{
  const root=await mkdtemp(path.join(process.cwd(),'.x-broker-'));
  const fetchApi=async(url,options={})=>{
    if(url==='https://api.x.com/2/oauth2/token'){
      const body=options.body;
      assert.equal(body.get('client_id'),clientId);
      assert.equal(body.get('redirect_uri'),'http://127.0.0.1:4320/callback');
      assert.equal(body.get('grant_type'),'authorization_code');
      assert.match(body.get('code_verifier'),/^[A-Za-z0-9_-]{32,}$/);
      return new Response(JSON.stringify(token),{status:200});
    }
    if(url==='https://api.x.com/2/users/me'){
      assert.equal(options.headers.Authorization,'Bearer access-token-for-x-test');
      return new Response(JSON.stringify({data:{id:'1234567890',username:'jamesaucreates',name:'James Au'}}),{status:200});
    }
    throw new Error(`unexpected_url:${url}`);
  };
  const {server}=await createXBroker({port:4320,studioPort:4310,root,capability,clientId,fetchApi});
  await new Promise(resolve=>server.listen(4320,'127.0.0.1',resolve));
  try{
    const request=(path,init={})=>fetch(`http://127.0.0.1:4320${path}`,{...init,headers:{'X-Studio-Broker':capability,...init.headers}});
    const prepared=await request('/prepare',{method:'POST',body:JSON.stringify({username:'jamesaucreates',scope:X_SCOPE})});
    assert.equal(prepared.status,200);
    const {beginPath}=await prepared.json();assert.match(beginPath,/^\/begin\/[a-f0-9]{64}$/);
    const begin=await fetch(`http://127.0.0.1:4320${beginPath}`,{redirect:'manual'});
    assert.equal(begin.status,303);
    const cookie=begin.headers.get('set-cookie');assert.match(cookie,/studio_x_nonce=/);
    const authorize=new URL(begin.headers.get('location'));
    assert.equal(authorize.origin,'https://x.com');assert.equal(authorize.pathname,'/i/oauth2/authorize');
    assert.equal(authorize.searchParams.get('client_id'),clientId);assert.equal(authorize.searchParams.get('scope'),X_SCOPE);assert.equal(authorize.searchParams.get('code_challenge_method'),'S256');
    const callback=await fetch(`http://127.0.0.1:4320/callback?state=${authorize.searchParams.get('state')}&code=authorization-code-for-test`,{redirect:'manual',headers:{cookie}});
    assert.equal(callback.status,303);
    const connected=await request('/status');assert.equal(connected.status,200);
    const status=await connected.json();
    assert.equal(status.state,'connected_identity');assert.equal(status.username,'jamesaucreates');assert.equal(status.accountId,'1234567890');assert.equal(status.publishReady,false);assert.equal(status.publishing,false);assert.deepEqual(status.identitySignals,['oauth2_users_me','expected_handle_and_stable_account_id_match']);
  }finally{await new Promise(resolve=>server.close(resolve));await rm(root,{recursive:true,force:true});}
});
