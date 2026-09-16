import type {Access} from './types';
import {ApiError} from './api';
import {hostedSession} from './hosted-auth';

async function headers(access:Access){
 let token=access.token;
 if(access.authMode==='supabase'){const session=await hostedSession();if(!session)throw new ApiError('Your hosted session ended. Sign in again.',401);token=session.access_token;}
 return {'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha','Authorization':`Bearer ${token}`};
}
async function ok(res:Response){if(!res.ok){let message='The workspace could not complete that request.';try{message=(await res.json()).error||message;}catch{/* keep */}throw new ApiError(message,res.status);}return res;}
async function get<T>(access:Access,path:string):Promise<T>{return (await ok(await fetch(path,{headers:await headers(access)}))).json();}
async function send<T>(access:Access,method:string,path:string,body:Record<string,unknown>={}):Promise<T>{return (await ok(await fetch(path,{method,headers:await headers(access),body:JSON.stringify(body)}))).json();}

export type SafeEvent={id:string;seq:number;type:string;at:number;text?:string;message?:string;destination?:number;sourceId?:string;policy?:string;stage?:string;percent?:number;variants?:number};
export type Variant={platform:string;language:string;text:string;sourceIds:string[];unknowns:string[];warnings?:string[];candidateOnly?:boolean};
export type Run={runId:string;conversationId:string;status:string;artifactHash:string|null;artifact:{variants:Variant[]}|null;usage:Record<string,unknown>;model:string;reasoning:string;events:SafeEvent[];cursor:number};
export type Conversation={conversationId:string;title:string;createdAt:number;updatedAt:number;archived:boolean};
export type Message={messageId:string;seq:number;role:'user'|'assistant'|'system';body:Record<string,unknown>;runId:string|null;at:number};
export type Capability={level:'Direct'|'Assisted'|'Bridge'|'Unsupported';evidence:string;verifiedAt:number|null;capabilityVersion:number};
export type ChannelView={id:string;platform:string;account:string;accountType?:string;connectionState:string;capabilities:Record<string,Capability>;evidenceSource:string;scopes:string[];expiresAt?:number};
export type ProviderView={id:string;platform:string;productionReviewed:boolean;capabilities:Record<string,boolean>};
export type Usage={entitlement:{planTermsId:string;writingBatchesRemaining:number;mediaCreditsRemaining:number;connectedAccounts:number;members:number;storageMb:number;resetsAt:number|null;source:string;version:number};subscription:null|{status:string;plan:string;label:string;priceCents:number;currency:string;priceStatus:string;live:boolean;currentPeriodEnd:number|null;cancelAtPeriodEnd:boolean;provider:string};budget:{windowKind:string;spentUsdMicro:number;reservedUsdMicro:number;warnUsdMicro:number;stopUsdMicro:number;status:string};overage:string;ledger:{kind:string;dimension:string;costState:string;estimatedUsdMicro:number;actualUsdMicro:number|null;at:number;provider:string;model:string}[];planTerms:{id:string;plan:string;version:number;label:string;priceCents:number;currency:string;status:string;priceLabel:string;entitlements:Record<string,unknown>}[];note:string;lifecycle:{status:string;exportAvailable?:boolean;canPublish?:boolean};membership:Record<string,unknown>};
export type Metric={value:number|null;display:string;availability:string;unit:string;nativeName:string};
export type AnalyticsPost={provider:string;providerPostId:string;jobId:string|null;platform:string|null;language:string|null;publishedState:string;contentOrigin:string;metrics:Record<string,Metric>;freshness:{observedAt:number;ingestedAt:number};definitionVersion:string;rates:Record<string,{display:string;numerator:number|null;denominator:number|null}>};
export type Analytics={state:string;posts:AnalyticsPost[];rules:Record<string,string>;connections:{id:string;platform:string;account:string;analytics:string}[];freshnessNow:number};
export type Thread={threadId:string;connectionId:string;provider:string;providerPostId:string;commentId:string;author:string;text:string;ingestedAt:number;tombstoned:boolean;replyAvailable:boolean;replyLevel:string};
export type Audience={threads:Thread[];capabilities:{connectionId:string;commentsRead:string}[];limits:string};

