import {test,afterEach} from 'node:test';
import assert from 'node:assert/strict';
import {connectionsApi} from '../src/connectionsApi.ts';
const previous=globalThis.fetch;afterEach(()=>{globalThis.fetch=previous;});
test('connection preparation submits exact identity-only consent',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/bluesky/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{handle:'test.bsky.social',scope:'atproto',identityConsent:true});return Response.json({authorizationPath:'/api/connections/bluesky/authorize'});};
 assert.equal(await connectionsApi.prepare('test.bsky.social'),'/api/connections/bluesky/authorize');
});
test('unexpected credential-bearing or external redirect is rejected',async()=>{
 for(const authorizationPath of ['https://evil.invalid','/api/connections/bluesky/authorize?token=synthetic']){
  globalThis.fetch=async()=>Response.json({authorizationPath});await assert.rejects(connectionsApi.prepare('test.bsky.social'),/Unexpected sign-in destination/);
 }
});
test('connection status is read only',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections');assert.equal(options?.method,undefined);return Response.json({bluesky:{state:'not_connected'}});};
 assert.equal((await connectionsApi.status()).bluesky.state,'not_connected');
});

test('records only the exact public Xiaohongshu identity metadata',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/xiaohongshu/observe-profile');assert.deepEqual(JSON.parse(String(options?.body)),{profileUrl:'https://www.rednote.com/user/profile/6aa748a9000000000301c840',nickname:'小红薯6AA7E810',rednoteId:'94556602041',identityConsent:true});return Response.json({state:'browser_profile_observed',publishReady:false,publishing:false});};
 assert.equal((await connectionsApi.observeXiaohongshu('https://www.rednote.com/user/profile/6aa748a9000000000301c840','小红薯6AA7E810','94556602041')).state,'browser_profile_observed');
});

test('requires a separate Creator Center confirmation before connecting Xiaohongshu',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/xiaohongshu/confirm-creator-centre');assert.deepEqual(JSON.parse(String(options?.body)),{rednoteId:'94556602041',creatorCentreConfirmed:true,identityConsent:true});return Response.json({state:'identity_connected',publishReady:false,publishing:false});};
 assert.equal((await connectionsApi.confirmXiaohongshu('94556602041')).state,'identity_connected');
});
test('Xiaohongshu private handoff sends consent but no cookie or token',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/xiaohongshu/begin-private-login');assert.deepEqual(JSON.parse(String(options?.body)),{privateHandoff:true,accountLocked:true});return Response.json({state:'private_handoff',resumePhrase:'Xiaohongshu private login complete',publishing:false});};
 assert.equal((await connectionsApi.beginXiaohongshuPrivateLogin()).state,'private_handoff');
});
test('Xiaohongshu verification sends only the closed-surface checkpoint',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/xiaohongshu/verify-private-login');assert.deepEqual(JSON.parse(String(options?.body)),{sensitiveSurfaceClosed:true});return Response.json({state:'identity_connected',routeState:'authenticated_route_test_required'});};
 assert.equal((await connectionsApi.verifyXiaohongshuPrivateLogin()).routeState,'authenticated_route_test_required');
});
test('prepares exact YouTube upload connection',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/youtube/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{email:'jamesaucreates@gmail.com',channelId:'UCzwNcXaG4EdjR27Tm9JH_zA',scope:'openid email https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload',identityConsent:true});return Response.json({authorizationPath:'/api/connections/youtube/authorize'});};
 assert.equal(await connectionsApi.prepareYouTube('jamesaucreates@gmail.com','UCzwNcXaG4EdjR27Tm9JH_zA'),'/api/connections/youtube/authorize');
});

test('YouTube verification sends no identity override or credential',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/youtube/verify');assert.equal(options?.method,'POST');assert.equal(options?.body,'{}');return Response.json({state:'verification_required'});};
 assert.equal((await connectionsApi.verifyYouTube()).state,'verification_required');
});


