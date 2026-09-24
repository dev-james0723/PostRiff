'use client';

import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { WelcomeClip } from './welcome-clip';

const POINTS: { icon: keyof typeof Icons; text: string }[] = [
  { icon: 'sparkles', text: 'Say what you want to put out: a topic, a link, your notes. Drafts come back in your voice, one per channel.' },
  { icon: 'shieldCheck', text: 'You approve the exact text, media and time. Nothing publishes on its own.' },
  { icon: 'broadcast', text: 'Every channel shows what it can really do, capability by capability, with the evidence.' }
];

/**
 * The first thing a new person sees once their workspace is ready. It offers the tour
 * and never forces it; "Not now" is remembered, and the help menu keeps the tour available.
 */
export function WelcomeDialog({ open, onStart, onDismiss }: { open: boolean; onStart: () => void; onDismiss: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onDismiss()}>
      <DialogContent className='sm:max-w-md'>
        <DialogHeader>
          <DialogTitle>Welcome to Rafii</DialogTitle>
          <DialogDescription>Three things worth knowing before you write anything.</DialogDescription>
        </DialogHeader>
        <WelcomeClip />
        <ul className='flex flex-col gap-3'>
          {POINTS.map((point) => {
            const Icon = Icons[point.icon];
            return (
              <li key={point.icon} className='flex items-start gap-3 text-sm'>
                <span className='bg-primary/10 text-primary flex size-8 shrink-0 items-center justify-center rounded-lg'>
                  <Icon className='size-4' />
                </span>
                <span className='text-muted-foreground pt-1 leading-relaxed'>{point.text}</span>
              </li>
            );
          })}
        </ul>
        <DialogFooter className='sm:justify-between'>
          <Button variant='ghost' onClick={onDismiss}>
            Not now
          </Button>
          <Button onClick={onStart}>
            Take the two-minute tour
            <Icons.chevronRight className='size-4' />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
