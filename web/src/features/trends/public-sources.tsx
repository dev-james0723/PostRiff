'use client';
import { useState } from 'react';
import { Button } from '@/components/ui/button';
import { Surface } from '@/components/rafii';
import { useExpired, useTrendContext, useTrendQuery } from './hooks';
import { QueryContent, date } from './present';
import type { z } from 'zod';
import type { publicSourceSchema } from './public-source-types';

type Source = z.infer<typeof publicSourceSchema>;
const labels: Record<Source['status'], string> = {
  APP_REVIEW_REQUIRED: 'Public access approval required',
  AUTHORIZATION_REQUIRED: 'Reconnect or verify public access',
  UNVERIFIED: 'Awaiting a verified public reading',
  LIVE: 'Live within this source scope',
  STALE: 'Last reading is out of date',
  PAUSED: 'Collection paused',
  REVOKED: 'Public access revoked'
};
function SourceRow({ source, refresh }: { source: Source; refresh: () => void }) {
  const { api, w } = useTrendContext();
  const deadline = source.expires_at && source.latest_successful_read
    ? new Date(Math.min(Date.parse(source.expires_at), Date.parse(source.latest_successful_read) + 900_000)).toISOString()
    : source.expires_at;
  const expired = useExpired(deadline);
  const [confirm, setConfirm] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const status = source.status === 'LIVE' && expired ? 'AUTHORIZATION_REQUIRED' : source.status;
  const revoke = async () => {
    setBusy(true); setError('');
    try { await api.revokePublicSource(w, source.authorization_id!); setConfirm(false); refresh(); }
    catch { setError('Access could not be revoked. A workspace member with connection management permission can try again.'); }
    finally { setBusy(false); }
  };
  return <li className='min-w-0 space-y-2 rounded-xl border p-4'>
    <h3 className='font-medium'>{source.label}</h3>
    <p className='text-sm' role='status'>{labels[status]}</p>
    <p className='text-muted-foreground text-sm'>{source.latest_successful_read
      ? `Last verified reading: ${date(source.latest_successful_read)}` : 'No verified third-party public reading.'}</p>
    <p className='text-muted-foreground text-sm'>{source.coverage}</p>
    {source.authorization_id && source.status !== 'REVOKED' && <div>
      {confirm ? <div className='space-y-2'>
        <p className='text-sm'>Stop public collection and withdraw results derived from this grant?</p>
        <div className='flex flex-wrap gap-2'>
          <Button variant='destructive' disabled={busy} onClick={() => void revoke()}>Revoke public access</Button>
          <Button variant='outline' disabled={busy} onClick={() => setConfirm(false)}>Cancel</Button>
        </div>
      </div> : <Button variant='outline' onClick={() => setConfirm(true)}>Revoke public access</Button>}
    </div>}
    {error && <p role='alert' className='text-sm'>{error}</p>}
  </li>;
}
export function PublicSources() {
  const sources = useTrendQuery(['public-sources'], (api, w, signal) => api.publicSources(w, signal));
  return <Surface as='section' className='mb-6 space-y-4 p-4' aria-label='Public discovery sources'>
    <details>
      <summary className='rafii-focus min-h-11 cursor-pointer font-medium'>Public discovery sources</summary>
      <p className='text-muted-foreground my-3 text-sm'>Public discovery needs its own Meta approval and permission verification. Connecting your account for publishing or analytics does not grant public discovery access.</p>
      <QueryContent query={sources}>{(data) => <ul className='grid gap-3 lg:grid-cols-3'>
        {data.map(source => <SourceRow key={source.provider} source={source} refresh={() => void sources.refetch()} />)}
      </ul>}</QueryContent>
      <p className='text-muted-foreground mt-3 text-sm'>Trend measurements use the available observations. Optional JEV interpretation requires current source rights, workspace consent and an approved model budget.</p>
    </details>
  </Surface>;
}
