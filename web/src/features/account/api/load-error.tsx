'use client';

import { Icons } from '@/components/icons';
import { StateMessage } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { cn } from '@/lib/utils';

/** One section's load failure: the API's message and a Retry that refetches only that section's query. */
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
    <StateMessage
      kind='error'
      layout='inline'
      title={title}
      description={error instanceof Error && error.message ? error.message : 'The workspace did not respond.'}
      action={
        <Button size='sm' variant='glass' className='min-h-9' disabled={retrying} onClick={onRetry}>
          <Icons.refresh className={cn(retrying && 'animate-spin motion-reduce:animate-none')} aria-hidden />
          Retry
        </Button>
      }
    />
  );
}
