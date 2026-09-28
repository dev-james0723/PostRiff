'use client';
import { useEffect, useRef, useState } from 'react';
import { useQuery, useQueryClient } from '@tanstack/react-query';
import { Button } from '@/components/ui/button';
import { useTrendContext } from './hooks';
import { TrendError } from './present';

const pending = new Set(['queued', 'leased', 'running', 'retry_wait']);
const messages: Record<string, string> = {
  disabled: 'Angle generation is not enabled for this workspace. Your saved evidence is unchanged.',
  needs_facts: 'Add and approve your own factual material in Ideas before requesting original angles.',
  needs_review: 'The current evidence, sharing permissions or writer policy needs review before angles can be generated.',
  budget_unavailable: 'No approved generation budget is available. No model call was started.',
  queue_full: 'Two generation requests are already in progress. Try again after they finish.',
  cached: 'The existing result is still current. Refreshing the available angles.',
  succeeded: 'The request finished. Refreshing the available angles; the writer may return fewer than three when evidence is insufficient.',
  failed_terminal: 'The request could not produce current, supported angles. Review the evidence before starting another request.',
  cancelled: 'The request was cancelled. No new angles were accepted.',
  outcome_unknown: 'The writer outcome is uncertain. This request will not be retried automatically.'
};

/** Explicit enqueue only: reads poll a stored job; they never dispatch a writer. */
export function AngleGeneration({ id, revision, allowed }: { id: string; revision: number; allowed: boolean }) {
  const { api, w } = useTrendContext();
  const client = useQueryClient();
  const key = useRef(crypto.randomUUID());
  const [request, setRequest] = useState<{ status: string; job_id?: string } | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<unknown>(null);
  const job = useQuery({
    queryKey: ['trends', w, 'generation-job', request?.job_id],
    queryFn: ({ signal }) => api.generationStatus(w, request!.job_id!, signal),
    enabled: allowed && Boolean(request?.job_id),
    retry: false,
    refetchInterval: (query) => !query.state.error && pending.has(query.state.data?.data.status ?? request?.status ?? '') ? 3000 : false
  });
  const status = job.data?.data.status ?? request?.status;
  useEffect(() => {
    if (status === 'succeeded' || status === 'cached')
      void client.invalidateQueries({ queryKey: ['trends', w, 'opportunities'] });
  }, [status, client, w]);
  async function generate() {
    if (!allowed || busy || (status && pending.has(status))) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.generateAngles(w, id, revision, key.current);
      setRequest(result.data);
    } catch (e) { setError(e); }
    finally { setBusy(false); }
  }
  return <div className='space-y-2'>
    <Button variant='quiet' type='button' disabled={!allowed || busy || Boolean(status && pending.has(status))} onClick={() => void generate()}>
      {busy ? 'Checking request…' : status && pending.has(status) ? 'Preparing angles…' : 'Give me 3 original angles'}
    </Button>
    <p className='text-muted-foreground text-sm'>Requests up to three options from the approved writer within the workspace’s existing cost limit. Requires current evidence, approved facts and sharing permission. Review every option before using it.</p>
    {status && <p role='status' className='text-sm'>{pending.has(status) ? 'Your request is in progress. You can leave this page and return to see the resulting angles.' : messages[status]}</p>}
    {(error || job.error) && <TrendError error={error ?? job.error} />}
  </div>;
}
