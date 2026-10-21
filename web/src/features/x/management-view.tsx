'use client';

import { useEffect, useMemo, useRef, useState, type FormEvent } from 'react';
import { useQuery } from '@tanstack/react-query';
import Link from 'next/link';
import { useWorkspace } from '@/lib/workspace/provider';
import { useChannels } from '@/lib/api/hooks';
import { disconnectedByCustomer } from '@/lib/channels/state';
import type { XActionInput, XFieldSpec, XOperation, XOverview } from '@/lib/api/x-types';

type Bag = Record<string, unknown>;
type Schema = Record<string, XFieldSpec>;
const control = 'w-full min-h-11 rounded-lg border bg-background px-3 py-2 text-foreground disabled:opacity-50';
const button = 'min-h-11 rounded-lg bg-primary px-4 py-2 text-sm font-medium text-primary-foreground disabled:cursor-not-allowed disabled:opacity-40';
const secondary = 'min-h-11 rounded-lg border px-3 py-2 text-sm disabled:opacity-40';
const card = 'min-w-0 rounded-xl border bg-card p-4 sm:p-6';
const cancellable = new Set(['needs_approval', 'queued', 'dispatching', 'accepted']);
const label = (text: string) => text.replace(/[._]/g, ' ');
const bag = (value: unknown): Bag => value && typeof value === 'object' && !Array.isArray(value) ? value as Bag : {};
const money = (value: number | null | undefined) => typeof value === 'number' && Number.isSafeInteger(value) && value >= 0
  ? new Intl.NumberFormat('en-US', { style: 'currency', currency: 'USD', maximumFractionDigits: 6 }).format(value / 1_000_000) : 'Cost not verified';
const date = (value?: number | null) => typeof value === 'number' && Number.isFinite(value) ? new Date(value * 1000).toLocaleString() : 'Not scheduled';
const nested: Record<string, Schema> = {
  reply: { in_reply_to_tweet_id: { kind: 'id', required: true }, exclude_reply_user_ids: { kind: 'ids', maximum: 100 } },
  edit: { previous_post_id: { kind: 'id', required: true } },
  post_media: { media_ids: { kind: 'ids', required: true, maximum: 4 }, tagged_user_ids: { kind: 'ids', maximum: 10 } },
  poll: { options: { kind: 'lines', required: true, maximum: 4 }, duration_minutes: { kind: 'integer', required: true, maximum: 10080 } },
  dm_message: { text: { kind: 'text', maximum: 10000 }, attachments: { kind: 'dm_attachments' } }
};

function encode(schema: Schema, values: Bag): Bag {
  const result: Bag = {};
  for (const [key, field] of Object.entries(schema)) {
    const value = values[key];
    if (value === undefined || (value === '' && !['string', 'media_metadata'].includes(field.kind))) {
      if (field.required) throw new Error('Complete ' + label(key) + '.');
      continue;
    }
    if (nested[field.kind]) result[key] = encode(nested[field.kind], bag(value));
    else if (field.kind === 'integer') {
      const n = Number(value);
      if (!Number.isSafeInteger(n) || n < 1 || (field.maximum && n > field.maximum)) throw new Error('Check ' + label(key) + '.');
      result[key] = n;
    } else if (['ids', 'lines', 'thread_posts'].includes(field.kind)) {
      const parts = String(value).split(field.kind === 'ids' ? /[\s,]+/ : /\r?\n/).map(x => x.trim()).filter(Boolean);
      if (!parts.length || (field.maximum && parts.length > field.maximum)) throw new Error('Check ' + label(key) + '.');
      result[key] = field.kind === 'thread_posts' ? parts.map(text => ({ text })) : parts;
    } else if (field.kind === 'fields') {
      if (Array.isArray(value) && value.length) result[key] = value.join(',');
      else if (field.required) throw new Error('Choose ' + label(key) + '.');
    } else if (field.kind === 'dm_attachments') result[key] = [{ media_id: String(value).trim() }];
    else if (field.kind === 'media_metadata') result[key] = { alt_text: { text: String(value) } };
    else result[key] = value;
  }
  return result;
}

