import {controlError} from '../../errors.mjs';
export async function controlApi<T>(path:string,options:RequestInit={}):Promise<T>{
  const response=await fetch('/api/control/v2'+path,{...options,cache:'no-store',credentials:'same-origin'});
  if(!response.ok){
    if(response.status===401){window.location.assign('/sign-in');throw new Error('Founder session expired. Sign in again.');}
    const safe=await response.json().catch(()=>({code:''})) as {code?:string};
    throw new Error(controlError(response.status,safe.code));
  }
  return response.json() as Promise<T>;
}