test('TikTok locks identity and both read-only scopes',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/tiktok/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{username:'fixture.james',scope:'user.info.basic,user.info.profile',identityConsent:true});return Response.json({authorizationPath:'/api/connections/tiktok/authorize'});};
 assert.equal(await connectionsApi.prepareTikTok('fixture.james'),'/api/connections/tiktok/authorize');
});
test('TikTok refuses foreign or secret-bearing OAuth navigation',async()=>{
 for(const authorizationPath of ['https://foreign.invalid/','/api/connections/tiktok/authorize?code=SYNTHETIC']){
  globalThis.fetch=async()=>Response.json({authorizationPath});await assert.rejects(connectionsApi.prepareTikTok('fixture.james'),/Unexpected sign-in destination/);
 }
});

test('Threads locks the approved account and future publishing scope',async()=>{
 const authorizationUrl='https://threads-jamesau.meta:4316/begin/'+'a'.repeat(64);
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/threads/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{username:'jamesaucreates',scope:'threads_basic,threads_content_publish',identityConsent:true});return Response.json({authorizationUrl});};
 assert.equal(await connectionsApi.prepareThreads('jamesaucreates'),authorizationUrl);
});
test('Threads rejects malformed or foreign handoff URLs',async()=>{
 for(const authorizationUrl of ['https://foreign.invalid/begin/'+ 'a'.repeat(64),'https://threads-jamesau.meta:4316/begin/not-a-ticket','https://threads-jamesau.meta:4316/begin/'+ 'a'.repeat(64)+'?code=synthetic']){
  globalThis.fetch=async()=>Response.json({authorizationUrl});await assert.rejects(connectionsApi.prepareThreads('jamesaucreates'),/Unexpected sign-in destination/);
 }
});
test('Threads route test is read only and locks the official text route',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/threads/route-test');assert.equal(options?.method,'POST');assert.deepEqual(JSON.parse(String(options?.body)),{account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',route:'official_api',routeDriver:'threads_graph_api'});return Response.json({state:'connected_identity',publishReady:true,routeState:'publish_ready'});};
 assert.equal((await connectionsApi.testThreadsRoute()).publishReady,true);
});
test('Threads publication sends the exact approval-bound manifest',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/threads/publish-text');assert.equal(options?.method,'POST');assert.deepEqual(JSON.parse(String(options?.body)),{account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',text:'Exact approved text',visibility:'public',replyControl:'provider_default',scheduledAt:null,media:[],derivatives:[],approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true});return Response.json({threadId:'1',url:'https://www.threads.com/@jamesaucreates/post/1',username:'jamesaucreates',text:'Exact approved text',mediaType:'TEXT_POST',timestamp:'2026-09-14T04:00:00Z',verifiedAt:'2026-09-14T04:00:01Z',replayed:false});};
 const result=await connectionsApi.publishThreadsText({text:'Exact approved text',approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true});
 assert.equal(result.threadId,'1');
});
test('Pinterest locks the approved account and explicit per-Pin scope',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/pinterest/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{username:'jamesaucreates',scope:'user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write',identityConsent:true});return Response.json({authorizationPath:'/api/connections/pinterest/authorize'});};
 assert.equal(await connectionsApi.preparePinterest('jamesaucreates'),'/api/connections/pinterest/authorize');
});
test('Pinterest verification sends no account override or credential',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/pinterest/verify');assert.equal(options?.method,'POST');assert.equal(options?.body,'{}');return Response.json({state:'verification_required'});};
 assert.equal((await connectionsApi.verifyPinterest()).state,'verification_required');
});
test('Pinterest browser connection sends only independently observed public identity evidence',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/pinterest/browser-connect');assert.deepEqual(JSON.parse(String(options?.body)),{username:'jamesaucreates',identitySignals:['business_hub_name_and_handle','public_profile_name_and_handle'],identityConsent:true});return Response.json({state:'connected_browser_identity',routeDriver:'controlled_browser'});};
 assert.equal((await connectionsApi.connectPinterestBrowser()).routeDriver,'controlled_browser');
});
test('Reddit locks the approved account to identity-only scope',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/reddit/prepare');assert.deepEqual(JSON.parse(String(options?.body)),{username:'Ok-External401',scope:'identity',identityConsent:true});return Response.json({authorizationPath:'/api/connections/reddit/authorize'});};
 assert.equal(await connectionsApi.prepareReddit('Ok-External401'),'/api/connections/reddit/authorize');
});
test('Reddit verification sends no account override or credential',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/reddit/verify');assert.equal(options?.method,'POST');assert.equal(options?.body,'{}');return Response.json({state:'needs_reauthorization'});};
 assert.equal((await connectionsApi.verifyReddit()).state,'needs_reauthorization');
});
test('Reddit browser connection sends only exact public identity evidence and route preference',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/reddit/browser-connect');assert.deepEqual(JSON.parse(String(options?.body)),{username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals:['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'],route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome'],identityConsent:true});return Response.json({state:'connected_browser_identity',route:'controlled_browser',routeDriver:'in_app_browser',publishReady:false,publishing:false});};
 assert.equal((await connectionsApi.connectRedditBrowser()).routeDriver,'in_app_browser');
});
test('Reddit publish enablement binds the verified account and non-mutating composer evidence',async()=>{
 globalThis.fetch=async(path,options)=>{assert.equal(path,'/api/connections/reddit/enable-browser-publishing');assert.deepEqual(JSON.parse(String(options?.body)),{username:'Ok-External401',identitySignals:['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'],route:'controlled_browser',routeDriver:'in_app_browser',routeTestSignals:['identity_reverified','composer_loaded','community_selector_present','title_and_body_fields_present','semantic_post_control_present'],publicationPolicy:'exact_post_approval_required',userAuthorization:true});return Response.json({state:'connected_browser_identity',routeState:'browser_publish_ready',publishReady:true,publishing:false});};
 assert.equal((await connectionsApi.enableRedditBrowserPublishing()).publishReady,true);
});
test('Instagram locks approved publishing scopes and exact image manifest',async()=>{
 globalThis.fetch=async(path,options)=>{if(path==='/api/connections/instagram/prepare'){assert.deepEqual(JSON.parse(String(options?.body)),{username:'jamesaucreates',scope:'instagram_business_basic,instagram_business_content_publish',identityConsent:true});return Response.json({authorizationPath:'/api/connections/instagram/authorize'});}assert.equal(path,'/api/connections/instagram/publish-image');assert.deepEqual(JSON.parse(String(options?.body)),{account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'instagram.feed_image',mediaType:'IMAGE',imageUrl:'https://cdn.example.test/a.jpg',caption:'Exact caption',altText:'Exact alt',visibility:'public',scheduledAt:null,derivatives:[],approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true});return Response.json({mediaId:'1',url:'https://www.instagram.com/p/1/',username:'jamesaucreates',caption:'Exact caption',mediaType:'IMAGE',timestamp:'2026-09-14T04:00:00Z',verifiedAt:'2026-09-14T04:00:01Z',replayed:false});};
 assert.equal(await connectionsApi.prepareInstagram('jamesaucreates'),'/api/connections/instagram/authorize');assert.equal((await connectionsApi.publishInstagramImage({imageUrl:'https://cdn.example.test/a.jpg',caption:'Exact caption',altText:'Exact alt',approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true})).mediaId,'1');
});
test('Facebook locks approved Page scopes and exact Page manifest',async()=>{
 const state={pageName:'James Au Studio',pageId:'2000002'} as any;globalThis.fetch=async(path,options)=>{if(path==='/api/connections/facebook/prepare'){assert.deepEqual(JSON.parse(String(options?.body)),{pageName:'James Au Studio',pageId:'2000002',scope:'pages_show_list,pages_read_engagement,pages_manage_posts',identityConsent:true});return Response.json({authorizationPath:'/api/connections/facebook/authorize'});}assert.equal(path,'/api/connections/facebook/publish-post');assert.deepEqual(JSON.parse(String(options?.body)),{account:'James Au Studio',pageId:'2000002',destination:'page_feed',nativeFormat:'facebook.page_post',message:'Exact post',link:null,visibility:'public',scheduledAt:null,derivatives:[],approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true});return Response.json({postId:'2000002_3',url:'https://www.facebook.com/2000002/posts/3',pageId:'2000002',pageName:'James Au Studio',message:'Exact post',scheduledAt:null,state:'published',verifiedAt:'2026-09-14T04:00:01Z',replayed:false});};assert.equal(await connectionsApi.prepareFacebook('James Au Studio','2000002'),'/api/connections/facebook/authorize');assert.equal((await connectionsApi.publishFacebookPost(state,{message:'Exact post',link:null,scheduledAt:null,approvalReceiptHash:'a'.repeat(64),idempotencyKey:'b'.repeat(64),publicationConsent:true})).postId,'2000002_3');
});