function Field({ name, field, value, change }: { name: string; field: XFieldSpec; value: unknown; change: (value: unknown) => void }) {
  const schema = nested[field.kind];
  if (schema) {
    const active = field.required || value !== undefined;
    return <fieldset className='space-y-3 rounded-lg border p-3'>
      <legend className='px-1 text-sm font-medium'>{label(name)}</legend>
      {!field.required && <label className='flex min-h-11 items-center gap-2 text-sm'><input aria-label={'Include ' + label(name)} type='checkbox' checked={!!active}
        onChange={e => change(e.target.checked ? {} : undefined)} />Include {label(name)}</label>}
      {active && Object.entries(schema).map(([key, child]) => <Field key={key} name={key} field={child} value={bag(value)[key]}
        change={next => change({ ...bag(value), [key]: next })} />)}
    </fieldset>;
  }
  const common = { className: control, required: !!field.required, 'aria-label': label(name) };
  return <label className='block space-y-1 text-sm'>
    <span className='font-medium'>{label(name)}{field.required ? ' *' : ''}</span>
    {field.kind === 'bool' ? <select {...common} value={value === undefined ? '' : String(value)} onChange={e => change(e.target.value === '' ? undefined : e.target.value === 'true')}>
      <option value=''>{field.required ? 'Choose…' : 'Use default'}</option><option value='true'>Yes</option><option value='false'>No</option>
    </select> : field.kind === 'enum' ? <select {...common} value={String(value ?? '')} onChange={e => change(e.target.value || undefined)}>
      <option value=''>Choose…</option>{field.choices?.map(choice => <option key={choice}>{choice}</option>)}
    </select> : field.kind === 'fields' ? <select {...common} multiple size={Math.min(5, field.choices?.length || 3)} value={Array.isArray(value) ? value as string[] : []}
      onChange={e => change(Array.from(e.target.selectedOptions, option => option.value))}>
      {field.choices?.map(choice => <option key={choice} value={choice}>{label(choice)}</option>)}
    </select> : ['text', 'ids', 'lines', 'thread_posts', 'media_metadata'].includes(field.kind) ? <textarea {...common}
      rows={field.kind === 'text' || field.kind === 'thread_posts' ? 4 : 2}
      maxLength={['text', 'media_metadata'].includes(field.kind) ? field.maximum ?? undefined : undefined}
      value={String(value ?? '')} onChange={e => change(e.target.value)}
      placeholder={field.kind === 'ids' ? 'X IDs separated by commas or spaces' : field.kind === 'lines' ? 'One choice per line' : field.kind === 'thread_posts' ? 'One complete post per line, in order' : undefined} />
    : <input {...common} type={field.kind === 'integer' ? 'number' : 'text'}
      min={field.kind === 'integer' ? 1 : undefined} max={field.kind === 'integer' ? field.maximum ?? undefined : undefined}
      maxLength={field.kind === 'string' ? field.maximum ?? undefined : undefined}
      inputMode={['id', 'integer', 'dm_attachments'].includes(field.kind) ? 'numeric' : undefined}
      value={String(value ?? '')} onChange={e => change(e.target.value)} />}
    {field.kind === 'ids' && field.maximum && <span className='block text-xs text-muted-foreground'>Up to {field.maximum} IDs.</span>}
  </label>;
}

