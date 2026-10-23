'use client';

import type { ReactNode, Ref } from 'react';
import type { DiscordCopy } from '../../lib/channels/discord-copy';
import { formatRetryTime, type SenderState } from '../../lib/channels/discord-sender-name';
import { recheckLine, senderStateCopy, type BlockedStateKey } from '../../lib/channels/discord-sender-state-copy';

export interface SenderStatePanelProps {
  state: SenderState & { key: BlockedStateKey };
  copy: DiscordCopy;
  locale: string;
  timeZone?: string;
  /** DOM id prefix, so the form can point `aria-describedby` at the title, body and next step. */
  id: string;
  /**
   * `alert` when the state came from an action that just failed. Left out when the panel sits inside the dialog's
   * persistent live region (a state found on open), which announces it.
   */
  role?: 'alert';
  /** The heading receives programmatic focus when the state appears, so a screen reader lands on the explanation. */
  headingRef?: Ref<HTMLHeadingElement>;
  /** Check again, reload or sign in again. Never a second write. */
  actions?: ReactNode;
  nowMs?: number;
  /** When Rafii last read the state from the server (epoch milliseconds); shown so a repeated check visibly happened. */
  checkedAtMs?: number | null;
}

/**
 * One availability state in plain words: what is wrong (title and body) and what the person can do next (or that
 * nothing can be done). Each state has a stable test id, `discord-sender-state-<key>`, and `data-state`.
 */
export function SenderStatePanel({ state, copy, locale, timeZone, id, role, headingRef, actions, nowMs, checkedAtMs }: SenderStatePanelProps) {
  const lines = senderStateCopy(copy, state.key);
  const checked = typeof checkedAtMs === 'number' ? formatRetryTime(checkedAtMs / 1000, locale, timeZone) : null;
  return (
    <section
      role={role}
      aria-labelledby={`${id}-title`}
      data-testid={`discord-sender-state-${state.key}`}
      data-state={state.key}
      data-discord-sender-state
      className='flex flex-col gap-2 rounded-lg border p-3'
    >
      <h3 id={`${id}-title`} ref={headingRef} tabIndex={-1} className='focus-visible:ring-ring/50 rounded text-sm font-medium outline-none focus-visible:ring-3'>
        {lines.title}
      </h3>
      <p id={`${id}-body`} className='text-sm'>
        {lines.body}
      </p>
      {state.key === 'edit_pending' && (
        <p data-recheck className='text-sm font-medium'>
          {recheckLine(copy, state.retryAt, locale, timeZone, nowMs)}
        </p>
      )}
      <div className='flex flex-col gap-0.5'>
        <p className='text-muted-foreground text-xs font-medium'>{copy.senderStateNextLabel}</p>
        <p id={`${id}-next`} className='text-sm'>
          {lines.next}
        </p>
      </div>
      {checked && (
        <p data-checked-at className='text-muted-foreground text-xs'>
          {copy.senderCheckedAt.replace('{time}', checked)}
        </p>
      )}
      {actions && <div className='flex flex-wrap gap-2 pt-1'>{actions}</div>}
    </section>
  );
}
