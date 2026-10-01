'use client';

import { useState } from 'react';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { SelectField } from '@/features/workspace/rafii-parts';
import { useFounderSession } from '@/features/founder/shell/founder-session';
import { founderKeys } from '@/lib/founder/api';
import { describeFounderError } from '@/lib/founder/errors';
import { DEMO_SCENARIOS } from '@/lib/founder/types';
import { scenarioKey } from './format';

/**
 * One line while Demo data is on (CONTRACTS §6): what Demo means, the scenario select and Reset. Both changes are
 * Demo actions carrying the revision the person saw; a failed save keeps its request id for an explicit retry.
 */
export function DemoBanner() {
  const { api, mode, environment } = useFounderSession();
  const client = useQueryClient();
  const [error, setError] = useState<string | null>(null);
  const envKey = environment ?? 'unknown';
  const workspace = useQuery({
    queryKey: founderKeys.workspace('demo', envKey),
    queryFn: ({ signal }) => api.workspace('demo', { signal }),
    enabled: mode === 'demo',
    retry: false,
    staleTime: 30_000
  });
  const data = workspace.data?.data;
  const mutation = useMutation({
    mutationFn: ({ action, targetId, value }: { action: string; targetId: string; value: string }) => api.demoAction(action, targetId, value, data?.revision ?? 0),
    onMutate: () => setError(null),
    onError: (failure) => setError(describeFounderError(failure)),
    onSuccess: () => void client.invalidateQueries({ queryKey: ['founder', 'demo', envKey] })
  });
  if (mode !== 'demo') return null;
  const busy = mutation.isPending || workspace.isPending;
  return (
    <div role='region' aria-label='Demo data' className='rafii-quiet mx-4 mt-3 flex flex-wrap items-center gap-x-3 gap-y-2 rounded-[var(--rafii-radius-control)] px-3 py-2 text-xs md:mx-8 lg:mx-10'>
      <span className='bg-foreground text-background inline-flex h-5 items-center rounded-full px-2 text-[11px] font-semibold tracking-wide uppercase'>Demo</span>
      <span className='text-muted-foreground min-w-0 flex-1'>Fictional dataset. No real emails, calls or account changes.</span>
      <div className='flex items-center gap-2'>
        <SelectField
          label='Scenario'
          hideLabel
          value={scenarioKey(data)}
          disabled={busy || !data}
          onChange={(event) => mutation.mutate({ action: 'set_scenario', targetId: 'scenario', value: event.target.value })}
          className='w-44'
          selectClassName='h-8 rounded-full py-0 pr-8 text-xs md:text-xs'
        >
          {DEMO_SCENARIOS.map(([id, label]) => (
            <option key={id} value={id}>
              {label}
            </option>
          ))}
        </SelectField>
        <Button type='button' variant='quiet' size='sm' disabled={busy || !data} onClick={() => mutation.mutate({ action: 'reset', targetId: 'all', value: '' })} className='gap-1'>
          <Icons.refresh className='size-3.5' aria-hidden /> Reset
        </Button>
      </div>
      {workspace.isError && (
        <span role='alert' className='text-destructive basis-full'>
          {describeFounderError(workspace.error)}
        </span>
      )}
      {error && (
        <span role='alert' className='text-destructive flex basis-full items-center gap-2'>
          {error}
          <Button type='button' variant='quiet' size='xs' onClick={() => mutation.mutate(mutation.variables as { action: string; targetId: string; value: string })} disabled={!mutation.variables}>
            Retry the same action
          </Button>
        </span>
      )}
    </div>
  );
}