function Values({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span className='text-muted-foreground'>Not returned</span>;
  if (Array.isArray(value)) return value.length ? <ol className='space-y-2'>{value.map((item, i) => <li key={i} className='border-l-2 pl-3'><Values value={item} /></li>)}</ol> : <span className='text-muted-foreground'>None returned</span>;
  if (typeof value === 'object') return <dl className='space-y-2'>{Object.entries(bag(value)).map(([key, item]) => <div key={key} className='grid gap-1 sm:grid-cols-[minmax(7rem,1fr)_3fr]'>
    <dt className='break-words text-sm text-muted-foreground'>{label(key)}</dt><dd className='min-w-0 break-words'><Values value={item} /></dd></div>)}</dl>;
  return <span className='whitespace-pre-wrap break-words text-sm'>{typeof value === 'boolean' ? value ? 'Yes' : 'No' : String(value)}</span>;
}

function receiptUrl(receipt: unknown) {
  const value = bag(receipt).url;
  if (typeof value !== 'string') return undefined;
  try {
    const url = new URL(value);
    if (url.protocol === 'https:' && url.hostname === 'x.com' && !url.username && !url.password
      && /^\/(?:i\/web|[A-Za-z0-9_]+)\/status\/[1-9][0-9]*(?:\/|$)/.test(url.pathname)) return value;
  } catch { /* Invalid receipt links remain inert. */ }
}

export function XManagementView() {
  const { api, workspaceId } = useWorkspace();
  const channels = useChannels();
  const accounts = useMemo(() => (channels.data?.channels ?? []).filter(c => c.platform === 'X' && !disconnectedByCustomer(c)), [channels.data]);
  const [connectionId, setConnectionId] = useState('');
  const [operationId, setOperationId] = useState('');
  const [body, setBody] = useState<Bag>({});
  const [query, setQuery] = useState<Bag>({});
  const [paths, setPaths] = useState<Record<string, string>>({});
  const [resources, setResources] = useState(1);
  const [schedule, setSchedule] = useState('');
  const [draft, setDraft] = useState<XOperation | null>(null);
  const [confirmed, setConfirmed] = useState(false);
  const [readResult, setReadResult] = useState<unknown>();
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [notice, setNotice] = useState('');
  const requestKey = useRef('');
  const scope = String(workspaceId) + ':' + connectionId;
  const currentScope = useRef(scope);
  currentScope.current = scope;
  useEffect(() => () => { currentScope.current = ''; }, []);
  useEffect(() => {
    if (!accounts.some(c => c.id === connectionId)) {
      const requested = new URLSearchParams(window.location.search).get('channel');
      setConnectionId(accounts.find(c => c.id === requested)?.id ?? accounts[0]?.id ?? '');
    }
  }, [accounts, connectionId]);
  useEffect(() => {
    setOperationId(''); setDraft(null); setConfirmed(false); setReadResult(undefined);
    setError(''); setNotice(''); setBusy(false); requestKey.current = '';
  }, [scope]);
  const overview = useQuery<XOverview>({
    queryKey: ['x-direct-overview', workspaceId, connectionId],
    queryFn: () => api.xOverview(workspaceId!, connectionId),
    enabled: !!workspaceId && !!connectionId,
    refetchInterval: state => state.state.data?.operations.some(o => ['queued', 'accepted', 'dispatching'].includes(o.state)) ? 5000 : false
  });
  const data = overview.data;
  const decision = data?.capabilities.find(d => d.capability.id === operationId);
  const capability = decision?.capability;
  useEffect(() => {
    setBody({}); setPaths({}); setQuery(capability?.collection ? { max_results: 10 } : {});
    setResources(capability?.collection ? 10 : 1); setSchedule('');
    setDraft(null); setConfirmed(false); setReadResult(undefined); setError(''); requestKey.current = '';
  }, [operationId, capability?.collection]);
  function changed(update: () => void) { update(); setDraft(null); setConfirmed(false); setError(''); requestKey.current = ''; }
  async function act(task: () => Promise<unknown>, done: (value: unknown) => void) {
    if (busy) return;
    const started = scope;
    setBusy(true); setError(''); setNotice('');
    try {
      const result = await task();
      if (currentScope.current === started) { done(result); void overview.refetch(); }
    } catch (e) {
      if (currentScope.current === started) setError(e instanceof Error ? e.message : 'The Direct action could not be completed.');
    } finally { if (currentScope.current === started) setBusy(false); }
  }
  function submit(event: FormEvent) {
    event.preventDefault();
    if (!capability || !workspaceId) return;
    try {
      const input: XActionInput = { operation: capability.id, path: paths, body: encode(capability.body_schema, body),
        query: encode(capability.query_schema, query), maxBillableResources: resources };
      if (schedule) {
        const at = new Date(schedule).getTime() / 1000;
        if (!Number.isFinite(at) || at <= Date.now() / 1000) throw new Error('Choose a future schedule time.');
        input.scheduleAt = at;
      }
      if (capability.mutates) {
        requestKey.current ||= crypto.randomUUID();
        input.requestKey = requestKey.current;
        void act(() => api.xPreview(workspaceId, connectionId, input), value => {
          const operation = value as XOperation;
          if (!operation?.id || !operation.digest || !operation.request) throw new Error('No complete approval preview was returned.');
          setDraft(operation); setConfirmed(false);
        });
      } else void act(() => api.xRead(workspaceId, connectionId, input), setReadResult);
    } catch (e) { setError(e instanceof Error ? e.message : 'Check the action fields.'); }
  }
  const ready = !!(data?.directOnly && data.costReady && data.journalReady && decision?.ready_for_preview);
  const accountName = accounts.find(a => a.id === connectionId)?.account ?? connectionId;
  const expired = !!draft?.expiresAt && draft.expiresAt <= Date.now() / 1000;
  const cost = draft?.request.estimatedMaxCostMicros;
  const verifiedCost = typeof cost === 'number' && Number.isSafeInteger(cost) && cost >= 0;
  const canSchedule = capability && ['posts.create', 'posts.reply', 'posts.quote', 'posts.thread'].includes(capability.id);
  function addImage(file?: File) {
    if (!file || !workspaceId) return;
    if (!['image/jpeg', 'image/png'].includes(file.type) || file.size > 8 * 1024 * 1024) {
      setError('Choose a JPEG or PNG image of at most 8 MB. The server verifies its contents.'); return;
    }
    const targetWorkspace = workspaceId;
    void act(async () => {
      const encoded = await new Promise<string>((resolve, reject) => {
        const reader = new FileReader();
        reader.addEventListener('load', () => resolve(String(reader.result).split(',')[1] || ''), { once: true });
        reader.addEventListener('error', () => reject(new Error('Could not read the selected image.')), { once: true });
        reader.readAsDataURL(file);
      });
      const snapshot = await api.snapshot(targetWorkspace);
      return api.act(targetWorkspace, snapshot.revision, 'p2_media_upload', { data: encoded });
    }, () => { setDraft(null); setConfirmed(false); setNotice('Image saved privately to this workspace. Review and approve its X upload separately.'); });
  }


  return <main className='mx-auto max-w-6xl space-y-6 p-4 text-foreground sm:p-8'>
    <header className='flex flex-wrap items-center justify-between gap-3'>
      <div><h1 className='text-2xl font-semibold'>Manage X</h1><p className='mt-1 text-sm text-muted-foreground'>Official X API actions for your connected account.</p></div>
      <Link className={secondary} href='/app/channels'>Connect or reconnect X</Link>
    </header>
    {(channels.error || overview.error || error) && <div role='alert' className='rounded-lg border border-destructive p-4 text-sm'>
      {error || (overview.error instanceof Error ? overview.error.message : 'Could not load X account availability.')}
      {!error && <button type='button' className='ml-3 underline' onClick={() => { void channels.refetch(); if (connectionId) void overview.refetch(); }}>Retry</button>}
    </div>}
    {notice && <p role='status' className='rounded-lg bg-muted p-3 text-sm'>{notice}</p>}
    <section className={card}><label className='block max-w-xl space-y-2 text-sm font-medium'>Connected X account
      <select aria-label='Connected X account' className={control} value={connectionId} disabled={busy || !accounts.length} onChange={e => setConnectionId(e.target.value)}>
        {!accounts.length && <option value=''>No connected X account</option>}
        {accounts.map(a => <option key={a.id} value={a.id}>{a.account}</option>)}
      </select></label>
      {!accounts.length && !channels.isLoading && <p className='mt-3 text-sm text-muted-foreground'>Connect your X account to see its available Direct actions.</p>}
      {overview.isLoading && connectionId && <p className='mt-3 text-sm' role='status'>Loading account availability…</p>}
      {data && (!data.costReady || !data.journalReady) && <p className='mt-3 text-sm'>Direct requests are unavailable until account usage and operation storage are ready.</p>}
    </section>
    {data && <div className='grid items-start gap-6 lg:grid-cols-2'>
      <section className={card}><h2 className='mb-4 text-lg font-semibold'>Choose an action</h2>
        <form onSubmit={submit} className='space-y-4'><fieldset disabled={busy} className='space-y-4'>
          <label className='block space-y-1 text-sm font-medium'>Action<select aria-label='Action' className={control} value={operationId} onChange={e => setOperationId(e.target.value)}>
            <option value=''>Choose an available action…</option>{data.capabilities.map(d => <option key={d.capability.id} value={d.capability.id} disabled={!d.ready_for_preview}>
              {d.capability.title}{d.ready_for_preview ? '' : ' — Unavailable'}</option>)}
          </select></label>
          {capability?.input_path_params.map(name => <Field key={name} name={name} field={{ kind: name === 'username' || name === 'dm_conversation_id' ? 'token' : 'id', required: true }}
            value={paths[name]} change={v => changed(() => setPaths(p => ({ ...p, [name]: String(v ?? '') })))} />)}
          {capability?.id === 'media.upload' && <div className='space-y-2 rounded-lg border p-3 text-sm'>
            <label className='block space-y-1'>Add image to this workspace
              <input aria-label='Add image to this workspace' className='block w-full min-w-0 text-sm' type='file' accept='image/jpeg,image/png' disabled={busy}
                onChange={event => { const file = event.target.files?.[0]; event.target.value = ''; addImage(file); }} />
            </label>
            <p className='text-xs text-muted-foreground'>Private preparation only. Nothing is sent to X until you approve the exact upload. Images: 320–4096 pixels per side.</p>
            <Link className='underline' href='/app/library'>Prepare videos in your Library</Link>
          </div>}
          {capability && Object.entries(capability.body_schema).map(([name, field]) =>
            capability.id === 'media.upload' && name === 'asset_id' ? <label key={name} className='block space-y-1 text-sm'>Workspace media asset
              <select aria-label='Workspace media asset' className={control} required value={String(body.asset_id ?? '')}
                onChange={e => changed(() => setBody(p => ({ ...p, asset_id: e.target.value })))}>
                <option value=''>Choose verified workspace media…</option>
                {(data.mediaAssets ?? []).map(asset => <option key={asset.id} value={asset.id}>{asset.mime} · {Math.ceil(asset.bytes / 1024)} KB · {asset.id.slice(0, 8)}</option>)}
              </select>
            </label> : name === 'media' && field.kind === 'post_media' ? <fieldset key={name} className='space-y-2 rounded-lg border p-3'>
              <legend className='px-1 text-sm font-medium'>Media attachments</legend>
              {!(data.uploadedMedia ?? []).length && <p className='text-xs text-muted-foreground'>Upload and approve media first. Expired or unverified uploads cannot be attached.</p>}
              {(data.uploadedMedia ?? []).map(upload => {
                const selected = String(bag(body.media).media_ids ?? '').split(/[\s,]+/).filter(Boolean);
                return <label key={upload.id} className='flex min-h-11 items-start gap-2 text-sm'>
                  <input aria-label={'Attach uploaded media ' + upload.id} className='mt-1' type='checkbox' checked={selected.includes(upload.id)}
                    onChange={event => changed(() => {
                      const ids = event.target.checked ? [...selected, upload.id] : selected.filter(id => id !== upload.id);
                      setBody(p => ({ ...p, media: ids.length ? { media_ids: ids.join(',') } : undefined }));
                    })} />
                  <span className='min-w-0 break-words'>{upload.mime} · {upload.id}<span className='block text-xs text-muted-foreground'>Expires {date(upload.expiresAt)}{upload.altText ? ' · ' + upload.altText : ''}</span></span>
                </label>;
              })}
            </fieldset> : <Field key={name} name={name} field={field} value={body[name]} change={v => changed(() => setBody(p => ({ ...p, [name]: v })))} />)}
          {capability && Object.keys(capability.query_schema).length > 0 && <details className='rounded-lg border p-3' open={!capability.mutates}>
            <summary className='cursor-pointer text-sm font-medium'>Read options</summary><div className='mt-3 space-y-3'>
              {Object.entries(capability.query_schema).map(([name, field]) => <Field key={name} name={name} field={field} value={query[name]} change={v => changed(() => setQuery(p => ({ ...p, [name]: v })))} />)}
            </div></details>}
          {capability && !capability.mutates && <label className='block space-y-1 text-sm'>Maximum billable resources
            <input aria-label='Maximum billable resources' className={control} type='number' min={1} max={10000} required value={resources} onChange={e => changed(() => setResources(Number(e.target.value)))} />
            <span className='block text-xs text-muted-foreground'>Must cover the requested results. The server also checks your admitted budget.</span>
          </label>}
          {canSchedule && <label className='block space-y-1 text-sm'>Schedule, optional — your local time<input aria-label='Schedule in your local time' className={control} type='datetime-local' value={schedule} onChange={e => changed(() => setSchedule(e.target.value))} /></label>}
          <button className={button} type='submit' disabled={!ready || busy}>{busy ? 'Working…' : capability?.mutates ? 'Preview exact action' : 'Read X data'}</button>
          {capability && <p className='text-xs text-muted-foreground'>{capability.mutates ? 'Preview creates a review. Approve it separately to authorize execution.' : 'This button runs a billable official X API read within the admitted budget.'}</p>}
        </fieldset></form>
        <details className='mt-5 border-t pt-4'><summary className='cursor-pointer text-sm font-medium'>All capability availability ({data.capabilities.length})</summary>
          <ul className='mt-3 max-h-96 space-y-3 overflow-y-auto'>{data.capabilities.map(d => <li key={d.capability.id} className='border-b pb-3 text-sm'>
            <p className='font-medium'>{d.capability.title}</p><p className='mt-1 text-muted-foreground'>{d.reason}</p></li>)}</ul>
        </details>
      </section>
      <div className='min-w-0 space-y-6'>
        {draft && <section className={card}><h2 className='text-lg font-semibold'>Review exact action</h2>
          <p className='mt-1 text-sm'>{label(draft.operation)} · {accountName}</p>
          <div className='my-4'><Values value={{ target: draft.request.path, content: draft.request.body, options: draft.request.query }} /></div>
          <dl className='space-y-2 border-t pt-3 text-sm'><div className='flex justify-between gap-3'><dt>Maximum estimated workflow usage</dt><dd className='font-medium'>{money(cost)}</dd></div>
            <div><dt className='text-muted-foreground'>Timing</dt><dd>{draft.request.scheduleAt ? date(draft.request.scheduleAt) : 'Dispatch after approval'}</dd></div>
            <div><dt className='text-muted-foreground'>Preview expires</dt><dd>{date(draft.expiresAt)}</dd></div></dl>
          <p className='mt-3 text-xs text-muted-foreground'>This approval includes up to {draft.request.maximumApiRequests} API requests, covering permitted retries and post readback. Estimates and request limits are not a guaranteed provider invoice cap.</p>
          {expired && <p className='mt-3 text-sm text-destructive'>This preview expired. Create a new preview.</p>}
          <label className='mt-4 flex min-h-11 items-start gap-3 text-sm'><input aria-label='Approve this exact action and estimated usage' className='mt-1' type='checkbox' checked={confirmed} disabled={busy || expired}
            onChange={e => setConfirmed(e.target.checked)} /><span>I approve this exact action, account, target, content, timing and estimated usage.</span></label>
          <button type='button' className={button + ' mt-4'} disabled={busy || !confirmed || expired || !verifiedCost || !data.costReady || !data.journalReady}
            onClick={() => void act(() => api.xApprove(workspaceId!, connectionId, draft.id, { digest: draft.digest, confirmed: true }), value => {
              setDraft(null); setConfirmed(false); setNotice('Approval recorded. Current status: ' + label((value as XOperation).state) + '. Provider evidence appears below when available.');
            })}>Approve this action</button>
        </section>}
        {readResult !== undefined && <section className={card}><h2 className='mb-4 text-lg font-semibold'>X API read result</h2><div className='max-h-[36rem] overflow-auto'><Values value={readResult} /></div></section>}
        <section className={card}><h2 className='mb-4 text-lg font-semibold'>Actions and provider evidence</h2>
          {!data.operations.length && <p className='text-sm text-muted-foreground'>No Direct actions recorded for this account.</p>}
          <ol className='space-y-5'>{data.operations.map(o => <li key={o.id} data-x-operation={o.id} data-x-state={o.state} className='space-y-2 border-b pb-4 last:border-0'>
            <div className='flex flex-wrap justify-between gap-2'><strong className='text-sm'>{label(o.operation)}</strong><span className='rounded bg-muted px-2 py-1 text-xs'>{label(o.state)}</span></div>
            <p className='text-xs text-muted-foreground'>{date(o.createdAt)}{o.request.scheduleAt ? ' · Scheduled ' + date(o.request.scheduleAt) : ''}</p>
            {o.reason && <p className='text-sm'>{o.reason}</p>}
            {o.receipts?.length ? o.receipts.map((receipt, i) => <details key={i} className='rounded border p-3 text-sm'><summary className='cursor-pointer'>Recorded API result {i + 1}</summary>
              <div className='mt-3'><Values value={receipt} /></div>{receiptUrl(receipt) && <a className='mt-3 inline-block underline' href={receiptUrl(receipt)} target='_blank' rel='noopener noreferrer'>View on X</a>}
            </details>) : <p className='text-xs text-muted-foreground'>No provider receipt recorded yet.</p>}
            <div className='flex flex-wrap gap-2'>
              {o.state === 'needs_approval' && <button className={secondary} disabled={busy} onClick={() => { setDraft(o); setConfirmed(false); }}>Review approval</button>}
              {cancellable.has(o.state) && <button className={secondary} disabled={busy || o.cancelRequested} onClick={() => void act(() => api.xCancel(workspaceId!, connectionId, o.id), () => {
                if (draft?.id === o.id) { setDraft(null); setConfirmed(false); }
                setNotice('Cancellation recorded. Any request already accepted by X retains its actual result.');
              })}>Cancel pending action</button>}
            </div></li>)}</ol>
        </section>
      </div>
    </div>}
  </main>;
}
