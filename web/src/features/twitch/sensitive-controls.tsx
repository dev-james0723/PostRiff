'use client';

import { useEffect, useRef, useState, type FormEvent } from 'react';
import { Surface } from '@/components/rafii/surface';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Label } from '@/components/ui/label';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useAuth } from '@/lib/auth/session';
import { NativeFields } from './native-fields';
import { clipDownloadHref, effectsList, parseFields, reviewCanApprove, submissionSignature } from './contracts';
import { displayTime } from './receipts';
import type { TwitchAction, TwitchCapability, TwitchConnection, TwitchSecretResult } from './types';

/** Separate interactive custody path; this entire subtree is excluded from the agent's page context. */
export function SensitiveTwitchControls({ connection, capabilities, mode, refresh }: {
  connection: TwitchConnection;
  capabilities: TwitchCapability[];
  mode: 'clips' | 'encoder';
  refresh: () => Promise<void>;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const { user } = useAuth();
  const action = mode === 'clips' ? 'twitch.clip.download' : 'twitch.stream.key.get';
  const capability = capabilities.find((item) => item.action === action);
  const [values, setValues] = useState<Record<string, unknown>>({});
  const [declared, setDeclared] = useState(false);
  const [confirmed, setConfirmed] = useState(false);
  const [review, setReview] = useState<{ action: TwitchAction; signature: string }>();
  const [result, setResult] = useState<TwitchSecretResult>();
  const [showKey, setShowKey] = useState(false);
  const [hideAt, setHideAt] = useState(0);
  const [clock, setClock] = useState(Date.now());
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(true);
  const visibilityGeneration = useRef(0);

  useEffect(() => {
    mounted.current = true;
    const hide = () => { visibilityGeneration.current++; setResult(undefined); setShowKey(false); setReview(undefined); setConfirmed(false); setHideAt(0); };
    const visibility = () => { if (document.visibilityState !== 'visible') hide(); };
    document.addEventListener('visibilitychange', visibility);
    window.addEventListener('pagehide', hide);
    return () => { mounted.current = false; document.removeEventListener('visibilitychange', visibility); window.removeEventListener('pagehide', hide); };
  }, []);

  useEffect(() => {
    if (!review && !result) return;
    const timer = setInterval(() => {
      const now = Date.now(); setClock(now);
      if (hideAt && now >= hideAt) { setResult(undefined); setShowKey(false); setHideAt(0); }
    }, 1000);
    return () => clearInterval(timer);
  }, [review, result, hideAt]);

  function edited() { setReview(undefined); setConfirmed(false); setResult(undefined); setShowKey(false); setError(''); }
  let signature = '';
  try { if (capability) signature = submissionSignature(action, parseFields(capability.fields, values), undefined, mode === 'clips' ? { rightsConfirmed: declared } : undefined); } catch { /* The form explains required fields on submit. */ }
  const current = review?.signature === signature ? review.action : undefined;
  const authorizedActor = Boolean(user?.id && current?.actorId === user.id);
  const canRetrieve = declared && current && authorizedActor && capability?.interactiveAvailable === true &&
    reviewCanApprove(current, connection.authorizationGeneration, clock) && (mode !== 'clips' || current.declarations?.rightsConfirmed === true);

  async function preview(event: FormEvent) {
    event.preventDefault();
    if (!capability || capability.interactiveAvailable !== true || !declared || busy) return;
    setBusy(true); setError(''); setReview(undefined); setConfirmed(false); setResult(undefined);
    const generation = visibilityGeneration.current;
    try {
      const payload = parseFields(capability.fields, values);
      const prepared = await api.twitchPreview(workspaceId, connection.id, { action, payload, ...(mode === 'clips' ? { rightsConfirmed: true as const } : {}) });
      if (!mounted.current || generation !== visibilityGeneration.current || document.visibilityState !== 'visible') return;
      if (prepared.action !== action) throw new Error('The server prepared a different request. Do not approve this preview.');
      setClock(Date.now());
      setReview({ action: prepared, signature: submissionSignature(action, payload, undefined, mode === 'clips' ? { rightsConfirmed: true } : undefined) });
      await refresh();
    } catch (err) { if (mounted.current) setError(err instanceof Error ? err.message : 'Secure preview is unavailable.'); }
    finally { if (mounted.current) setBusy(false); }
  }

  async function retrieve() {
    if (!current || !canRetrieve || !confirmed || busy) return;
    setBusy(true); setError('');
    const generation = visibilityGeneration.current;
    try {
      const approved = await api.twitchApprove(workspaceId, connection.id, current.id, current.payloadHash);
      if (!mounted.current || generation !== visibilityGeneration.current || document.visibilityState !== 'visible') return;
      if (approved.state !== 'approved' || approved.payloadHash !== current.payloadHash) throw new Error('The request was not approved for retrieval. Check its receipt.');
      const response = await api.twitchSecretAccess(workspaceId, connection.id, current.id, current.payloadHash);
      if (!mounted.current || generation !== visibilityGeneration.current || document.visibilityState !== 'visible') return;
      if (response.action !== action || response.stored !== false || response.displayOnce !== true) throw new Error('The secure response did not match this request.');
      setResult(response); setShowKey(false); setHideAt(Date.now() + 30_000); setClock(Date.now());
    } catch (err) {
      if (mounted.current) setError(err instanceof Error ? err.message : 'The secure response could not be received. Check the saved receipt before trying again.');
    } finally {
      if (mounted.current) { setReview(undefined); setConfirmed(false); setBusy(false); }
      await refresh();
    }
  }

  if (!capability) return null;
  const data = result?.secretResult?.data;
  const key = mode === 'encoder' && data && typeof data === 'object' && !Array.isArray(data) && typeof (data as Record<string, unknown>).streamKey === 'string' ? (data as { streamKey: string }).streamKey : '';
  const clips = mode === 'clips' && Array.isArray(data) ? data.filter((item) => item && typeof item === 'object') as Record<string, unknown>[] : [];

  return (
    <Surface as='section' material='quiet' className='grid gap-4' data-private aria-label={mode === 'clips' ? 'Authorized clip download access' : 'Secure encoder configuration'}>
      <h2 className='font-medium'>{mode === 'clips' ? 'Authorized clip downloads' : 'Encoder stream key'}</h2>
      <p className='text-muted-foreground text-sm leading-relaxed'>{mode === 'clips' ? 'Get expiring official download links for clips you have the right to store and reuse. Review the clips first; downloads remain a separate click.' : 'A stream key permits broadcasting as this channel. Retrieve it only when configuring your encoder. It is excluded from Rafii Agent context and cleared from this page after 30 seconds.'}</p>
      {capability.interactiveAvailable !== true && <p role='status' className='text-muted-foreground text-sm'>Secure access is unavailable for this account. The server must verify release access, current permissions and account eligibility first.</p>}
      <form onSubmit={(event) => void preview(event)} className='grid gap-4'>
        <NativeFields fields={capability.fields} values={values} disabled={busy || capability.interactiveAvailable !== true} onChange={(next) => { setValues(next); edited(); }} />
        <Label id='twitch-secure-declaration-label' className='flex items-start gap-2 text-sm font-normal leading-relaxed'><input type='checkbox' aria-labelledby='twitch-secure-declaration-label' className='rafii-focus mt-1 size-4 shrink-0' disabled={busy || capability.interactiveAvailable !== true} checked={declared} onChange={(event) => { setDeclared(event.target.checked); edited(); }} />{mode === 'clips' ? 'I have permission to download, store and reuse these exact clips. I understand that Twitch access alone does not grant content rights.' : `I need the stream key for ${connection.account} to configure an encoder, and I understand that it grants broadcast access.`}</Label>
        <Button type='submit' variant='outline' disabled={busy || capability.interactiveAvailable !== true || !declared} className='justify-self-start'>{busy ? 'Working…' : 'Prepare secure review'}</Button>
      </form>
      {current && <div className='grid gap-3 rounded-lg border p-4'>
        <h3 className='text-sm font-medium'>Approve this exact retrieval</h3>
        <p className='text-sm'>Account: {connection.account}{connection.providerAccountId ? ` (${connection.providerAccountId})` : ''}</p>
        <pre className='max-h-48 overflow-auto whitespace-pre-wrap break-words text-xs'>{JSON.stringify(current.payload, null, 2)}</pre>
        {mode === 'clips' && <p className='text-sm'>{current.declarations?.rightsConfirmed === true ? 'Your content-rights declaration is included in this approval.' : 'The server has not included your rights declaration. Prepare a new review.'}</p>}
        {effectsList(current.effects).map((effect) => <p key={effect} className='text-muted-foreground text-xs'>{effect}</p>)}
        <p className='text-muted-foreground text-xs'>Expires {displayTime(current.expiresAt)}. A recent sign-in is required.</p>
        <Label id='twitch-secure-approval-label' className='flex items-start gap-2 text-sm font-normal'><input type='checkbox' aria-labelledby='twitch-secure-approval-label' className='rafii-focus mt-1 size-4 shrink-0' checked={confirmed} disabled={busy || !canRetrieve} onChange={(event) => setConfirmed(event.target.checked)} />I approve this exact account and retrieval now.</Label>
        <Button type='button' disabled={busy || !canRetrieve || !confirmed} onClick={() => void retrieve()} className='justify-self-start'>{mode === 'clips' ? 'Approve & get download links' : 'Approve & retrieve stream key'}</Button>
        {!canRetrieve && <p role='alert' className='text-destructive text-sm'>This review cannot be used: check the account, approval expiry, declaration and signed-in person.</p>}
      </div>}
      {error && <p role='alert' className='text-destructive text-sm'>{error}</p>}
      {result && <div className='grid gap-3 rounded-lg border p-4'>
        <p className='text-muted-foreground text-xs'>Clears in {Math.max(0, Math.ceil((hideAt - clock) / 1000))} seconds. Leaving or hiding this page clears it immediately.</p>
        {key ? <div className='grid gap-2'><Label htmlFor='twitch-encoder-key'>Stream key</Label><Input id='twitch-encoder-key' type={showKey ? 'text' : 'password'} value={key} readOnly autoComplete='off' spellCheck={false} /><Button type='button' size='sm' variant='outline' className='justify-self-start' onClick={() => setShowKey((value) => !value)}>{showKey ? 'Mask key' : 'Show key'}</Button></div> : mode === 'encoder' ? <p role='alert' className='text-destructive text-sm'>No stream key was returned. Check the retrieval receipt.</p> : <ul className='grid gap-3'>{clips.map((clip, index) => <li key={index} className='grid gap-2'><p className='text-sm'>Clip {typeof clip.clip_id === 'string' ? clip.clip_id : index + 1}</p><div className='flex flex-wrap gap-3'>{(['landscape_download_url', 'portrait_download_url'] as const).map((field) => { const href = clipDownloadHref(clip[field]); return href ? <a key={field} href={href} target='_blank' rel='noopener noreferrer' className='rafii-focus rounded-sm text-sm underline underline-offset-4'>{field.startsWith('landscape') ? 'Open landscape download' : 'Open portrait download'}</a> : null; })}</div></li>)}</ul>}
        <Button type='button' variant='ghost' size='sm' onClick={() => { setResult(undefined); setShowKey(false); setHideAt(0); }} className='justify-self-start'>Hide now</Button>
      </div>}
    </Surface>
  );
}
