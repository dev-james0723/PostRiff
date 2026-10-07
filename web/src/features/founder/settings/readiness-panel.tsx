'use client';

import { useQuery } from '@tanstack/react-query';
import { StateMessage } from '@/components/rafii';
import { founderFetch } from '@/lib/founder/api';
import type { Envelope } from '@/lib/founder/types';
import { useFounderScope } from '../customers/kit/api';
import { Panel } from '../customers/kit/page-frame';

type Readiness = {
  sourceSha: string | null;
  features: { id: string; name: string; state: string; blockers: string[]; nextAction: string }[];
  telemetry: { dataState: string; reason?: string | null };
};

export function ReadinessPanel() {
  const scope = useFounderScope();
  const query = useQuery({
    queryKey: ['founder', 'activation-readiness', scope.environment],
    enabled: scope.ready,
    queryFn: async ({ signal }) => (await founderFetch<Envelope<Readiness>>('/activation/readiness', { signal })).data
  });
  return (
    <Panel title='Activation readiness' description='Current server gates and remaining verification. Configuration alone does not prove delivery or activation.'>
      {query.isPending ? <p className='text-muted-foreground text-sm'>Loading readiness…</p> : query.isError ? (
        <StateMessage kind='error' layout='inline' title='Readiness unavailable' description='The server gates could not be read. Retry when the Founder connection is available.' />
      ) : query.data ? (
        <div className='flex flex-col gap-3'>
          <p className='text-muted-foreground text-sm'>Telemetry: {query.data.telemetry.dataState}{query.data.telemetry.reason ? ` · ${query.data.telemetry.reason.replaceAll('_', ' ')}` : ''}</p>
          {query.data.features.map((feature) => (
            <details key={feature.id} className='rafii-quiet rounded-lg p-3'>
              <summary className='cursor-pointer text-sm'>{feature.name} · {feature.state.replaceAll('_', ' ')}</summary>
              <p className='text-muted-foreground mt-2 text-sm'>{feature.nextAction}</p>
              {feature.blockers.length > 0 && <ul className='text-muted-foreground mt-2 list-inside list-disc text-xs'>{feature.blockers.map((blocker) => <li key={blocker}>{blocker.replaceAll('_', ' ')}</li>)}</ul>}
            </details>
          ))}
          {query.data.sourceSha && <p className='text-muted-foreground break-all font-mono text-xs'>Source: {query.data.sourceSha}</p>}
        </div>
      ) : null}
    </Panel>
  );
}
