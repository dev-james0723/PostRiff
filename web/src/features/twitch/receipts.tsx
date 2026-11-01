'use client';

import { Button } from '@/components/ui/button';
import { Surface } from '@/components/rafii/surface';
import { actionStateLabel, canCancelAction, canPauseAction, canReconcileAction, safeDisplay, timestampMillis } from './contracts';
import type { TwitchAction, TwitchReadResult } from './types';

export function displayTime(value: string | number | null | undefined): string {
  const millis = timestampMillis(value);
  return millis === null ? 'Not provided' : new Date(millis).toLocaleString(undefined, { dateStyle: 'medium', timeStyle: 'short' });
}

/** Render server data as text. Event/chat content is never markup, scripts or an instruction to the agent. */
export function DataReceipt({ data, label = 'Twitch response' }: { data: unknown; label?: string }) {
  return (
    <details className='min-w-0 rounded-lg border p-3' data-private>
      <summary className='rafii-focus cursor-pointer rounded-sm text-sm'>{label}</summary>
      <pre className='mt-3 max-h-96 overflow-auto whitespace-pre-wrap break-words text-xs leading-relaxed'>{JSON.stringify(safeDisplay(data), null, 2)}</pre>
    </details>
  );
}

const READ_LABELS: Record<string, string> = {
  id: 'ID', user_id: 'User ID', broadcaster_id: 'Channel ID', user_name: 'User',
  broadcaster_name: 'Channel', creator_name: 'Creator', game_name: 'Category', language: 'Language',
  viewer_count: 'Viewers at this snapshot', view_count: 'Views reported by Twitch',
  created_at: 'Created', started_at: 'Started', start_time: 'Starts', end_time: 'Ends',
  duration: 'Duration', status: 'Status', cost: 'Channel Points cost', message: 'Message',
  is_live: 'Live', total: 'Total returned by Twitch', points: 'Subscription points', votes: 'Votes',
  bits: 'Bits', is_enabled: 'Enabled', description: 'Description', prompt: 'Viewer prompt',
  next_ad_at: 'Next ad', length: 'Length', is_active: 'Active', title: 'Title', type: 'Type',
  message_id: 'Message ID', clip_id: 'Clip ID', accountType: 'Twitch account type',
  isLive: 'Live at verification'
};

function scalar(value: unknown): string | null {
  if (typeof value === 'boolean') return value ? 'Yes' : 'No';
  if (typeof value === 'string' || typeof value === 'number') return String(value);
  return null;
}

/** Present only observed fields. Missing analytics remain missing, including zero-versus-unknown counts. */
export function NativeReadResult({ result }: { result: TwitchReadResult }) {
  const value = safeDisplay(result.data);
  const object = value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : null;
  const rows = Array.isArray(value) ? value : object && Array.isArray(object.segments) ? object.segments : object ? [object] : [];
  const provenance = result.provenance && typeof result.provenance === 'object' ? result.provenance as Record<string, unknown> : undefined;
  const observed = result.observedAt ?? (typeof provenance?.observedAt === 'string' ? provenance.observedAt : undefined);
  const source = result.source ?? (typeof provenance?.source === 'string' ? provenance.source : undefined);

  return (
    <div className='grid gap-3'>
      <p className='text-muted-foreground text-xs'>{observed ? `Observed ${displayTime(observed)}` : 'Response timestamp not provided'}{source ? ` · ${source}` : ''}</p>
      {typeof result.total === 'number' && <p className='text-sm'>Total returned by Twitch: <strong>{result.total.toLocaleString()}</strong></p>}
      {rows.length === 0 ? <p className='text-muted-foreground text-sm'>Twitch returned no matching items in this response.</p> : <ul className='grid max-h-[34rem] gap-3 overflow-auto' data-private>
        {rows.map((row, index) => {
          if (!row || typeof row !== 'object' || Array.isArray(row)) return <li key={index} className='rounded-lg border p-3 text-sm'>{scalar(row) ?? 'Structured item'}</li>;
          const record = row as Record<string, unknown>;
          const title = scalar(record.title ?? record.user_name ?? record.broadcaster_name ?? record.name) || `Result ${index + 1}`;
          const entries = Object.keys(READ_LABELS).filter((key) => key in record && scalar(record[key]) !== null && (key !== 'title' || record.title !== title));
          return <li key={typeof record.id === 'string' ? `${record.id}:${index}` : index} className='grid gap-3 rounded-lg border p-4'>
            <h4 className='text-sm font-medium'>{title}</h4>
            <dl className='grid gap-3 sm:grid-cols-2'>{entries.map((key) => <div key={key} className='min-w-0'><dt className='text-muted-foreground text-xs'>{READ_LABELS[key]}</dt><dd className='mt-1 whitespace-pre-wrap break-words text-sm'>{scalar(record[key])}</dd></div>)}</dl>
            {entries.length === 0 && <DataReceipt data={record} label='Result fields' />}
          </li>;
        })}
      </ul>}
      {provenance?.creatorDashboard === false && <p className='text-muted-foreground text-xs'>This is an official API observation. It does not include Creator Dashboard revenue, watch time, unique viewers or retention.</p>}
      {result.pagination !== undefined && <DataReceipt data={result.pagination} label='Next-page cursor' />}
      <DataReceipt data={result} label='Complete response & provenance' />
    </div>
  );
}