export const cloud={
 conversations:(a:Access)=>get<{conversations:Conversation[]}>(a,`/api/workspaces/${a.workspaceId}/ideas/conversations`),
 createConversation:(a:Access,title:string)=>send<Conversation>(a,'POST',`/api/workspaces/${a.workspaceId}/ideas/conversations`,{title}),
 messages:(a:Access,id:string)=>get<Conversation&{messages:Message[]}>(a,`/api/workspaces/${a.workspaceId}/ideas/conversations/${id}/messages`),
 turn:(a:Access,id:string,body:Record<string,unknown>)=>send<Run>(a,'POST',`/api/workspaces/${a.workspaceId}/ideas/conversations/${id}/turns`,body),
 events:(a:Access,runId:string,cursor=0)=>get<Run>(a,`/api/workspaces/${a.workspaceId}/ideas/runs/${runId}/events?cursor=${cursor}`),
 apply:(a:Access,runId:string,expectedRevision:number,artifactHash:string)=>send<{runId:string;status:string;revision:number;variants?:number}>(a,'POST',`/api/workspaces/${a.workspaceId}/ideas/runs/${runId}/apply`,{expectedRevision,artifactHash}),
 quickStart:(a:Access,expectedRevision:number,body:Record<string,unknown>)=>send<Run&{sourceId:string;sourcePolicy:string;revision:number}>(a,'POST',`/api/workspaces/${a.workspaceId}/ideas/quick-start`,{expectedRevision,...body}),
 models:()=>fetch('/api/ideas/models').then(r=>r.json() as Promise<{models:{id:string;label:string;qualified:boolean;detail:string}[];reasoning:{id:string;available:boolean;detail:string}[]}>),
 channels:(a:Access)=>get<{channels:ChannelView[];providers:ProviderView[]}>(a,`/api/workspaces/${a.workspaceId}/channels`),
 oauthStart:(a:Access,provider:string,capability:string)=>send<{authorizeUrl:string;permissionExplanation:string;scopes:string[]}>(a,'POST',`/api/workspaces/${a.workspaceId}/channels/${provider}/oauth/start`,{capability}),
 oauthComplete:(a:Access,provider:string,state:string,code?:string,error?:string)=>send<{connected:boolean;reason?:string;account?:string;providerAccountId?:string;missingScopes?:string[];capabilities?:Record<string,Capability>;revision?:number}>(a,'POST',`/api/workspaces/${a.workspaceId}/channels/${provider}/oauth/complete`,{state,code,error}),
 verifyChannel:(a:Access,id:string)=>send<{connectionId:string;state:string;identityVerified:boolean;detail?:string}>(a,'POST',`/api/workspaces/${a.workspaceId}/channels/${id}/verify`),
 disconnect:(a:Access,id:string)=>send<{disconnected:boolean;remoteRevoked:boolean;revision:number}>(a,'DELETE',`/api/workspaces/${a.workspaceId}/channels/${id}`),
 usage:(a:Access)=>get<Usage>(a,`/api/workspaces/${a.workspaceId}/usage`),
 dataRequest:(a:Access,body:Record<string,unknown>)=>send<Record<string,unknown>&{kind:string;status:string}>(a,'POST',`/api/workspaces/${a.workspaceId}/data-requests`,body),
 dataRequests:(a:Access)=>get<{requests:{requestId:string;kind:string;status:string;receipt:Record<string,unknown>;requestedAt:number}[]}>(a,`/api/workspaces/${a.workspaceId}/data-requests`),
 privacy:()=>fetch('/api/privacy/notice').then(r=>r.json() as Promise<Record<string,unknown>>),
 analytics:(a:Access)=>get<Analytics>(a,`/api/workspaces/${a.workspaceId}/analytics/summary`),
 audience:(a:Access)=>get<Audience>(a,`/api/workspaces/${a.workspaceId}/audience/threads`),
 draftReply:(a:Access,threadId:string,body:Record<string,unknown>)=>send<{draftId:string;origin:string;text:string;label:string}>(a,'POST',`/api/workspaces/${a.workspaceId}/audience/threads/${threadId}/reply-drafts`,body),
 replyPreview:(a:Access,draftId:string)=>send<{manifest:Record<string,unknown>;digest:string;action:string;replyLevel:string}>(a,'POST',`/api/workspaces/${a.workspaceId}/audience/reply-drafts/${draftId}/reply-preview`),
 approveReply:(a:Access,draftId:string,digest:string)=>send<{draftId:string;status:string;note?:string}>(a,'POST',`/api/workspaces/${a.workspaceId}/audience/reply-drafts/${draftId}/reply`,{digest,confirmed:true}),
 members:(a:Access)=>get<{members:{userId:string;role:string;status:string;you:boolean}[]}>(a,`/api/workspaces/${a.workspaceId}/members`),
};
export const usd=(micro:number|null|undefined)=>micro==null?'—':`$${(micro/1_000_000).toFixed(2)}`;
