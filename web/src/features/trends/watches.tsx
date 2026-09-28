'use client';
import { useRef, useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { StateMessage, Surface } from '@/components/rafii';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { Trend, TrendWatch } from '@/lib/coworker/trend-types';
import { useTrendContext, useTrendQuery } from './hooks';
import { Disclosure } from './disclosure';
import { QueryContent, TrendError, fieldClass } from './present';
const watchReason = (threshold: TrendWatch['threshold']) =>
  threshold === 'stage_change' ? 'Trend pattern changes' : 'Available evidence changes';
export function WatchForm({ trend }: { trend: Trend }) {
  const { api, w, flags, enabled } = useTrendContext();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const client = useQueryClient();
  const [threshold, setThreshold] = useState<'stage_change' | 'coverage_change'>('stage_change');
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [saved, setSaved] = useState<TrendWatch | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const key = useRef({ fingerprint: '', key: '' });
  if (!flags.RAFII_TREND_NOTIFICATIONS_ENABLED)
    return <p className='text-sm'>Trend watches are not enabled.</p>;
  async function save() {
    if (!canEdit || !enabled || busy || !platforms.length) return;
    const fingerprint = JSON.stringify([w, trend.id, threshold, platforms]);
    if (key.current.fingerprint !== fingerprint)
      key.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError(null);
    try {
      const result = await api.watch(w, {
        trend_id: trend.id,
        platforms,
        threshold,
        notification_policy: 'in_app',
        idempotency_key: key.current.key
      });
      if (!result.data.active) throw new Error('Watch is not active.');
      setSaved(result.data);
      void client.invalidateQueries({ queryKey: ['trends', w, 'watches'] });
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Disclosure title='Watch this conversation' className='trend-watch'>
      {saved ? (
        <p role='status'>
          Watching · {saved.platforms.join(', ')} · {watchReason(saved.threshold)} · in-app only
        </p>
      ) : (
        <form
          className='space-y-3'
          onSubmit={(e) => {
            e.preventDefault();
            void save();
          }}
        >
          <label className='block'>
            Alert when
            <select
              className={fieldClass}
              value={threshold}
              onChange={(e) => setThreshold(e.target.value as typeof threshold)}
              disabled={!canEdit || busy}
            >
              <option value='stage_change'>The trend pattern changes</option>
              <option value='coverage_change'>The available evidence changes</option>
            </select>
          </label>
          <fieldset disabled={!canEdit || busy}>
            <legend>Platforms</legend>
            {trend.platform_states.map((s) => (
              <label key={s.platform} className='flex min-h-11 items-center gap-2'>
                <input
                  aria-label={s.platform}
                  type='checkbox'
                  checked={platforms.includes(s.platform)}
                  onChange={(e) =>
                    setPlatforms(
                      e.target.checked
                        ? [...platforms, s.platform]
                        : platforms.filter((p) => p !== s.platform)
                    )
                  }
                />
                {s.platform}
              </label>
            ))}
          </fieldset>
          <p>In-app notifications only. Email and push preferences remain separate.</p>
          <Button variant='glass' type='submit' disabled={!canEdit || busy || !platforms.length}>
            {busy ? 'Saving…' : 'Save watch'}
          </Button>
        </form>
      )}
      {error !== null && <TrendError error={error} />}
    </Disclosure>
  );
}
export function Watchlist() {
  const { api, w } = useTrendContext();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const query = useTrendQuery(['watches'], (a, w, s) => a.watches(w, s));
  const [error, setError] = useState<unknown>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const keys = useRef(new Map<string, string>());
  async function disable(watch: TrendWatch) {
    if (busy || !canEdit) return;
    const identity = `${watch.id}:${watch.revision}`;
    if (!keys.current.has(identity)) keys.current.set(identity, crypto.randomUUID());
    setBusy(watch.id);
    setError(null);
    try {
      const result = await api.disableWatch(
        w,
        watch.id,
        watch.revision,
        keys.current.get(identity)!
      );
      if (result.data.active) throw new Error('Watch is still active.');
      await query.refetch();
    } catch (e) {
      setError(e);
    } finally {
      setBusy(null);
    }
  }
  return (
    <>
      <QueryContent query={query}>
        {(items) =>
          items.length ? (
            <div className='space-y-3'>
              {items.map((watch) => (
                <Surface key={watch.id} className='trend-watch-row space-y-3'>
                  <h2 className='font-medium'>Saved conversation</h2>
                  <Disclosure title='Conversation reference'>
                    <p>{watch.trend_id}</p>
                  </Disclosure>
                  <p>
                    {watch.active ? 'Watching' : 'Disabled'} · {watch.platforms.join(', ')} ·{' '}
                    {watchReason(watch.threshold)} · in-app
                  </p>
                  <Button
                    variant='glass'
                    disabled={!canEdit || !watch.active || busy !== null}
                    onClick={() => void disable(watch)}
                  >
                    {busy === watch.id ? 'Disabling…' : 'Disable watch'}
                  </Button>
                </Surface>
              ))}
            </div>
          ) : (
            <StateMessage
              kind='empty'
              title='No saved trend watches'
              description='Choose a conversation, select its platforms, and decide what changes you want to hear about.'
            />
          )
        }
      </QueryContent>
      {error !== null && <TrendError error={error} />}
    </>
  );
}
