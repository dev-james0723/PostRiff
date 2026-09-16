import {createClient, type Session, type SupabaseClient} from '@supabase/supabase-js';

export type HostedAuthConfig={projectUrl:string;publishableKey:string;provider:'supabase';flow:'pkce'};
const PLAN_KEY='postriff-hosted-plan';
let clientPromise:Promise<SupabaseClient>|null=null;

async function config():Promise<HostedAuthConfig>{
 const response=await fetch('/api/auth/config',{cache:'no-store'});
 if(!response.ok)throw new Error('Hosted sign-in is not configured.');
 return response.json();
}

export function hostedClient(){
 if(!clientPromise)clientPromise=config().then(value=>createClient(value.projectUrl,value.publishableKey,{auth:{flowType:'pkce',detectSessionInUrl:true,persistSession:true,autoRefreshToken:true}}));
 return clientPromise;
}

export function selectedHostedPlan(){return localStorage.getItem(PLAN_KEY)==='assist'?'assist':'studio';}

export async function hostedSession():Promise<Session|null>{
 const client=await hostedClient();
 const {data,error}=await client.auth.getSession();
 if(error)throw error;
 return data.session;
}

export async function startGoogleSignIn(plan:string){
 localStorage.setItem(PLAN_KEY,plan==='assist'?'assist':'studio');
 const client=await hostedClient();
 const {error}=await client.auth.signInWithOAuth({provider:'google',options:{redirectTo:window.location.origin}});
 if(error)throw error;
}

export async function sendEmailCode(email:string,plan:string){
 localStorage.setItem(PLAN_KEY,plan==='assist'?'assist':'studio');
 const client=await hostedClient();
 const {error}=await client.auth.signInWithOtp({email,options:{shouldCreateUser:true}});
 if(error)throw error;
}

export async function verifyEmailCode(email:string,token:string){
 const client=await hostedClient();
 const {data,error}=await client.auth.verifyOtp({email,token,type:'email'});
 if(error)throw error;
 if(!data.session)throw new Error('The email code did not create a verified session.');
 return data.session;
}

export async function signOutHosted(){
 const client=await hostedClient();
 const {error}=await client.auth.signOut({scope:'local'});
 if(error)throw error;
}

