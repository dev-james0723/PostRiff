'use client';

import { Icons } from '@/components/icons';
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** One card's load failure: the API's message and a Retry that refetches only that card's query. */
export function LoadError({
  title,
  error,
  retrying,
  onRetry
}: {
  title: string;
  error: unknown;
  retrying: boolean;
  onRetry: () => void;
}) {
  return (
    <Alert variant='destructive'>
      <Icons.alertCircle aria-hidden />
      <AlertTitle>{title}</AlertTitle>
      <AlertDescription className='flex flex-col items-start gap-2'>
        <span>{error instanceof Error && error.message ? error.message : 'The workspace did not respond.'}</span>
        <Button size='sm' variant='outline' disabled={retrying} onClick={onRetry}>
          <Icons.refresh className={cn(retrying && 'animate-spin')} aria-hidden />
          Retry
        </Button>
      </AlertDescription>
    </Alert>
  );
}
