'use client';
import { useRef, useState } from 'react';
import Link from 'next/link';
import { Button } from '@/components/ui/button';
import { Surface, StateMessage } from '@/components/rafii';
import { useSnapshot } from '@/lib/api/hooks';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import type { TrendOpportunity } from '@/lib/coworker/trend-types';
import { useExpired, useTrendContext } from './hooks';
import { date, fieldClass, TrendError } from './present';
import { Disclosure } from './disclosure';
import { FitDetails } from './fit-details';

export function OpportunityCard({ opportunity: op }: { opportunity: TrendOpportunity }) {
  const { api, w, enabled } = useTrendContext();
  const snapshot = useSnapshot();
  const canEdit = checkAccess(useWorkspaceAccess(), { permission: 'edit' });
  const expired = useExpired(op.expires_at);
  const [angle, setAngle] = useState(op.angles[0]?.id ?? '');
  const [channel, setChannel] = useState('');
  const [goal, setGoal] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const [source, setSource] = useState(op.source_id);
  const request = useRef({ fingerprint: '', key: '' });
  const channels = (snapshot.data?.state.phase2?.channels ?? []).filter(
    (c) =>
      !c.revoked && op.platform_targets.some((p) => p.toLowerCase() === c.platform.toLowerCase())
  );
  if (
    expired ||
    op.verification_state !== 'verified' ||
    ['expired', 'blocked', 'dismissed'].includes(op.state)
  )
    return (
      <StateMessage
        kind='stale'
        title='Opportunity needs a fresh evidence check'
        description='Its receipt or contribution is no longer current.'
      />
    );
  async function accept() {
    if (!enabled || !canEdit || busy || !channel || !goal.trim() || !angle) return;
    const fingerprint = JSON.stringify([w, op.id, op.revision, angle, channel, goal.trim()]);
    if (request.current.fingerprint !== fingerprint)
      request.current = { fingerprint, key: crypto.randomUUID() };
    setBusy(true);
    setError(null);
    try {
      const result = await api.acceptOpportunity(w, op.id, {
        revision: op.revision,
        angle_id: angle,
        channel_id: channel,
        goal: goal.trim(),
        idempotency_key: request.current.key
      });
      const expected = `/app/ideas?source=${encodeURIComponent(result.data.source_id)}`;
      if (!result.data.verified || result.data.href !== expected)
        throw new Error('Source creation could not be verified.');
      // useSnapshot owns the canonical workspace query; refresh before the Ideas handoff.
      await snapshot.refetch({ throwOnError: true });
      setSource(result.data.source_id);
    } catch (e) {
      setError(e);
    } finally {
      setBusy(false);
    }
  }
  return (
    <Surface
      as='section'
      material='canvas'
      padding='none'
      className='trend-opportunity space-y-3'
      aria-label='Original contribution'
    >
      <p className='text-muted-foreground text-xs font-medium'>Try this angle</p>
      <h3 className='text-lg font-semibold leading-snug'>{op.title}</h3>
      <p>{op.contribution}</p>
      <p className='text-muted-foreground text-sm'>Keep in mind: {op.uncertainty}</p>
      <p className='text-sm'>Check again at {date(op.expires_at)}</p>
      {op.workspace_fit.sufficient ? (
        <>
          {op.angles.map((a) => (
            <Disclosure key={a.id} title={a.title}>
              <p>{a.contribution}</p>
              <p>Format: {a.format_reason}</p>
              <p>
                Facts you need:{' '}
                {a.factual_requirements.join('; ') || 'No additional facts specified'}
              </p>
            </Disclosure>
          ))}
          {source ? (
            <p role='status'>
              Saved to Ideas.{' '}
              <Link
                className='rafii-focus underline'
                href={`/app/ideas?source=${encodeURIComponent(source)}`}
              >
                Review source and create original post
              </Link>
            </p>
          ) : (
            <Disclosure className='trend-action-disclosure' title='Develop this idea'>
              <form
                className='space-y-3'
                onSubmit={(e) => {
                  e.preventDefault();
                  void accept();
                }}
              >
                <label className='block'>
                  Original angle
                  <select
                    className={fieldClass}
                    value={angle}
                    onChange={(e) => setAngle(e.target.value)}
                    disabled={!canEdit || busy}
                  >
                    {op.angles.map((a) => (
                      <option key={a.id} value={a.id}>
                        {a.title}
                      </option>
                    ))}
                  </select>
                </label>
                <label className='block'>
                  Destination account
                  <select
                    className={fieldClass}
                    value={channel}
                    onChange={(e) => setChannel(e.target.value)}
                    disabled={!canEdit || busy}
                  >
                    <option value=''>Choose a connected account</option>
                    {channels.map((c) => (
                      <option key={c.id} value={c.id}>
                        {c.platform} · {c.account}
                      </option>
                    ))}
                  </select>
                </label>
                <label className='block'>
                  Your goal
                  <input
                    aria-label='Your goal'
                    className={fieldClass}
                    value={goal}
                    maxLength={1000}
                    onChange={(e) => setGoal(e.target.value)}
                    disabled={!canEdit || busy}
                  />
                </label>
                <p className='text-sm'>
                  Save this angle as a source in Ideas, then review facts and choose whether to
                  draft.
                </p>
                <Button
                  variant='glass'
                  type='submit'
                  disabled={!canEdit || busy || !channel || !angle || !goal.trim()}
                >
                  {busy ? 'Saving…' : 'Save to Ideas'}
                </Button>
                {!channels.length && (
                  <p className='text-sm'>A connected, permitted destination is required.</p>
                )}
              </form>
            </Disclosure>
          )}
        </>
      ) : (
        <p>Content angles are unavailable until workspace fit has enough support.</p>
      )}
      <FitDetails fit={op.workspace_fit} />
      {error !== null && <TrendError error={error} />}
    </Surface>
  );
}
