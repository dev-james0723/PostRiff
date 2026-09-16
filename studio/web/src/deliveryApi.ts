import {api} from './api.ts';
import type {Asset,Template} from './types.ts';

export type HandoffState='queued_local'|'human_action_needed'|'needs_review'|'cancelled'|'user_reported';
export type DeliveryWorker={paused:boolean;heartbeatAt:string|null;owner:string|null;generation:number};
export type HandoffManifest={
  version:1;scope:'local_handoff_only';publicationAuthority:false;remoteScheduling:false;identityState:'unverified';
  draftId:string;draftRevision:number;title:string;source:string;angle:string;channel:string;nativeFormat:string;language:string;copy:string;
  assets:Asset[];template:Template|null;visualRef:{theme:string;layouts:string[]};
  accountLabel:string;destinationLabel:string;audience:string;scheduledLocal:string;scheduledUtc:string;deadlineUtc:string;
  timezone:string;fold:null|0|1;windowMinutes:number;deliveryMethod:'assisted_handoff';derivatives:'none';
};
export type HandoffReview={id:string;draftId:string;draftRevision:number;manifestHash:string;manifest:HandoffManifest;createdAt:string};
export type HandoffJob={
  id:string;reviewId:string;draftId:string;channel:string;title:string;state:HandoffState;
  scheduledUtc:string;scheduledLocal:string;timezone:string;deadlineUtc:string;createdAt:string;updatedAt:string;
  reason:string|null;permalink:string|null;verificationState:'unverified';
};
export type DeliveryState={reviews:HandoffReview[];jobs:HandoffJob[];worker:DeliveryWorker;capabilities:{manualHandoff:true;automaticPublishing:false;nativeScheduling:false}};
export type PrepareHandoff={
  draftId:string;expectedRevision:number;channel:string;accountLabel:string;destinationLabel:string;audience:string;
  scheduledLocal:string;timezone:string;fold:null|0|1;windowMinutes:number;deliveryMethod:'assisted_handoff';derivatives:'none';
};
const segment=(value:string)=>encodeURIComponent(value);
export const deliveryApi={
  state:()=>api<DeliveryState>('/api/delivery'),
  prepare:(input:PrepareHandoff)=>api<{review:HandoffReview}>('/api/delivery/reviews',{method:'POST',body:JSON.stringify(input)}),
  approve:(review:HandoffReview)=>api<{job:HandoffJob}>(`/api/delivery/reviews/${segment(review.id)}/approve`,{method:'POST',body:JSON.stringify({manifestHash:review.manifestHash,expectedRevision:review.draftRevision})}),
  cancel:(id:string)=>api<{job:HandoffJob}>(`/api/delivery/jobs/${segment(id)}/cancel`,{method:'POST',body:'{}'}),
  report:(id:string,permalink:string)=>api<{job:HandoffJob}>(`/api/delivery/jobs/${segment(id)}/report`,{method:'POST',body:JSON.stringify({permalink})}),
  control:(paused:boolean)=>api<{worker:DeliveryWorker}>('/api/delivery/control',{method:'POST',body:JSON.stringify({paused})}),
  packagePath:(id:string)=>`/api/delivery/jobs/${segment(id)}/package`,
};
export const handoffLabel=(state:HandoffState)=>({queued_local:'Queued locally',human_action_needed:'Human action needed',needs_review:'Needs review',cancelled:'Cancelled',user_reported:'User reported · unverified'})[state];
export const packageEligible=(job:HandoffJob)=>job.state==='human_action_needed'||job.state==='user_reported';
export const localAssetPath=(id:string)=>`/api/assets/${segment(id)}/content`;
export const isHttpsPermalink=(value:string)=>{try{const url=new URL(value);return url.protocol==='https:'&&!!url.hostname&&!url.username&&!url.password;}catch{return false;}};
export function heartbeatLabel(heartbeatAt:string|null,now=Date.now()){
  if(!heartbeatAt)return 'No worker heartbeat observed';
  const instant=Date.parse(heartbeatAt);
  if(!Number.isFinite(instant))return 'Heartbeat timestamp unavailable';
  const age=Math.floor((now-instant)/1000);
  if(age<0)return 'Heartbeat clock is ahead of this browser';
  return age<60?`Heartbeat observed ${age}s ago`:`Heartbeat observed ${Math.floor(age/60)}m ago`;
}
export function isManualManifest(manifest:HandoffManifest){
  return manifest.scope==='local_handoff_only'&&manifest.deliveryMethod==='assisted_handoff'&&manifest.publicationAuthority===false&&manifest.remoteScheduling===false&&manifest.identityState==='unverified'&&manifest.derivatives==='none'&&typeof manifest.copy==='string'&&!!manifest.nativeFormat&&!!manifest.scheduledUtc&&!!manifest.deadlineUtc;
}
