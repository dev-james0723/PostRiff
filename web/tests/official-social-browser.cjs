/** Cloud-only UI acceptance. Provider API responses are synthetic; this never qualifies live OAuth/publishing. */
const assert = require('node:assert/strict');
const {spawn} = require('node:child_process');
const {readFileSync,mkdirSync,writeFileSync} = require('node:fs');
const {join} = require('node:path');
const {chromium} = require('playwright');
assert.equal(process.platform,'linux','Route browser acceptance through JCB');
assert.ok(process.env.CI,'Cloud CI required');
const base='http://127.0.0.1:4439';
const fixture=JSON.parse(readFileSync(join(__dirname,'fixtures/wp04a-workspace.json'),'utf8'));
const wid=fixture.snapshot.state.workspace.id;
const otherWid='00000000-0000-0000-0000-000000000099';
const out=join(__dirname,'../../.depot/social-browser-evidence');mkdirSync(out,{recursive:true});
const app=spawn(process.execPath,['node_modules/next/dist/bin/next','dev','-p','4439','-H','127.0.0.1'],{cwd:join(__dirname,'..'),env:process.env,stdio:['ignore','pipe','pipe']});
app.stdout.on('data',chunk=>process.stdout.write(chunk));app.stderr.on('data',chunk=>process.stderr.write(chunk));
const feature=(group,granted)=>({officialSupport:'documented',permission_group:group,implemented:true,appApproved:false,granted,eligible:false,liveE2E:false,state:'BLOCKED',blockers:['APP APPROVAL NOT VERIFIED','LIVE E2E NOT PROVEN'],limitation:''});
const identity=feature('identity',true),publish=feature('publish',false),comments=feature('comments_read',true);
const channel={id:'fixture-ig',platform:'Instagram',account:'Ordinary fixture creator',accountType:'professional',connectionState:'read_verified',evidenceSource:'fixture',providerAccountId:'1789',language:'English',capabilityVersion:1,scopes:['instagram_business_basic','instagram_business_manage_comments'],expiresAt:Date.now()/1000+864000,verifiedAt:Date.now()/1000,canManage:true,capabilities:{identity:{level:'Direct'},publish:{level:'Unsupported'},comments_read:{level:'Direct'},reply:{level:'Direct'}},officialCapabilities:{identity,publish,comments_read:comments},socialReadiness:{connection:'CONNECTED',publishing:'PUBLISHING_PERMISSION_UNAVAILABLE',history:'HISTORICAL_IMPORT_UNAVAILABLE',fullyAvailable:false,evidence:'last_verified_grant',liveVerified:false}};
const provider={id:'instagram',platform:'Instagram',configured:true,connectReady:true,capabilities:{identity:true,publish:true,comments_read:true},officialCapabilities:channel.officialCapabilities};
(async()=>{
 let browser;const checks=[];
 try {
  let ready=false;for(let i=0;i<120;i++){if(await fetch(base).then(r=>r.status<500).catch(()=>false)){ready=true;break;}await new Promise(r=>setTimeout(r,500));}
  assert.ok(ready,'Cloud Next server started');browser=await chromium.launch({headless:true});
  for(const width of [1280,390]){
   const context=await browser.newContext({viewport:{width,height:900},reducedMotion:'reduce'});
   await context.addCookies([{name:'postriff_dev',value:'1',url:base}]);
   await context.addInitScript(()=>{localStorage.setItem('postriff-dev-principal','00000000-0000-0000-0000-000000000001');localStorage.setItem('postriff-onboarding:00000000-0000-0000-0000-000000000001',JSON.stringify({completed:{},dismissed:{welcome:1},nudged:{}}));});
   let sends=0,reads=0,completionWorkspace=null,activeChannel=channel,activeProvider=provider,activeSnapshot=fixture.snapshot;const page=await context.newPage();page.setDefaultTimeout(30000);
   await context.route('**/*',async route=>{
    const request=route.request(),url=new URL(request.url()),p=url.pathname;
    if(url.origin!==base)return route.abort();if(!p.startsWith('/api/'))return route.continue();
    const send=(body,status=200)=>route.fulfill({status,contentType:'application/json',body:JSON.stringify(body)});
    if(p.endsWith('/native-read')){reads++;return send({provider:'instagram',feature:'comments_read',availability:'available',data:{data:[{id:'comment-7',text:'Question from reader',username:'Reader',parent_id:'post-1'}]},provenance:{kind:'provider_native',provider:'instagram',reportingPeriod:{}},rate:{}});}
    if(p.endsWith('/native-action'))return send({id:'action-1',state:'preview',digest:'immutable-digest',manifest:{action:'reply',target:'comment-7',platform:'Instagram',providerAccountId:'1789',payload:{text:request.postDataJSON().payload.text}}},201);
    if(p.endsWith('/approve')){sends++;return send({executionState:'uncertain',message:'Synthetic timeout: reconcile before any new approval.'});}
    if(p==='/api/oauth/instagram/context')return send({workspaceId:wid});
    if(p.endsWith('/oauth/complete')){completionWorkspace=p.split('/')[3];return send({connected:true,connectionId:channel.id,account:channel.account,missingScopes:[]});}
    if(request.method()!=='GET')return send({error:'Unexpected synthetic mutation'},400);
    if(p==='/api/catalog')return send({authMode:'dev',execution:'dev-synthetic',phase2:true,templates:[],routes:[],profileMetadata:{}});
    if(p==='/api/workspaces')return send({workspaces:[{workspaceId:wid,membership:fixture.snapshot.membership,name:'Social fixture',plan:'studio',memberCounts:{owner:1}},{workspaceId:otherWid,membership:fixture.snapshot.membership,name:'Other workspace',plan:'studio',memberCounts:{owner:1}}]});
    if(p==='/api/me')return send({userId:'00000000-0000-0000-0000-000000000001',displayName:'Fixture',preferences:{timeZone:'UTC',locale:'en'},mfa:{}});
    if(p===`/api/workspaces/${otherWid}`)return send({...fixture.snapshot,state:{...fixture.snapshot.state,workspace:{...fixture.snapshot.state.workspace,id:otherWid}}});
    if(p===`/api/workspaces/${wid}`)return send(activeSnapshot);
    if(p.endsWith('/channels'))return send({channels:[activeChannel],providers:[activeProvider]});
    if(p.endsWith('/usage'))return send({entitlement:{planTermsId:'synthetic-studio',writingBatchesRemaining:1,mediaCreditsRemaining:0,connectedAccounts:10,members:1,storageMb:100,resetsAt:null,source:'fixture',version:1},subscription:null,budget:null,overage:'disabled',ledger:[],planTerms:[],note:'Synthetic browser acceptance',lifecycle:{status:'active',canPublish:false},membership:fixture.snapshot.membership});
    if(p.endsWith('/memory'))return send(fixture.memory);
    if(p.endsWith('/memory/proposals'))return send({pending:[],recent:[],learning:{items:[]}});
    return send({error:'Unhandled synthetic read'},404);
   });
   await page.goto(base+'/app/channels',{waitUntil:'domcontentloaded'});
   await page.getByText('Ordinary fixture creator',{exact:true}).first().waitFor();
   await page.getByText('Individual capabilities and verification',{exact:true}).click();
   await page.getByRole('list',{name:'Official capabilities'}).waitFor();
   await page.getByText('Connected — publishing not enabled.',{exact:true}).waitFor();
   await page.getByText('Identity verified for this account',{exact:false}).waitFor();
   assert.equal(await page.getByText('Ready · live tested',{exact:false}).count(),0);
   assert.equal(await page.getByRole('button',{name:'Enable Publish',exact:true}).count(),1);
   await page.getByText('Read post metrics and conversations',{exact:true}).click();
   await page.getByLabel('Post identifier',{exact:true}).fill('post-1');
   await page.getByRole('button',{name:'Read comments and replies',exact:true}).click();
   await page.getByText('Question from reader',{exact:true}).waitFor();
   await page.getByRole('button',{name:'Prepare reply',exact:true}).click();
   await page.getByLabel('Your exact reply').fill('Approved fixture reply');
   await page.getByRole('button',{name:'Review reply',exact:true}).click();
   await page.getByRole('button',{name:'Approve and send this reply',exact:true}).click();
   await page.getByText('Synthetic timeout: reconcile before any new approval.',{exact:true}).waitFor();
   assert.equal(sends,1);assert.equal(reads,1);assert.equal(await page.getByRole('button',{name:'Approve and send this reply',exact:true}).count(),0);
   const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);assert.equal(overflow,false);
   await page.screenshot({path:join(out,`social-${width}.png`),fullPage:true});
   const pixels=readFileSync(join(out,`social-${width}.png`));assert(pixels.length<1_000_000,'Bounded synthetic screenshot evidence');
   // JCB's reviewed workflow currently exports logs rather than arbitrary output
   // artifacts. This bounded fixture-only image is recovered from those logs.
   console.log('RAFII_BROWSER_IMAGE '+width+' '+pixels.toString('base64'));
   // Observed preview incident shape, still entirely synthetic: saved member
   // identity and verified OIDC product must not inherit publication blockers.
   const memberIdentity={...identity,appApproved:true,eligible:true,blockers:['LIVE E2E NOT PROVEN']};
   activeChannel={...channel,id:'fixture-li',platform:'LinkedIn',account:'LinkedIn identity fixture',accountType:'member',scopes:['openid','profile'],identityVerifiedAt:Date.now()/1000,capabilities:{...channel.capabilities,identity:{...channel.capabilities.identity,verifiedAt:Date.now()/1000-7200}},socialReadiness:{...channel.socialReadiness,publishing:'PUBLISHING_AWAITING_PROVIDER_REVIEW'},officialCapabilities:{connected:memberIdentity,member_identity:memberIdentity,member_publish:publish,organization_identity:{...identity,granted:false,permission_group:'organization_identity'}}};
   activeProvider={...provider,id:'linkedin',platform:'LinkedIn',capabilities:{identity:true,publish:true},memberPublishingStatus:{approved:false,code:'callback_mismatch',message:'Rafii member publishing access is not verified for this deployment. The operator must reconcile the registered callback with the exact callback generated by this deployment.'},officialCapabilities:activeChannel.officialCapabilities};
   await page.reload({waitUntil:'domcontentloaded'});
   await page.getByText('LinkedIn identity fixture',{exact:true}).waitFor();
   const identityReadTime=await page.getByText(/^Verified /).first().textContent();
   assert.match(identityReadTime,/^Verified /);assert.doesNotMatch(identityReadTime,/hours? ago/);
   await page.getByText('Connected — publishing not enabled.',{exact:true}).waitFor();
   await page.getByText('Individual capabilities and verification',{exact:true}).click();
   assert.equal(await page.getByText('Identity verified for this account',{exact:false}).count(),2);
   assert.equal(await page.getByText('Public release verification pending',{exact:true}).count(),2);
   assert.equal(await page.getByText('Ready · live tested',{exact:false}).count(),0);
   await page.getByText('Rafii’s LinkedIn publishing setup is incomplete. Your account remains connected; the Rafii operator needs to finish setup.',{exact:true}).waitFor();
   assert.equal(await page.getByText(activeProvider.memberPublishingStatus.message,{exact:true}).count(),0,'Customer setup copy never asks them to edit callback/env/client evidence');
   const publishRow=page.getByRole('list',{name:'Official capabilities'}).getByRole('listitem').filter({hasText:'Member publish'});
   assert.match(await publishRow.innerText(),/Platform approval unverified/);
   const sharePermission={...publish,appApproved:true,granted:true,eligible:true,blockers:['LIVE E2E NOT PROVEN']};
   activeChannel={...activeChannel,scopes:['openid','profile','w_member_social'],socialReadiness:{...activeChannel.socialReadiness,publishing:'PUBLISHING_AVAILABLE'},officialCapabilities:{...activeChannel.officialCapabilities,member_publish:sharePermission}};
   activeProvider={...activeProvider,memberPublishingApproved:true,memberPublishingStatus:{approved:true,code:'share_access_verified',message:'Synthetic verified Share product for this deployment.'},productionReviewed:false,officialCapabilities:activeChannel.officialCapabilities};
   await page.reload({waitUntil:'domcontentloaded'});
   await page.getByText('Connected — publishing permission granted; verification pending.',{exact:true}).waitFor();
   await page.getByText('Individual capabilities and verification',{exact:true}).click();
   assert.equal(await page.getByText('Ready · live tested',{exact:false}).count(),0);
   assert.match(await page.getByRole('list',{name:'Official capabilities'}).getByRole('listitem').filter({hasText:'Member publish'}).innerText(),/Live test pending/);
   assert.match(await page.getByRole('list',{name:'Official capabilities'}).getByRole('listitem').filter({hasText:'Organization identity'}).innerText(),/Platform approval unverified/);
   await page.getByRole('button',{name:'Connect another account',exact:true}).click();
   assert.equal(await page.getByRole('radio',{name:'Account only',exact:false}).isChecked(),true);
   assert.equal(await page.getByRole('radio',{name:'Publish',exact:false}).isChecked(),false);
   await page.keyboard.press('Escape');
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1),false);
   // A201 receipt is useful before restricted member read access exists. This
   // is a fixture of the normal Queue receipt, never real provider evidence.
   const acceptedJob={...structuredClone(fixture.snapshot.state.phase2.jobs[0]),id:'fixture-linkedin-accepted',state:'provider_accepted',providerReference:'urn:li:share:123',url:'https://www.linkedin.com/feed/update/urn:li:share:123/',verification:null,providerConfirmed:'LinkedIn accepted this post. Restricted read permission is unavailable; open the post to confirm publication. Do not resubmit.',nextAt:Date.now()/1000+86400,events:[{state:'provider_accepted',at:Date.now()/1000,message:'LinkedIn accepted this post. Restricted read permission is unavailable; open the post to confirm publication. Do not resubmit.',execution:'hosted-worker'}]};
   activeSnapshot={...fixture.snapshot,state:{...fixture.snapshot.state,phase2:{...fixture.snapshot.state.phase2,jobs:[acceptedJob]}}};
   await page.goto(base+'/app/queue?job='+acceptedJob.id,{waitUntil:'domcontentloaded'});
   const receiptDialog=page.getByRole('dialog');
   await receiptDialog.getByText('Accepted — confirm on LinkedIn',{exact:true}).first().waitFor();
   const ownerLink=receiptDialog.getByRole('link',{name:'Open post to confirm',exact:true});
   assert.equal(await ownerLink.getAttribute('href'),acceptedJob.url);
   await receiptDialog.getByText('Accepted by LinkedIn. Publication is not API verified; confirm it on LinkedIn. Do not resubmit.',{exact:true}).waitFor();
   assert.equal(await receiptDialog.getByRole('link',{name:'Open verified post',exact:true}).count(),0);
   assert.equal(await receiptDialog.getByRole('button',{name:'Prepare again',exact:true}).count(),0);
   assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1),false);
   console.log('RAFII_BROWSER_IMAGE linkedin-receipt-'+width+' '+(await page.screenshot({path:join(out,'linkedin-receipt-'+width+'.png'),fullPage:true})).toString('base64'));
   activeSnapshot=fixture.snapshot;
   activeChannel=channel;activeProvider=provider;
   await page.evaluate(id=>localStorage.setItem('postriff-workspace',id),otherWid);
   await page.goto(base+'/channels/connect?provider=instagram&state=synthetic-state-0123456789012345&code=synthetic-code');
   await page.waitForURL('**/app/channels?connected=fixture-ig');
   assert.equal(completionWorkspace,wid);
   checks.push({callbackThroughNormalUI:true,restoresOriginatingWorkspaceFromOtherSelection:true,width,granularCapabilities:true,savedIdentitySeparatedFromRelease:true,sharePermissionSeparatedFromLiveQualification:true,restrictedOrganizationRemainsBlocked:true,acceptedLinkedInReceiptVisibleWithoutPrivateRead:true,ownerCheckNeverApiVerified:true,noAcceptedPostResubmission:true,minimumIdentitySelected:true,latestIdentityVerificationShown:true,noReadyFromIdentity:true,readHierarchy:true,immutableApproval:true,noDuplicateAfterUnknown:true,horizontalOverflow:false});await context.close();
  }
  const receipt={execution:'cloud Next/Playwright; synthetic provider responses; no live qualification',checks};writeFileSync(join(out,'receipt.json'),JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));
 }finally{if(browser)await browser.close();app.kill('SIGTERM');}
})().catch(error=>{console.error(error);process.exitCode=1;});
