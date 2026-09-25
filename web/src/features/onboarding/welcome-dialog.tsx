'use client';

import { rafiiDialog, rafiiDialogFooter } from '@/components/auth/form-styles';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { cn } from '@/lib/utils';
import { WelcomeClip } from './welcome-clip';

const POINTS: { icon: keyof typeof Icons; text: string }[] = [
  { icon: 'sparkles', text: 'Say what you want to post. Drafts come back in your voice.' },
  { icon: 'shieldCheck', text: 'You approve every post. Nothing publishes on its own.' },
  { icon: 'broadcast', text: 'Each channel shows what it can really do.' }
];

/**
 * The first thing a new person sees once their workspace is ready. It offers the tour
 * and never forces it; "Not now" is remembered, and the help menu keeps the tour available.
 * An elevated glass dialog (DNA §21.16): no marketing chrome, no entrance that delays work.
 */
export function WelcomeDialog({ open, onStart, onDismiss }: { open: boolean; onStart: () => void; onDismiss: () => void }) {
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onDismiss()}>
      <DialogContent className={cn(rafiiDialog, 'gap-5 sm:max-w-md')}>
        <DialogHeader className='gap-1.5 pr-8'>
          <DialogTitle className='text-foreground text-xl font-medium tracking-tight'>
            Welcome to <em className='rafii-serif'>Rafii</em>
          </DialogTitle>
          <DialogDescription className='leading-relaxed'>Three things to know.</DialogDescription>
        </DialogHeader>
        <WelcomeClip />
        <ul className='flex flex-col gap-3'>
          {POINTS.map((point) => {
            const Icon = Icons[point.icon];
            return (
              <li key={point.icon} className='flex items-start gap-3 text-sm'>
                <span className='rafii-glass text-foreground flex size-9 shrink-0 items-center justify-center rounded-full'>
                  <Icon className='size-4' />
                </span>
                <span className='text-muted-foreground pt-2 leading-relaxed'>{point.text}</span>
              </li>
            );
          })}
        </ul>
        <DialogFooter className={cn(rafiiDialogFooter, 'sm:justify-between')}>
          <Button variant='quiet' size='control' onClick={onDismiss}>
            Not now
          </Button>
          <Button variant='action' size='control' onClick={onStart}>
            Take the tour
            <Icons.chevronRight className='size-4' />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
