import type {Access, Created, Snapshot, Template, Route, ProfileMetadata} from './types';

export class ApiError extends Error { status:number; constructor(message:string,status:number) {super(message);this.status=status;} }
async function response(res:Response) {
  if (!res.ok) {let message='The local alpha could not complete that request.';try {message=(await res.json()).error || message;} catch { /* keep safe error */ } throw new ApiError(message,res.status);}
  return res;
}
const headers = (access?:Access) => ({'Content-Type':'application/json','X-PostRiff-Request':'founder-alpha',...(access ? {'Authorization':`Bearer ${access.token}`} : {})});
export const api = {
  async catalog():Promise<{templates:Template[];routes:Route[];profileMetadata:ProfileMetadata}> {return (await response(await fetch('/api/catalog'))).json();},
  async create(sample:boolean):Promise<Created> {return (await response(await fetch('/api/workspaces',{method:'POST',headers:headers(),body:JSON.stringify({sample})}))).json();},
  async verify(input:Record<string,unknown>):Promise<Created> {return (await response(await fetch('/api/auth/verify',{method:'POST',headers:headers(),body:JSON.stringify(input)}))).json();},
  async get(access:Access):Promise<Snapshot> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}`,{headers:headers(access)}))).json();},
  async act(access:Access,revision:number,action:string,payload:Record<string,unknown>):Promise<Snapshot> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/actions`,{method:'POST',headers:headers(access),body:JSON.stringify({expectedRevision:revision,action,payload})}))).json();},
  async export(access:Access):Promise<Blob> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/export`,{headers:headers(access)}))).blob();},
  async exportProfile(access:Access):Promise<Blob> {return (await response(await fetch(`/api/workspaces/${access.workspaceId}/profile-export`,{headers:headers(access)}))).blob();},
};

export function readLocal<T>(key:string,fallback:T):T {try {return JSON.parse(localStorage.getItem(key) || 'null') ?? fallback;} catch {return fallback;}}
export function writeLocal(key:string,value:unknown) {localStorage.setItem(key,JSON.stringify(value));}
export const ACCESS_KEY='postriff-alpha-access-v1';
