'use client';

import { useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import type { FeatureReadiness } from '@/lib/feature-readiness';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useWorkspaceAccess } from '@/lib/auth/access';
import { MEASUREMENT_REASON_COPY } from './readiness-copy';

/**
 * Owner control for native post readings (growth_measurement enrollment). Turning readings on is free, uses no AI and
 * never posts; turning them off stops new readings and keeps the ones already taken. Everyone else is pointed to the
 * owner. The server re-checks the owner role, the interactive session and the self-serve switch on every change.
 */
export function MeasurementEnrollment({ readiness, onChange }: { readiness: FeatureReadiness; onChange: () => void }) {
  const access = useWorkspaceAccess();
  const { api, workspaceId } = useWorkspaceApi();
  const owner = access.role === 'owner';
  const collecting = readiness.state !== 'feature_disabled';
  const query = useQuery({ queryKey: ['growth-measurement', workspaceId], queryFn: () => api.growthMeasurementEnrollment(workspaceId), enabled: owner && collecting, retry: false });
  const [confirmed, setConfirmed] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  if (!collecting) return null;
  if (!owner)
    return readiness.reasonCodes.includes('measurement_enrollment_required')
      ? <p className='growth-footnote growth-measurement-ask' id='growth-measurement'>Post readings are off for this workspace. Ask the workspace owner to turn them on.</p>
      : null;
  if (query.isError) return <p role='alert' className='growth-error' id='growth-measurement'>Post reading settings could not be loaded. <Button variant='quiet' onClick={() => void query.refetch()}>Try again</Button></p>;
  const e = query.data;
  if (!e) return null;
  // A workspace on the reviewed early-access list stays admitted either way, so it gets no stop control here.
  const enrolled = e.status === 'active' && e.reason !== 'reviewed_cohort';
  async function change(on: boolean) {
    setBusy(true); setError('');
    try {
      await (on ? api.enrollGrowthMeasurement(workspaceId) : api.leaveGrowthMeasurement(workspaceId));
      setConfirmed(false);
      await query.refetch();
      onChange();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Post readings could not be changed.');
    } finally { setBusy(false); }
  }
  return <section className='growth-measurement' id='growth-measurement' aria-labelledby='growth-measurement-title' data-admitted={e.admitted}>
    <div>
      <p className='growth-kicker'>Post readings</p>
      <h3 id='growth-measurement-title'>{e.admitted ? 'Post readings are on.' : 'Post readings are off.'}</h3>
      <p>{MEASUREMENT_REASON_COPY[e.reason] ?? (e.admitted ? MEASUREMENT_REASON_COPY.already_enrolled : MEASUREMENT_REASON_COPY.workspace_not_eligible)}</p>
    </div>
    {enrolled ? <div className='growth-measurement-actions'>
      <label className='growth-check'><input type='checkbox' aria-label='Stop new post readings for this workspace. Readings already taken stay.' checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Stop new post readings for this workspace. Readings already taken stay.</label>
      <Button variant='quiet' disabled={!confirmed || busy} onClick={() => void change(false)}>{busy ? 'Stopping…' : 'Stop post readings'}</Button>
    </div> : e.eligible && !e.admitted ? <div className='growth-measurement-actions'>
      <label className='growth-check'><input type='checkbox' aria-label='Read my own posts’ native metrics at publish, one hour, one day and one week. No AI, no cost, nothing is posted.' checked={confirmed} onChange={(event) => setConfirmed(event.target.checked)} />Read my own posts’ native metrics at publish, one hour, one day and one week. No AI, no cost, nothing is posted.</label>
      <Button className='growth-primary' disabled={!confirmed || busy} onClick={() => void change(true)}>{busy ? 'Turning on…' : 'Turn on post readings'}</Button>
    </div> : null}
    {error && <p role='alert' className='growth-error'>{error}</p>}
  </section>;
}
