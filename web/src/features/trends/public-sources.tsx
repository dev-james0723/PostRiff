'use client';
import { useEffect, useId, useRef, useState, type FormEvent } from 'react';
import { Button } from '@/components/ui/button';
import { StateMessage, Surface } from '@/components/rafii';
import { usePreferences } from '@/lib/preferences';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import { fieldClass } from './present';
import { publicSourceCopy, publicSourcePresentation, verificationKeys, type PublicSource } from './public-source-types';
import type { DiscoveryRequestInput, DiscoveryRequestReceipt } from './api';

type Copy = ReturnType<typeof publicSourceCopy>;
type RequestOption = { provider: PublicSource['provider']; enabled: boolean; reviewed_page_ids: string[] };
function SourceRow({ source, option, copy, formatDate, refresh, requested }: {
  source: PublicSource; option?: RequestOption; copy: Copy; formatDate: (value: string) => string;
  refresh: () => void; requested: (receipt: DiscoveryRequestReceipt) => void;
}) {
  const { api, w } = useTrendContext();
  const id = useId();
  const deadline = source.expires_at && source.latest_successful_read
    ? new Date(Math.min(Date.parse(source.expires_at), Date.parse(source.latest_successful_read) + 900_000)).toISOString()
    : source.expires_at;
  const grantExpired = useExpired(source.expires_at);
  const readingExpired = useExpired(deadline);
  const shown = publicSourcePresentation(source, grantExpired, readingExpired);
  const [confirm, setConfirm] = useState(false);
  const [revoking, setRevoking] = useState(false);
  const [revokeError, setRevokeError] = useState(false);
  const [value, setValue] = useState('');
  const [searchType, setSearchType] = useState<'TOP' | 'RECENT'>('TOP');
  const [submitting, setSubmitting] = useState(false);
  const [requestError, setRequestError] = useState(false);
  const submission = useRef<{ fingerprint: string; key: string } | null>(null);
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const allowed = option?.enabled === true && source.dispatch_enabled && Boolean(source.authorization_id) && !grantExpired
    && shown.verification.verified_scope_or_feature === 'VERIFIED'
    && !['REVOKED', 'PAUSED', 'APP_REVIEW_REQUIRED', 'AUTHORIZATION_REQUIRED'].includes(shown.status);
  const revoke = async () => {
    setRevoking(true); setRevokeError(false);
    try { await api.revokePublicSource(w, source.authorization_id!); if (mounted.current) { setConfirm(false); refresh(); } }
    catch { if (mounted.current) setRevokeError(true); }
    finally { if (mounted.current) setRevoking(false); }
  };
  const submit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    if (!allowed || submitting || !value.trim()) return;
    if (source.provider === 'facebook' && !option?.reviewed_page_ids.includes(value)) return;
    const selection = source.provider === 'instagram' ? { hashtag: value.trim().replace(/^#/, '') }
      : source.provider === 'threads' ? { query: value.trim(), search_type: searchType }
      : { reviewed_page_id: value };
    const fingerprint = JSON.stringify({ provider: source.provider, selection });
    const attempt = submission.current?.fingerprint === fingerprint ? submission.current : { fingerprint, key: crypto.randomUUID() };
    submission.current = attempt;
    const input = { provider: source.provider, selection, idempotency_key: attempt.key } as DiscoveryRequestInput;
    setSubmitting(true); setRequestError(false);
    try { const result = await api.submitDiscoveryRequest(w, input); if (mounted.current) requested(result.data); }
    catch { if (mounted.current) setRequestError(true); }
    finally { if (mounted.current) setSubmitting(false); }
  };
  return <li className='min-w-0 space-y-3 break-words rounded-xl border p-4'>
    <h3 className='font-medium'>{copy.providers[source.provider]}</h3>
    <p className='text-sm' role='status'>{copy.statuses[shown.status]}</p>
    <dl className='space-y-2 text-sm'>
      {verificationKeys.map(key => <div key={key} data-verification-key={key} className='flex flex-wrap justify-between gap-x-3 gap-y-1'>
        <dt className='min-w-0'>{copy.gates[key]}</dt>
        <dd className='font-medium'>{copy.states[shown.verification[key]]}</dd>
      </div>)}
    </dl>
    <p className='text-muted-foreground text-sm'>{source.latest_successful_read
      ? `${copy.lastRead}: ${formatDate(source.latest_successful_read)}` : copy.noRead}</p>
    <p className='text-muted-foreground text-sm'>{copy.coverage[source.provider]}</p>
    <form onSubmit={event => void submit(event)} className='space-y-2 border-t pt-3' aria-label={`${copy.requestTitle}: ${copy.providers[source.provider]}`}>
      {source.provider === 'facebook' ? <>
        <label htmlFor={`${id}-value`} className='block text-sm'>{copy.page}</label>
        <select id={`${id}-value`} aria-label={copy.page} className={fieldClass} value={value} onChange={event => setValue(event.target.value)} disabled={!allowed || submitting} required>
          <option value=''>{copy.choosePage}</option>
          {(option?.reviewed_page_ids ?? []).map(page => <option key={page} value={page}>{page}</option>)}
        </select>
      </> : <>
        <label htmlFor={`${id}-value`} className='block text-sm'>{source.provider === 'instagram' ? copy.hashtag : copy.query}</label>
        <input id={`${id}-value`} aria-label={source.provider === 'instagram' ? copy.hashtag : copy.query} className={fieldClass} value={value} onChange={event => setValue(event.target.value)}
          disabled={!allowed || submitting} required maxLength={source.provider === 'instagram' ? 80 : 160} autoComplete='off' />
      </>}
      {source.provider === 'threads' && <>
        <label htmlFor={`${id}-order`} className='block text-sm'>{copy.searchOrder}</label>
        <select id={`${id}-order`} aria-label={copy.searchOrder} className={fieldClass} value={searchType} onChange={event => setSearchType(event.target.value as 'TOP' | 'RECENT')} disabled={!allowed || submitting}>
          <option value='TOP'>{copy.top}</option><option value='RECENT'>{copy.recent}</option>
        </select>
      </>}
      {!allowed && <p id={`${id}-disabled`} className='text-muted-foreground text-sm'>{copy.requestDisabled}</p>}
      <Button type='submit' variant='outline' className='min-h-11 max-w-full whitespace-normal' disabled={!allowed || submitting || !value.trim()} aria-describedby={!allowed ? `${id}-disabled` : undefined}>
        {submitting ? copy.queueBusy : copy.queue}
      </Button>
      {requestError && <p role='alert' className='text-sm'>{copy.requestError}</p>}
    </form>
    {source.authorization_id && source.status !== 'REVOKED' && <div>
      {confirm ? <div className='space-y-2'>
        <p className='text-sm'>{copy.revokeConfirm}</p>
        <div className='flex flex-wrap gap-2'>
          <Button variant='destructive' className='min-h-11 max-w-full whitespace-normal' disabled={revoking} onClick={() => void revoke()}>{copy.revoke}</Button>
          <Button variant='outline' className='min-h-11' disabled={revoking} onClick={() => setConfirm(false)}>{copy.cancel}</Button>
        </div>
      </div> : <Button variant='outline' className='min-h-11 max-w-full whitespace-normal' onClick={() => setConfirm(true)}>{copy.revoke}</Button>}
    </div>}
    {revokeError && <p role='alert' className='text-sm'>{copy.revokeError}</p>}
  </li>;
}
function RequestReceipt({ receipt, source, available, copy, formatDate }: {
  receipt: DiscoveryRequestReceipt; source?: PublicSource; available: boolean; copy: Copy; formatDate: (value: string) => string;
}) {
  const expired = useExpired(source?.expires_at);
  const receiptExpired = useExpired(receipt.expires_at);
  const current = available && Boolean(source?.authorization_id) && !expired && !receiptExpired
    && source?.verification.verified_scope_or_feature === 'VERIFIED'
    && !['REVOKED', 'AUTHORIZATION_REQUIRED', 'APP_REVIEW_REQUIRED'].includes(source.status);
  const measured = receipt.status === 'completed' && current;
  const selection = current ? receipt.selection : null;
  const description = !selection ? copy.unknown : 'hashtag' in selection ? `#${selection.hashtag}`
    : 'query' in selection ? `${selection.query} · ${selection.search_type === 'TOP' ? copy.top : copy.recent}`
    : selection.reviewed_page_id;
  return <li className='min-w-0 space-y-1 break-words rounded-xl border p-3 text-sm'>
    <h4 className='font-medium'>{copy.providers[receipt.provider]} · {copy.receiptStatuses[receipt.status]}</h4>
    {receipt.status === 'queued' && <p role='status'>{copy.queued}</p>}
    <p>{copy.selection}: {description}</p>
    <p>{copy.sample}: {measured && receipt.sample_size !== null ? receipt.sample_size : copy.unknown}</p>
    <p>{copy.range}: {measured && receipt.earliest_source_at && receipt.latest_source_at
      ? `${formatDate(receipt.earliest_source_at)} – ${formatDate(receipt.latest_source_at)}` : copy.unknown}</p>
    <p>{copy.retrieved}: {measured && receipt.retrieved_at ? formatDate(receipt.retrieved_at) : copy.unknown}</p>
    <p>{copy.created}: {formatDate(receipt.created_at)}</p>
    <p>{copy.completeness}: {copy.completenessStates[measured ? receipt.completeness : 'unknown']}</p>
    <p className='text-muted-foreground'>{copy.coverage[receipt.provider]}</p>
  </li>;
}
function WorkspacePublicSources() {
  const { locale, timeZone } = usePreferences();
  const copy = publicSourceCopy(locale);
  const formatDate = (value: string) => new Intl.DateTimeFormat(locale, { timeZone, dateStyle: 'medium', timeStyle: 'short' }).format(new Date(value));
  const sources = useTrendQuery(['public-sources'], (api, w, signal) => api.publicSources(w, signal));
  const requests = useTrendQuery(['discovery-requests'], (api, w, signal) => api.discoveryRequests(w, signal));
  const [submitted, setSubmitted] = useState<DiscoveryRequestReceipt | null>(null);
  const storedReceipts = requests.data?.data.requests ?? [];
  const receipts = submitted && !storedReceipts.some(receipt => receipt.request_id === submitted.request_id)
    ? [submitted, ...storedReceipts] : storedReceipts;
  const refresh = () => { setSubmitted(null); void sources.refetch(); void requests.refetch(); };
  return <Surface as='section' className='mb-6 min-w-0 space-y-4 p-4' aria-label={copy.title}>
    <details>
      <summary className='rafii-focus min-h-11 cursor-pointer font-medium'>{copy.title}</summary>
      <p className='text-muted-foreground my-3 text-sm'>{copy.caveat}</p>
      {sources.isError ? <StateMessage kind='error' title={copy.loadError} action={<Button variant='outline' onClick={() => void sources.refetch()}>{copy.retry}</Button>} />
        : !sources.data ? <StateMessage kind='loading' title={copy.loading} />
        : sources.data.execution_state === 'unavailable' ? <StateMessage kind='offline' title={copy.unavailable} />
        : <>
          {sources.data.execution_state === 'partial' && <StateMessage kind='partial' title={copy.partial} />}
          {sources.data.execution_state === 'collecting' && <StateMessage kind='loading' title={copy.collecting} />}
          <ul className='grid gap-3 lg:grid-cols-3'>
            {sources.data.data.map(source => <SourceRow key={source.provider} source={source} copy={copy} formatDate={formatDate}
              option={requests.isError || requests.data?.execution_state === 'unavailable' ? undefined : requests.data?.data.options.find(option => option.provider === source.provider)}
              refresh={refresh} requested={receipt => { setSubmitted(receipt); void requests.refetch(); }} />)}
          </ul>
        </>}
      {requests.isError || requests.data?.execution_state === 'unavailable'
        ? <StateMessage kind='offline' title={copy.requestUnavailable} />
        : !requests.data && <StateMessage kind='loading' title={copy.requestLoading} />}
      {receipts.length > 0 && <div className='mt-4 space-y-2'>
        <h3 className='font-medium'>{copy.receipts}</h3>
        <ul className='grid gap-3 lg:grid-cols-3'>{receipts.map(receipt => <RequestReceipt key={receipt.request_id} receipt={receipt}
          available={!requests.isError && Boolean(requests.data) && requests.data?.execution_state !== 'unavailable'}
          source={sources.isError || sources.data?.execution_state === 'unavailable' ? undefined : sources.data?.data.find(source => source.provider === receipt.provider)} copy={copy} formatDate={formatDate} />)}</ul>
      </div>}
      <p className='text-muted-foreground mt-3 text-sm'>{copy.jev}</p>
    </details>
  </Surface>;
}
/** Workspace changes dispose local forms, receipts and all asynchronous callbacks. */
export function PublicSources() {
  const { w } = useTrendContext();
  return <WorkspacePublicSources key={w} />;
}
