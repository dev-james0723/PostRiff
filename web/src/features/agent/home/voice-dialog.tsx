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
    { id: 'neutral', title: 'Neutral', detail: 'Clear and natural. Doesn’t use your writing samples.' },
    {
      id: 'personalized',
      title: 'Writing like you',
      detail: available ? `Uses ${sampleCount} sample${sampleCount === 1 ? '' : 's'} you approved for ${modelLabel}.` : `No samples approved for ${modelLabel} yet.`,
      disabled: !available
    }
  ];
  return (
    <RafiiDialog open={open} onOpenChange={onOpenChange}>
      <RafiiDialogContent size='sm' aria-describedby={undefined}>
        <RafiiDialogHeader eyebrow='Writing voice' title='Choose the' accent='voice.' />
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
          <Link href='/app/workspace/brand' className='rafii-focus text-foreground w-fit rounded-md text-xs underline underline-offset-2' title={voiceRevision ? `Voice profile revision ${voiceRevision} is active` : 'No voice profile yet'}>
            Manage voice and samples
          </Link>
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
