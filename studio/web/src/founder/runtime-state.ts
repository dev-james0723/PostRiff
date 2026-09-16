export interface RuntimeRoute {id:string;label:string;status:string;detail:string;usage:string}
export interface RuntimeJob {id:string;route:string;status:string;inputHash:string;artifactHash?:string;manifest:Record<string,unknown>;events:{id:string;seq:number;type:string;text?:string}[];artifact?:{variants?:{platform:string;language:string;text:string}[];fields?:unknown[]};usage:{provenance:string;modelRequests?:number}}
export interface SyncReceipt {id:string;variantId:string;variantRevision:number}
export interface RuntimeState {operations?:SyncReceipt[];selected:string;templateId?:string|null;cloudVoiceRevision?:number|null;routes:RuntimeRoute[];devices:{id:string;name:string;connection:string;lastSeen:number;status:string}[];jobs:RuntimeJob[];sourceVisibility:Record<string,string>}
export interface EditPayload {idempotencyKey:string;variantId:string;variantRevision:number;text:string}
export interface PendingEdit extends EditPayload {submitted?:EditPayload}
export function pendingKey(workspaceId:string){return `postriff-p3-pending:${workspaceId}`;}
export function retainedEdit(previous:PendingEdit|undefined,variant:{id:string;revision:number;text:string},text:string):PendingEdit {
 return {idempotencyKey:previous?.text===text?previous.idempotencyKey:crypto.randomUUID(),variantId:variant.id,variantRevision:previous?.variantRevision??variant.revision,text,...(previous?.submitted?{submitted:previous.submitted}:{})};
}
export function recoveryLabel(status:string){return ({interrupted:'Interrupted · partial text retained',revoked:'Device revoked · writes stopped',expired:'Expired · prepare a new request',completed:'Candidate ready for review',applied:'Candidate saved for editorial review',waiting:'Waiting for runtime',running:'Running',prepared:'Review source scope before starting'} as Record<string,string>)[status]||status;}

export function submission(edit:PendingEdit):EditPayload {
 return edit.submitted??{idempotencyKey:edit.idempotencyKey,variantId:edit.variantId,variantRevision:edit.variantRevision,text:edit.text};
}
export function reconcileEdits(pending:Record<string,PendingEdit>,receipts:SyncReceipt[]):Record<string,PendingEdit> {
 let next=pending;
 for(const [id,edit] of Object.entries(pending)) {
  const sent=edit.submitted;
  if(!sent)continue;
  const receipt=receipts.find(r=>r.id===sent.idempotencyKey&&r.variantId===id);
  if(!receipt)continue;
  if(next===pending)next={...pending};
  if(edit.idempotencyKey===sent.idempotencyKey&&edit.text===sent.text)delete next[id];
  else {
   const {submitted:_,...local}=edit;
   next[id]={...local,variantRevision:receipt.variantRevision};
  }
 }
 return next;
}
