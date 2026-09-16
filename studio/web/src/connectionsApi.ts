import {api} from './api.ts';
export type Connection = {provider:string;available:boolean;state:string;handle:string|null;did:string|null;scope:string;verifiedAt:string|null;expiresAt:string|null;identitySignals:string[];publishReady:boolean;publishing:false};
export type YouTubeConnection = Omit<Connection,'did'> & {email:string|null;channelId:string|null;channelTitle:string|null};
export type InstagramConnection = Omit<Connection,'did'|'handle'> & {username:string|null;userId:string|null;accountType:string|null;route:'official_api';routeDriver:'instagram_api_with_instagram_login';routeState:'not_tested'|'publish_ready';routeTestId:string|null;routeTestedAt:string|null;routeTestSignals:string[];publicationPolicy:'exact_post_approval_required'};
export type InstagramPostResult={mediaId:string;url:string;username:string;caption:string;mediaType:'IMAGE';timestamp:string;verifiedAt:string;replayed:boolean};
export type FacebookConnection = Omit<Connection,'did'|'handle'> & {userName:string|null;userId:string|null;pageName:string|null;pageId:string|null;tasks:string[];configurationId:string|null;route:'official_api';routeDriver:'facebook_pages_api';routeState:'not_tested'|'publish_ready';routeTestId:string|null;routeTestedAt:string|null;routeTestSignals:string[];publicationPolicy:'exact_post_approval_required'};
export type FacebookPostResult={postId:string;url:string|null;pageId:string;pageName:string;message:string;scheduledAt:string|null;state:'published'|'scheduled';verifiedAt:string;replayed:boolean};
export type TikTokConnection = Omit<Connection,'did'|'handle'> & {username:string|null;openId:string|null;displayName:string|null};
export type ThreadsConnection = Omit<Connection,'did'|'handle'> & {username:string|null;userId:string|null;route:'official_api';routeDriver:'threads_graph_api';routeState:'not_tested'|'publish_ready';routeTestId:string|null;routeTestedAt:string|null;routeTestSignals:string[];publicationPolicy:'exact_post_approval_required'};
export type ThreadsPostResult = {threadId:string;url:string;username:string;text:string;mediaType:'TEXT_POST';timestamp:string;verifiedAt:string;replayed:boolean};
export type PinterestConnection = Omit<Connection,'did'|'handle'> & {username:string|null;accountId:string|null;accountType:string|null;routeDriver:'official_api_oauth'|'controlled_browser'};
export type RedditConnection = Omit<Connection,'did'|'handle'> & {username:string|null;accountId:string|null;profileUrl:string|null;route:'official_api'|'controlled_browser';routeDriver:'reddit_oauth'|'in_app_browser';preferredPublishDrivers:['computer_use','chrome'];sessionState:'not_established'|'oauth_token_active'|'verify_before_each_action';routeState:'not_tested'|'browser_publish_ready';routeTestId:string|null;routeTestedAt:string|null;routeTestSignals:string[];publicationPolicy:'exact_post_approval_required'};
export type XConnection = Omit<Connection,'did'|'handle'> & {username:string|null;accountId:string|null;profileUrl:string|null;route:'official_api';routeDriver:'x_oauth2_pkce';sessionState:'not_established'|'oauth_token_active';routeState:'not_tested';routeTestId:null;routeTestedAt:null;routeTestSignals:string[];publicationPolicy:'exact_post_approval_required'};
export type LinkedInConnection = Omit<Connection,'did'|'handle'> & {email:string|null;subject:string|null;name:string|null;profileUrl:string|null;route:'official_api';routeDriver:'linkedin_oauth2_posts_api';sessionState:'not_established'|'oauth_token_active';publicationPolicy:'exact_post_approval_required';schedulingAvailable:boolean};
export type LinkedInScheduledJob={idempotencyKey:string;state:'scheduled'|'submitting'|'delivery_unverified'|'unresolved';text:string;scheduledAt:string;createdAt:string;postId:string|null;url:string|null;verifiedAt:string|null};
export type XBrowserConnection={provider:'x';route:'controlled_browser';routeDriver:'x-in-app-browser/1';state:string;profile:string|null;username:string|null;identitySignals:string[];sessionState:'verify_before_each_action';publishReady:boolean;publishing:false;liveTestVerified:boolean;cost:'free_no_api'};
export type XBrowserPreview={manifest:{version:string;channel:'x';nativeFormat:'x.post';profile:string;text:string;audience:'public';timing:'now'|'scheduled';scheduledAt:string|null;media:[];derivatives:[]};hash:string;state:'local_preview'};
export type XiaohongshuConnection = Omit<Connection,'did'|'handle'> & {nickname:string|null;profileId:string|null;rednoteId:string|null;profileUrl:string|null;driverInstalled:boolean;driverRunning:boolean;driverVersion:string|null;route:string|null;routeDriver:string|null;routeState:string;serviceAuthenticated:boolean;loopbackOnly:boolean|null;noHostPort:boolean|null;executionMode:'isolated_container'|'native_binary';serviceBoundary:'docker_socket_and_bearer'|'loopback_bearer';sessionStored:boolean;sessionOpaque:boolean;allowedOperations:string[];disabledOperations:string[];mutationsLocked:boolean;driverBlocked:boolean;blockerCode:string|null;nativeBlockerCode:string|null};
export const connectionsApi={
  status:()=>api<{bluesky:Connection;youtube:YouTubeConnection;instagram:InstagramConnection;facebook:FacebookConnection;tiktok:TikTokConnection;threads:ThreadsConnection;pinterest:PinterestConnection;reddit:RedditConnection;x:XConnection;linkedin:LinkedInConnection;xiaohongshu:XiaohongshuConnection}>('/api/connections'),
  linkedinStatus:()=>api<LinkedInConnection>('/api/connections/linkedin'),
  prepare:async(handle:string)=>{
    const result=await api<{authorizationPath:string}>('/api/connections/bluesky/prepare',{method:'POST',body:JSON.stringify({handle,scope:'atproto',identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/bluesky/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  verifyYouTube:()=>api<YouTubeConnection>('/api/connections/youtube/verify',{method:'POST',body:'{}'}),
  prepareYouTube:async(email:string,channelId:string)=>{
    const scope='openid email https://www.googleapis.com/auth/youtube.readonly https://www.googleapis.com/auth/youtube.upload';
    const result=await api<{authorizationPath:string}>('/api/connections/youtube/prepare',{method:'POST',body:JSON.stringify({email,channelId,scope,identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/youtube/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  uploadYouTube:async(form:FormData)=>api<{videoId:string;url:string;privacyStatus:string|null;publishAt:string|null;processingStatus:string|null;verifiedAt:string}>('/api/connections/youtube/upload',{method:'POST',body:form}),
  verifyInstagram:()=>api<InstagramConnection>('/api/connections/instagram/verify',{method:'POST',body:'{}'}),
  prepareInstagram:async(username:string)=>{
    const result=await api<{authorizationPath:string}>('/api/connections/instagram/prepare',{method:'POST',body:JSON.stringify({username,scope:'instagram_business_basic,instagram_business_content_publish',identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/instagram/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  testInstagramRoute:()=>api<InstagramConnection>('/api/connections/instagram/route-test',{method:'POST',body:JSON.stringify({account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'instagram.feed_image',mediaType:'IMAGE',route:'official_api',routeDriver:'instagram_api_with_instagram_login'})}),
  publishInstagramImage:(value:{imageUrl:string;caption:string;altText:string;approvalReceiptHash:string;idempotencyKey:string;publicationConsent:true})=>api<InstagramPostResult>('/api/connections/instagram/publish-image',{method:'POST',body:JSON.stringify({account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'instagram.feed_image',mediaType:'IMAGE',imageUrl:value.imageUrl,caption:value.caption,altText:value.altText,visibility:'public',scheduledAt:null,derivatives:[],approvalReceiptHash:value.approvalReceiptHash,idempotencyKey:value.idempotencyKey,publicationConsent:value.publicationConsent})}),
  verifyFacebook:()=>api<FacebookConnection>('/api/connections/facebook/verify',{method:'POST',body:'{}'}),
  prepareFacebook:async(pageName:string,pageId:string)=>{const scope='pages_show_list,pages_read_engagement,pages_manage_posts';const result=await api<{authorizationPath:string}>('/api/connections/facebook/prepare',{method:'POST',body:JSON.stringify({pageName,pageId,scope,identityConsent:true})});if(result.authorizationPath!=='/api/connections/facebook/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');return result.authorizationPath;},
  testFacebookRoute:(state:FacebookConnection)=>api<FacebookConnection>('/api/connections/facebook/route-test',{method:'POST',body:JSON.stringify({account:state.pageName,pageId:state.pageId,destination:'page_feed',nativeFormat:'facebook.page_post',route:'official_api',routeDriver:'facebook_pages_api'})}),
  publishFacebookPost:(state:FacebookConnection,value:{message:string;link:string|null;scheduledAt:string|null;approvalReceiptHash:string;idempotencyKey:string;publicationConsent:true})=>api<FacebookPostResult>('/api/connections/facebook/publish-post',{method:'POST',body:JSON.stringify({account:state.pageName,pageId:state.pageId,destination:'page_feed',nativeFormat:'facebook.page_post',message:value.message,link:value.link,visibility:'public',scheduledAt:value.scheduledAt,derivatives:[],approvalReceiptHash:value.approvalReceiptHash,idempotencyKey:value.idempotencyKey,publicationConsent:value.publicationConsent})}),
  verifyTikTok:()=>api<TikTokConnection>('/api/connections/tiktok/verify',{method:'POST',body:'{}'}),
  prepareTikTok:async(username:string)=>{
    const result=await api<{authorizationPath:string}>('/api/connections/tiktok/prepare',{method:'POST',body:JSON.stringify({username,scope:'user.info.basic,user.info.profile',identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/tiktok/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  verifyThreads:()=>api<ThreadsConnection>('/api/connections/threads/verify',{method:'POST',body:'{}'}),
  testThreadsRoute:()=>api<ThreadsConnection>('/api/connections/threads/route-test',{method:'POST',body:JSON.stringify({account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',route:'official_api',routeDriver:'threads_graph_api'})}),
  publishThreadsText:(value:{text:string;approvalReceiptHash:string;idempotencyKey:string;publicationConsent:true})=>api<ThreadsPostResult>('/api/connections/threads/publish-text',{method:'POST',body:JSON.stringify({
    account:'@jamesaucreates',destination:'main_profile_feed',nativeFormat:'threads.post',mediaType:'TEXT',
    text:value.text,visibility:'public',replyControl:'provider_default',scheduledAt:null,media:[],derivatives:[],
    approvalReceiptHash:value.approvalReceiptHash,idempotencyKey:value.idempotencyKey,publicationConsent:value.publicationConsent,
  })}),
  prepareThreads:async(username:string)=>{
    const scope='threads_basic,threads_content_publish';
    const result=await api<{authorizationUrl:string}>('/api/connections/threads/prepare',{method:'POST',body:JSON.stringify({username,scope,identityConsent:true})});
    let url:URL;
    try{url=new URL(result.authorizationUrl);}catch{throw new Error('Unexpected sign-in destination. No navigation was started.');}
    if(url.protocol!=='https:'||url.hostname!=='threads-jamesau.meta'||url.port!=='4316'||!/^\/begin\/[a-f0-9]{64}$/.test(url.pathname)||url.search||url.hash)throw new Error('Unexpected sign-in destination. No navigation was started.');
    return url.toString();
  },
  verifyPinterest:()=>api<PinterestConnection>('/api/connections/pinterest/verify',{method:'POST',body:'{}'}),
  preparePinterest:async(username:string)=>{
    const scope='user_accounts:read,boards:read,boards:write,boards:read_secret,boards:write_secret,pins:read,pins:write,pins:read_secret,pins:write_secret,ads:read,ads:write,billing:read,billing:write';
    const result=await api<{authorizationPath:string}>('/api/connections/pinterest/prepare',{method:'POST',body:JSON.stringify({username,scope,identityConsent:true})});
    return result.authorizationPath;
  },
  connectPinterestBrowser:()=>api<PinterestConnection>('/api/connections/pinterest/browser-connect',{method:'POST',body:JSON.stringify({username:'jamesaucreates',identitySignals:['business_hub_name_and_handle','public_profile_name_and_handle'],identityConsent:true})}),
  verifyReddit:()=>api<RedditConnection>('/api/connections/reddit/verify',{method:'POST',body:'{}'}),
  prepareReddit:async(username:string)=>{
    const result=await api<{authorizationPath:string}>('/api/connections/reddit/prepare',{method:'POST',body:JSON.stringify({username,scope:'identity',identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/reddit/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  connectRedditBrowser:()=>api<RedditConnection>('/api/connections/reddit/browser-connect',{method:'POST',body:JSON.stringify({username:'Ok-External401',profileUrl:'https://www.reddit.com/user/Ok-External401/',identitySignals:['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'],route:'controlled_browser',routeDriver:'in_app_browser',preferredPublishDrivers:['computer_use','chrome'],identityConsent:true})}),
  enableRedditBrowserPublishing:()=>api<RedditConnection>('/api/connections/reddit/enable-browser-publishing',{method:'POST',body:JSON.stringify({username:'Ok-External401',identitySignals:['signed_in_preferences_account_link','owner_profile_edit_controls_and_canonical_url'],route:'controlled_browser',routeDriver:'in_app_browser',routeTestSignals:['identity_reverified','composer_loaded','community_selector_present','title_and_body_fields_present','semantic_post_control_present'],publicationPolicy:'exact_post_approval_required',userAuthorization:true})}),
  prepareX:async(username:string)=>{
    const scope='tweet.read users.read tweet.write offline.access';
    const result=await api<{authorizationPath:string}>('/api/connections/x/prepare',{method:'POST',body:JSON.stringify({username,scope,identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/x/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  verifyX:()=>api<XConnection>('/api/connections/x/verify',{method:'POST',body:'{}'}),
  prepareLinkedIn:async(email:string)=>{
    const scope='openid profile email w_member_social';
    const result=await api<{authorizationPath:string}>('/api/connections/linkedin/prepare',{method:'POST',body:JSON.stringify({email,scope,identityConsent:true})});
    if(result.authorizationPath!=='/api/connections/linkedin/authorize')throw new Error('Unexpected sign-in destination. No navigation was started.');
    return result.authorizationPath;
  },
  verifyLinkedIn:()=>api<LinkedInConnection>('/api/connections/linkedin/verify',{method:'POST',body:'{}'}),
  publishLinkedInTest:()=>api<{state:'published';postId:string;url:string;text:string;account:string;verifiedAt:string;approvalReceiptHash:string;replayed:boolean}>('/api/connections/linkedin/publish-text',{method:'POST',body:JSON.stringify({text:'Testing the LinkedIn connection for James Au Studio. This post was reviewed and sent through my local approval workflow.',approvalReceiptHash:'sha256:8a311cb35fe270fc880e24b3fa6319c48f338b39711e3a12e5b0c436cbbc67df',idempotencyKey:'linkedin-route-test-2026-09-14-v1',publicationConsent:true})}),
  previewLinkedInSchedule:(text:string,scheduledAt:string)=>api<{manifest:{text:string;scheduledAt:string};approvalReceiptHash:string}>('/api/connections/linkedin/schedule-preview',{method:'POST',body:JSON.stringify({text,scheduledAt})}),
  scheduleLinkedInText:(value:{text:string;scheduledAt:string;approvalReceiptHash:string;idempotencyKey:string;publicationConsent:true})=>api<{state:'scheduled';scheduledAt:string;replayed:boolean}>('/api/connections/linkedin/schedule-text',{method:'POST',body:JSON.stringify(value)}),
  linkedinScheduled:()=>api<{jobs:LinkedInScheduledJob[]}>('/api/connections/linkedin/scheduled'),
  xBrowserStatus:()=>api<XBrowserConnection>('/api/connections/x-browser/status'),
  xBrowserLogin:()=>api<{state:string;instruction:string}>('/api/connections/x-browser/login',{method:'POST',body:'{}'}),
  xBrowserVerify:(profile:string)=>api<XBrowserConnection>('/api/connections/x-browser/verify',{method:'POST',body:JSON.stringify({profile})}),
  xBrowserPreview:(profile:string,text:string,scheduledAt:string|null)=>api<XBrowserPreview>('/api/connections/x-browser/preview',{method:'POST',body:JSON.stringify({profile,text,scheduledAt})}),
  xBrowserPublish:(manifest:XBrowserPreview['manifest'],approvedHash:string)=>api<Record<string,unknown>>('/api/connections/x-browser/publish',{method:'POST',body:JSON.stringify({manifest,approvedHash,publicationConsent:true})}),
  observeXiaohongshu:(profileUrl:string,nickname:string,rednoteId:string)=>api<XiaohongshuConnection>('/api/connections/xiaohongshu/observe-profile',{method:'POST',body:JSON.stringify({profileUrl,nickname,rednoteId,identityConsent:true})}),
  confirmXiaohongshu:(rednoteId:string)=>api<XiaohongshuConnection>('/api/connections/xiaohongshu/confirm-creator-centre',{method:'POST',body:JSON.stringify({rednoteId,creatorCentreConfirmed:true,identityConsent:true})}),
  beginXiaohongshuPrivateLogin:()=>api<{state:'private_handoff';qrImage:string|null;expiresInSeconds:number;resumePhrase:string;publishing:false}>('/api/connections/xiaohongshu/begin-private-login',{method:'POST',body:JSON.stringify({privateHandoff:true,accountLocked:true})}),
  verifyXiaohongshuPrivateLogin:()=>api<XiaohongshuConnection>('/api/connections/xiaohongshu/verify-private-login',{method:'POST',body:JSON.stringify({sensitiveSurfaceClosed:true})}),
};
