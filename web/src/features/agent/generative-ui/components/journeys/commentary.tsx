'use client';
/**
 * Rafii's own words in a generated view, kept visually apart from stored records and verified status (lane E). The text
 * is model-written: it is shown as plain text under an explicit "Rafii's note" label and never styled like a fact,
 * a receipt or a status.
 */
import { z } from 'zod';
import { useJourneyEnvironment } from '../../journeys/runtime';
import type { JourneyRendererProps } from './types';

const commentaryProps = z.object({ text: z.string().min(1).max(600) });

export function Commentary({ props }: JourneyRendererProps) {
  const { copy } = useJourneyEnvironment();
  const parsed = commentaryProps.safeParse(props);
  if (!parsed.success) return null;
  return (
    <aside aria-label={copy.common.rafiiNote} className='border-border/70 flex flex-col gap-0.5 border-l-2 pl-3'>
      <span className='text-muted-foreground text-[11px] font-medium tracking-wide uppercase'>{copy.common.rafiiNote}</span>
      <p className='text-muted-foreground text-sm text-pretty' dir='auto'>
        {parsed.data.text}
      </p>
    </aside>
  );
}
