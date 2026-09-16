import type {Access, Created, Snapshot, Template, Route, ProfileMetadata} from './types';
import {hostedSession} from './hosted-auth';

export class ApiError extends Error { status:number; constructor(message:string,status:number) {super(message);this.status=status;} }
async function response(res:Response) {
  if (!res.ok) {let message='The local alpha could not complete that request.';try {message=(await res.json()).error || message;} catch { /* keep safe error */ } throw new ApiError(message,res.status);}
  return res;
}
async function headers(access?:Access) {
 let token=access?.token;
 if(access?.authMode==='supabase'){
  const session=await hostedSession();
  if(!session)throw new ApiError('Your hosted session ended. Sign in again.',401);
  token=session.access_token;
 }
 return {'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',...(token ? {'Authorization':`Bearer ${token}`} : {})};
}
export const api = {
  async catalog():Promise<{templates:Template[];routes:Route[];profileMetadata:ProfileMetadata;phase2?:boolean;authMode?:'supabase'}> {return (await response(await fetch('/api/catalog'))).json();},
  async challenge(input:Record<string,unknown>):Promise<{state:string}> {return (await response(await fetch('/api/auth/challenge',{method:'POST',headers:await headers(),body:JSON.stringify(input)}))).json();},
  async create(sample:boolean):Promise<Created> {return (await response(await fetch('/api/workspaces',{method:'POST',headers:await headers(),body:JSON.stringify({sample})}))).json();},
  async verify(input:Record<string,unknown>):Promise<Created> {return (await response(await fetch('/api/auth/verify',{method:'POST',headers:await headers(),body:JSON.stringify(input)}))).json();},
  async verifyHosted(plan:string,token:string):Promise<Snapshot&{workspaceId:string}> {return (await response(await fetch('/api/auth/verify',{method:'POST',headers:{...await headers(),'Authorization':`Bearer ${token}`},body:JSON.stringify({plan})}))).json();},
  async get(access:Access):Promise<Snapshot> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}`,{headers:await headers(access)}))).json();},
  async act(access:Access,revision:number,action:string,payload:Record<string,unknown>):Promise<Snapshot> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/actions`,{method:'POST',headers:await headers(access),body:JSON.stringify({expectedRevision:revision,action,payload})}))).json();},
  async export(access:Access):Promise<Blob> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/export`,{headers:await headers(access)}))).blob();},
  async exportProfile(access:Access):Promise<Blob> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/profile-export`,{headers:await headers(access)}))).blob();},
  async media(access:Access,assetId:string):Promise<Blob> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/media/${assetId}`,{headers:await headers(access)}))).blob();},
};

export function readLocal<T>(key:string,fallback:T):T {try {return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback;} catch {return fallback;}}
export function writeLocal(key:string,value:unknown) {localStorage.setItem(key,JSON.stringify(value));}
export const ACCESS_KEY='postriff-alpha-access-v1';