export function ActionReceipts({ actions, busy, canControl, onControl, onReview, onReconcile }: {
  actions: TwitchAction[];
  busy: boolean;
  canControl: (action: TwitchAction) => boolean;
  onControl: (id: string, command: 'pause' | 'cancel') => Promise<void>;
  onReview: (action: TwitchAction) => void;
  onReconcile?: (id: string) => Promise<void>;
}) {
  return (
    <Surface as='section' material='quiet' className='grid gap-4' aria-labelledby='twitch-actions-heading'>
      <div className='grid gap-1'>
        <h2 id='twitch-actions-heading' className='font-medium'>Action history</h2>
        <p className='text-muted-foreground text-sm'>Approval places an action in Rafii’s queue. The status below records what happened next.</p>
      </div>
      {actions.length === 0 ? <p className='text-muted-foreground text-sm'>No Twitch actions have been prepared for this connection.</p> : (
        <ul className='grid gap-3'>
          {actions.map((action) => (
            <li key={action.id} className='grid gap-3 rounded-lg border p-4'>
              <div className='flex flex-wrap items-start justify-between gap-2'>
                <p className='text-sm font-medium'>{action.action.replace(/^twitch\./, '').replaceAll('.', ' · ')}</p>
                <span className='rounded-full border px-2.5 py-1 text-xs'>{actionStateLabel(action.state)}</span>
              </div>
              <p className='text-muted-foreground text-xs'>{action.scheduled === true && action.executeAt ? `Scheduled for ${displayTime(action.executeAt)}` : 'Execute after approval'}{action.createdAt ? ` · Prepared ${displayTime(action.createdAt)}` : ''}</p>
              {action.error && <p role='alert' className='text-destructive text-sm'>{action.error}</p>}
              {['unknown', 'outcome_unknown', 'ambiguous', 'reconciling'].includes(action.state) && <p className='text-muted-foreground text-sm'>Twitch may have received this action. Wait for reconciliation or inspect the official result before preparing another copy.</p>}
              {action.state === 'accepted' && <p className='text-muted-foreground text-sm'>Twitch accepted the request and is still processing the resource. Its completed result has not been verified. Read the resource to check before creating another copy.</p>}
              {action.state === 'partial' && <p className='text-muted-foreground text-sm'>Twitch confirmed only some requested items. Check the provider receipt for the confirmed and remaining items before preparing any further action.</p>}
              <div className='flex flex-wrap gap-2'>
                {action.state === 'draft' && <Button type='button' size='sm' variant='outline' disabled={busy} onClick={() => onReview(action)}>Review this action</Button>}
                {canControl(action) && canPauseAction(action.state) && <Button type='button' size='sm' variant='outline' disabled={busy} onClick={() => void onControl(action.id, 'pause')}>Pause</Button>}
                {canControl(action) && canCancelAction(action.state) && <Button type='button' size='sm' variant='ghost' disabled={busy} onClick={() => void onControl(action.id, 'cancel')}>Cancel</Button>}
                {onReconcile && canReconcileAction(action) && <Button type='button' size='sm' variant='outline' disabled={busy} onClick={() => void onReconcile(action.id)}>Check Twitch result</Button>}
              </div>
              {action.result !== undefined && action.result !== null && <DataReceipt data={action.result} label='Provider result' />}
              <details className='text-muted-foreground text-xs'>
                <summary className='rafii-focus cursor-pointer rounded-sm'>Receipt details</summary>
                <p className='mt-2 break-all'>Action ID: {action.id}</p>
                <p className='mt-1 break-all'>Approved payload SHA-256: {action.payloadHash}</p>
              </details>
            </li>
          ))}
        </ul>
      )}
    </Surface>
  );
}
