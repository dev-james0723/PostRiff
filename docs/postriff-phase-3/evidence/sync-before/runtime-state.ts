export interface RuntimeRoute {id:string;label:string;status:string;detail:string;usage:string}
export interface RuntimeJob {id:string;route:string;status:string;inputHash:string;artifactHash?:string;manifest:Record<string,unknown>;events:{id:string;seq:number;type:string;text?:string}[];artifact?:{variants?:{platform:string;language:string;text:string}[];fields?:unknown[]};usage:{provenance:string;modelRequests?:number}}
export interface RuntimeState {selected:string;templateId?:string|null;cloudVoiceRevision?:number|null;routes:RuntimeRoute[];devices:{id:string;name:string;connection:string;lastSeen:number;status:string}[];jobs:RuntimeJob[];sourceVisibility:Record<string,string>}
export interface PendingEdit {idempotencyKey:string;variantId:string;variantRevision:number;text:string}
export function pendingKey(workspaceId:string){return `postriff-p3-pending:${workspaceId}`;}
export function retainedEdit(previous:PendingEdit|undefined,variant:{id:string;revision:number;text:string},text:string):PendingEdit {
 return {idempotencyKey:previous?.idempotencyKey||crypto.randomUUID(),variantId:variant.id,variantRevision:previous?.variantRevision??variant.revision,text};
}
export function recoveryLabel(status:string){return ({interrupted:'Interrupted · partial text retained',revoked:'Device revoked · writes stopped',expired:'Expired · prepare a new request',completed:'Candidate ready for review',applied:'Candidate saved for editorial review',waiting:'Waiting for runtime',running:'Running',prepared:'Review source scope before starting'} as Record<string,string>)[status]||status;}
