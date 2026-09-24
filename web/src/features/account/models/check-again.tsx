'use client';

import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import type { ModelCatalog } from '@/lib/api/types';
import { useFlash } from '@/hooks/use-flash';
import { relativeTime } from '@/lib/time';
import { authState } from './catalog';

export interface CheckAgainProps {
  /** Performs an authenticated fresh scan, including newly installed CLI routes. */
  rescan: () => Promise<ModelCatalog>;
  checking: boolean;
  disabled: boolean;
}

/** The glass recipe on the motion button: a quiet secondary control beside the page title (DNA §9.2). */
const GLASS_BUTTON =
  'rafii-glass hover:rafii-glass-selected h-12 rounded-[var(--rafii-radius-control)] border-0 bg-transparent px-4 text-sm hover:bg-transparent dark:bg-transparent dark:hover:bg-transparent';

/** Asks the API for the writer list again. The button shows the real request state, nothing simulated. */
export function CheckAgainButton({ rescan, checking, disabled }: CheckAgainProps) {
  const [outcome, flash] = useFlash<'success' | 'error'>();

  async function check() {
    let catalog: ModelCatalog;
    try {
      catalog = await rescan();
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'The writer list could not be checked.');
      flash('error');
      return;
    }
    const agents = catalog.agents ?? [];
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
      className={GLASS_BUTTON}
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
      Check again refreshes the installation and sign-in checks.
    </p>
  );
}
