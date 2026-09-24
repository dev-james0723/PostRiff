const {test}=require('node:test');const assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),Module=require('node:module'),ts=require('typescript');
const filename=path.resolve(__dirname,'../src/lib/workspace/bootstrap.ts');const loaded=new Module(filename);
loaded._compile(ts.transpileModule(fs.readFileSync(filename,'utf8'),{compilerOptions:{module:ts.ModuleKind.CommonJS}}).outputText,filename);
const {bootstrapOrigin,fetchWorkspaceBootstrap}=loaded.exports;
const me={userId:'user-a',displayName:'Reader A',mfa:{enforced:false,aal:'aal1'}};
const workspaces=[{workspaceId:'space-a',name:'Only A',membership:{role:'owner'}}];
test('bootstrap origin uses configured HTTPS or explicitly local loopback; rejects host tricks',()=>{
 assert.equal(bootstrapOrigin({NEXT_PUBLIC_APP_URL:'https://staging.example.com'}),'https://staging.example.com');
 for(const url of ['http://staging.example.com','https://user:pass@example.com','https://example.com/path','https://example.com?x=1','https://example.com/#x','invalid']) assert.equal(bootstrapOrigin({NEXT_PUBLIC_APP_URL:url}),null);
 assert.equal(bootstrapOrigin({POSTRIFF_DEV_SSR:'1',POSTRIFF_API_ORIGIN:'http://127.0.0.1:4438'}),'http://127.0.0.1:4438');
 assert.equal(bootstrapOrigin({POSTRIFF_DEV_SSR:'1',POSTRIFF_API_ORIGIN:'http://localhost:4438'}),null);
 assert.equal(bootstrapOrigin({POSTRIFF_DEV_SSR:'1',VERCEL:'1',POSTRIFF_API_ORIGIN:'http://127.0.0.1:4438'}),null);
});
test('bootstrap authenticates fixed reads without cache or redirect; foreign selection cannot select a workspace',async()=>{
 const calls=[];
 const send=async(url,options)=>{calls.push([url,options]);return Response.json(url.endsWith('/me')?me:{workspaces})};
 const result=await fetchWorkspaceBootstrap('https://staging.example.com','test-token','supabase','foreign-space',send);
 assert.equal(result.workspaceId,'space-a');assert.equal(result.me.userId,'user-a');
 assert.equal(JSON.stringify(result).includes('test-token'),false);
 assert.deepEqual(calls.map(c=>c[0]).sort(),['https://staging.example.com/api/me','https://staging.example.com/api/workspaces']);
 for(const [,options] of calls){assert.equal(options.cache,'no-store');assert.equal(options.redirect,'error');assert.equal(options.headers.Authorization,'Bearer test-token');assert.ok(options.signal instanceof AbortSignal);}
});
test('bootstrap refuses failed identity, missing memberships, enforced MFA and unavailable transport',async()=>{
 for(const value of [{userId:'',mfa:me.mfa},{...me,mfa:{enforced:true,aal:'aal1'}}]) assert.equal(await fetchWorkspaceBootstrap('https://example.com','token','supabase',undefined,async url=>Response.json(url.endsWith('/me')?value:{workspaces})),null);
 assert.equal(await fetchWorkspaceBootstrap('https://example.com','token','supabase',undefined,async url=>Response.json(url.endsWith('/me')?me:{workspaces:[]})),null);
 assert.equal(await fetchWorkspaceBootstrap('https://example.com','token','supabase',undefined,async()=>new Response(null,{status:401})),null);
 assert.equal(await fetchWorkspaceBootstrap('https://example.com','token','supabase',undefined,async()=>{throw new Error('offline')}),null);
 const result=await fetchWorkspaceBootstrap('https://example.com','token','supabase',undefined,async url=>Response.json(url.endsWith('/me')?{...me,mfa:{enforced:true,aal:'aal2'}}:{workspaces}));
 assert.equal(result.me.userId,'user-a');
});
