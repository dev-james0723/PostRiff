'use client';

import { useEffect, useId, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useAuth } from '@/lib/auth/session';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { youtubePolicyAcceptanceBody } from '@/lib/youtube/policy-acceptance';

export function YouTubePolicyAcceptance({ force = false, onAvailabilityChange }: {
  force?: boolean;
  onAvailabilityChange?: (allowed: boolean) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const { user } = useAuth();
  const client = useQueryClient();
  const checkboxId = useId();
  const queryKey = ['youtube-policy', workspaceId, user?.id];
  const status = useQuery({ queryKey, queryFn: () => api.youtubePolicy(workspaceId), retry: false, staleTime: 0 });
  const [choice, setChoice] = useState({ policyId: '', confirmed: false });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const required = force || status.data?.requiredForConnection === true;
  const allowed = Boolean(status.data && (!required || status.data.ready && status.data.accepted
    && status.data.receipt?.userId === user?.id && status.data.receipt?.workspaceId === workspaceId));
  const policy = status.data?.policy;
  const checked = Boolean(policy && choice.policyId === policy.id && choice.confirmed);
  useEffect(() => { onAvailabilityChange?.(allowed); }, [allowed, onAvailabilityChange]);

  async function accept() {
    if (!status.data || !policy) return;
    setBusy(true);
    setError('');
    try {
      const body = youtubePolicyAcceptanceBody(status.data, choice.policyId, checked);
      const receipt = await api.acceptYouTubePolicy(workspaceId, body);
      client.setQueryData(queryKey, receipt);
      await client.invalidateQueries({ queryKey: ['youtube', workspaceId] });
    } catch (failure) {
      setError(failure instanceof Error ? failure.message : 'The policies could not be accepted.');
      setChoice({ policyId: '', confirmed: false });
      void status.refetch();
    } finally { setBusy(false); }
  }

  if (status.data && !required) return null;
  return (
    <section aria-labelledby={`${checkboxId}-heading`} className='rafii-quiet grid gap-3 rounded-xl p-4 text-sm'>
      <h2 id={`${checkboxId}-heading`} className='font-medium'>YouTube Privacy Policy and Terms</h2>
      {status.isPending ? <p>Loading published policies…</p> : !status.data?.ready || !policy ? (
        <p role='status'>The published policies are not available yet. YouTube access is unavailable.</p>
      ) : (
        <>
          <p>
            <a className='underline' href={policy.privacy.url} target='_blank' rel='noreferrer'>Privacy Policy ({policy.privacy.revision})</a>
            {' and '}
            <a className='underline' href={policy.terms.url} target='_blank' rel='noreferrer'>Terms ({policy.terms.revision})</a>
          </p>
          {allowed && status.data.receipt ? (
            <p role='status'>You agreed for this workspace on {new Date(status.data.receipt.acceptedAt * 1000).toLocaleString()}.</p>
          ) : (
            <>
              <label htmlFor={checkboxId} className='flex items-start gap-2'>
                <input id={checkboxId} type='checkbox' checked={checked} disabled={busy}
                  aria-label='I agree to these Privacy Policy and Terms revisions for my YouTube use in this workspace.'
                  onChange={(event) => setChoice({ policyId: policy.id, confirmed: event.target.checked })} />
                <span>I agree to these Privacy Policy and Terms revisions for my YouTube use in this workspace.</span>
              </label>
              <Button className='w-fit' disabled={!checked || busy} onClick={() => void accept()}>
                {busy ? 'Recording agreement…' : 'Agree to YouTube policies'}
              </Button>
            </>
          )}
        </>
      )}
      {error && <p role='alert'>{error}</p>}
      {status.isError && <Button variant='glass' className='w-fit' onClick={() => void status.refetch()}>Retry</Button>}
    </section>
  );
}
