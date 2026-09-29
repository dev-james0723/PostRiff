'use client';
import { useState } from 'react';
import { createClient, SupabaseClient } from '@supabase/supabase-js';
export default function SignIn() {
  const [client,setClient]=useState<SupabaseClient|null>(null);
  const [email,setEmail]=useState(''),[password,setPassword]=useState(''),[code,setCode]=useState('');
  const [factor,setFactor]=useState(''),[error,setError]=useState(''),[busy,setBusy]=useState(false);
  const url=process.env.NEXT_PUBLIC_CONTROL_SUPABASE_URL, key=process.env.NEXT_PUBLIC_CONTROL_SUPABASE_PUBLISHABLE_KEY;
  async function submit(event:React.FormEvent) {
    event.preventDefault(); setBusy(true); setError('');
    try {
      if (!url || !key) throw new Error('Founder identity is not configured for this deployment.');
      if (!factor) {
        const next=createClient(url,key,{auth:{persistSession:false,autoRefreshToken:false,detectSessionInUrl:false}});
        const signed=await next.auth.signInWithPassword({email,password});
        setPassword('');
        if (signed.error) throw new Error('Sign-in could not be verified.');
        const factors=await next.auth.mfa.listFactors();
        const totp=factors.data?.totp.find(item=>item.status==='verified');
        if (!totp) throw new Error('A verified MFA factor is required. Enroll it through the existing account security flow.');
        setClient(next); setFactor(totp.id);
      } else {
        if (!client) throw new Error('Sign in again.');
        const verified=await client.auth.mfa.challengeAndVerify({factorId:factor,code});
        setCode('');
        if (verified.error || !verified.data) throw new Error('Second-factor verification failed.');
        const response=await fetch('/api/control/v2/session/exchange',{method:'POST',headers:{'Content-Type':'application/json','Authorization':'Bearer '+verified.data.access_token,'X-Control-Exchange':'1'},body:'{}',cache:'no-store'});
        setClient(null);
        if (!response.ok) throw new Error('Founder access was denied. Check the operator binding and MFA freshness.');
        window.location.assign('/control/command');
      }
    } catch (failure) { setError(failure instanceof Error ? failure.message : 'Sign-in failed.'); }
    finally { setBusy(false); }
  }
  return <form onSubmit={submit} aria-busy={busy}>
    {!factor ? <><label htmlFor="email">Founder email</label><input id="email" type="email" autoComplete="username" value={email} onChange={event=>setEmail(event.target.value)} required/><label htmlFor="password">Password</label><input id="password" type="password" autoComplete="current-password" value={password} onChange={event=>setPassword(event.target.value)} required/></> : <><label htmlFor="mfa">Authenticator code</label><input id="mfa" inputMode="numeric" autoComplete="one-time-code" pattern="[0-9]{6}" value={code} onChange={event=>setCode(event.target.value)} required autoFocus/></>}
    {error && <p role="alert">{error}</p>}<button type="submit" disabled={busy||!url||!key}>{busy?'Verifying…':factor?'Verify founder session':'Continue'}</button>
    {!url && <p role="status">Identity source unavailable. This deployment is not connected.</p>}
  </form>;
}
