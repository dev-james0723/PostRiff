'use client';

import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import type { ModelCatalog } from '@/lib/api/types';
import { useFlash } from '@/hooks/use-flash';
import { relativeTime } from '@/lib/time';
import { authState } from './catalog';

export interface CheckAgainProps {
  /** `refetch` from `useModels()`: the only way this page can ask the server again. */
  refetch: () => Promise<{ data?: ModelCatalog; error: Error | null; isError: boolean }>;
  checking: boolean;
  disabled: boolean;
}

/** Asks the API for the writer list again. The button shows the real request state, nothing simulated. */
export function CheckAgainButton({ refetch, checking, disabled }: CheckAgainProps) {
  const [outcome, flash] = useFlash<'success' | 'error'>();

  async function check() {
    const result = await refetch();
    if (result.isError) {
      toast.error(result.error?.message ? `The writer list could not be checked: ${result.error.message}` : 'The writer list could not be checked.');
      flash('error');
      return;
    }
    const agents = result.data?.agents ?? [];
    if (agents.length > 0) {
      toast.success(agents.map((agent) => `${agent.name}${agent.version ? ` ${agent.version}` : ''}: ${authState(agent).label}`).join(' · '));
    } else {
      toast.success('Checked. No CLI is listed for this deployment.');
    }
    flash('success');
  }

  return (
    <StatefulButton
      variant='outline'
      size='md'
      data-tour='models-rescan'
      state={checking ? 'loading' : (outcome ?? 'idle')}
      loadingText='Checking…'
      successText='Checked'
      errorText='Try again'
      icon={<Icons.refresh className='size-4' />}
      disabled={disabled}
      aria-label='Check again: ask the server for the writer list'
      onClick={() => void check()}
    >
      Check again
    </StatefulButton>
  );
}

/** When this browser last received the list, plus what the server may reuse. */
export function CheckedLine({ receivedAt, now }: { receivedAt: number; now: number }) {
  return (
    <p className='text-muted-foreground text-xs'>
      {receivedAt > 0 ? (
        <>
          List received{' '}
          <time dateTime={new Date(receivedAt * 1000).toISOString()}>{relativeTime(receivedAt, Math.max(now, receivedAt))}</time>.{' '}
        </>
      ) : null}
      The server may answer with a CLI check it made up to a minute earlier.
    </p>
  );
}
