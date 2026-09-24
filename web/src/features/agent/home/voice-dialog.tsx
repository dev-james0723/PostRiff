'use client';

import { useEffect, useState } from 'react';
import Link from 'next/link';
import { Icons } from '@/components/icons';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

export type VoiceMode = 'neutral' | 'personalized';

export interface VoiceDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  value: VoiceMode;
  onApply: (value: VoiceMode) => void;
  /** Approved writing samples exist for the selected route (`eligibleVoiceSources`). */
  available: boolean;
  sampleCount: number;
  /** The active voice profile revision, when one is approved. */
  voiceRevision: number | null;
  modelLabel: string;
}

/**
 * Writing Voice (DNA §15.5): a versioned profile, not a tone slider. Neutral writes without the
 * person's samples; Personalized uses only the samples approved for the selected writer route.
 * Choices stage inside the dialog and apply on the primary action; closing keeps the applied value.
 */
export function VoiceDialog({ open, onOpenChange, value, onApply, available, sampleCount, voiceRevision, modelLabel }: VoiceDialogProps) {
  const [staged, setStaged] = useState<VoiceMode>(value);
  useEffect(() => {
    if (open) setStaged(value);
  }, [open, value]);
  const options: { id: VoiceMode; title: string; detail: string; disabled?: boolean }[] = [
    { id: 'neutral', title: 'Neutral', detail: 'Clear and natural. Writes from your idea and sources without your writing samples.' },
    {
      id: 'personalized',
      title: 'Writing like you',
      detail: available ? `Uses the ${sampleCount} writing sample${sampleCount === 1 ? '' : 's'} you approved for ${modelLabel}.` : `No writing samples are approved for ${modelLabel} yet. Add and allow samples on the Brand page.`,
      disabled: !available
    }
  ];
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm' aria-describedby={undefined}>
        <RafiiDialogHeader eyebrow='Writing voice' title='Choose the' accent='voice.' intro='Which writing the drafts should sound like. Nothing here changes your languages, model or destinations.' />
        <RafiiDialogBody className='flex flex-col gap-3 pt-1'>
          <div role='radiogroup' aria-label='Writing voice' className='flex flex-col gap-2'>
            {options.map((option) => {
              const selected = staged === option.id;
              return (
                <button
                  key={option.id}
                  type='button'
                  role='radio'
                  aria-checked={selected}
                  disabled={option.disabled}
                  onClick={() => setStaged(option.id)}
                  className={cn('rafii-focus flex min-h-16 items-start gap-3 rounded-[var(--rafii-radius-card)] px-4 py-3.5 text-left transition-colors disabled:opacity-50', selected ? 'rafii-glass-selected' : 'rafii-glass')}
                >
                  <span aria-hidden className={cn('mt-0.5 flex size-5 shrink-0 items-center justify-center rounded-full', selected ? 'bg-foreground text-background' : 'rafii-quiet')}>
                    {selected && <Icons.check className='size-3' />}
                  </span>
                  <span className='flex min-w-0 flex-col gap-1'>
                    <span className='text-foreground text-sm font-medium'>{option.title}</span>
                    <span className='text-muted-foreground text-xs leading-relaxed'>{option.detail}</span>
                  </span>
                </button>
              );
            })}
          </div>
          <p className='text-muted-foreground flex items-start gap-2 text-xs leading-relaxed'>
            <Icons.info aria-hidden className='mt-0.5 size-3.5 shrink-0' />
            <span>
              {voiceRevision ? `Voice profile revision ${voiceRevision} is active for approvals.` : 'No voice profile is active yet.'}{' '}
              <Link href='/app/workspace/brand' className='text-foreground underline underline-offset-2'>
                Manage voice and samples
              </Link>
            </span>
          </p>
        </RafiiDialogBody>
        <RafiiDialogFooter>
          <Button variant='action' size='control' className='w-full' onClick={() => { onApply(staged); onOpenChange(false); }}>
            Use this voice
            <Icons.check />
          </Button>
        </RafiiDialogFooter>
      </RafiiDialogContent>
    </RafiiDialog>
  );
}
