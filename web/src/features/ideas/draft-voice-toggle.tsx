'use client';

import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import type { DraftVoiceControl } from './use-draft';

/**
 * The composer's voice switch for the Ideas draft buttons ("Draft now", "Draft from this source"). Off, the default
 * here, drafts in a neutral voice exactly as before; on, the request asks for the person's approved voice. It is
 * shown only when the selected writer may use that voice, so the page is unchanged for a workspace without one.
 */
export function DraftVoiceToggle({ voice, disabled, className }: { voice: DraftVoiceControl; disabled?: boolean; className?: string }) {
  if (!voice.available) return null;
  const on = voice.mode === 'personalized';
  return (
    <button
      type='button'
      aria-pressed={on}
      disabled={disabled}
      onClick={() => voice.onChange(on ? 'neutral' : 'personalized')}
      title='Uses only the voice and writing samples you approved for this model'
      className={cn(
        'rafii-focus inline-flex min-h-11 items-center gap-2 rounded-[var(--rafii-radius-control)] px-3.5 text-sm font-medium transition-colors disabled:opacity-50',
        on ? 'rafii-glass-selected text-foreground' : 'rafii-glass text-muted-foreground hover:text-foreground',
        className
      )}
    >
      {on ? <Icons.check aria-hidden className='size-4 shrink-0' /> : <Icons.userPen aria-hidden className='size-4 shrink-0' />}
      <span>
        Write in my voice
        {on && voice.revision ? ` · v${voice.revision}` : ''}
      </span>
    </button>
  );
}
