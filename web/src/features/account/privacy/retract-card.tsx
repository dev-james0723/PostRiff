'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { Card, CardContent, CardDescription, CardFooter, CardHeader, CardTitle } from '@/components/ui/card';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Snapshot } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { BusyProps } from './export-cards';
import { activeSources, draftsUsing, plural, retractionImpact, retractionLines, sourceKindLabel, sourceName } from './privacy-model';
import { Unavailable, type Refetchable } from './section';

/* Same destructive tint as the Ideas page's hold-to-withdraw, so the gesture reads the same everywhere. */
const HOLD_CLASS = 'h-9 w-full min-w-0 bg-secondary px-4 text-secondary-foreground [--hold-radius:min(var(--radius-md),12px)]';
const HOLD_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const HOLD_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const linkClass = 't-learn text-foreground inline-flex items-center gap-0.5 text-sm font-medium hover:underline';

export function RetractCard({
  snapshot,
  canEdit,
  busy,
  setBusy
}: BusyProps & {
  snapshot: Refetchable & { data?: Snapshot; isPending: boolean };
  canEdit: boolean;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [picked, setPicked] = useState<string | null>(null);
  const [retracting, setRetracting] = useState(false);
  // Remounts the hold button so a finished or failed hold can be pressed again.
  const [holdEpoch, setHoldEpoch] = useState(0);

  const state = snapshot.data?.state;
  const sources = state ? activeSources(state) : [];
  const source = sources.find((item) => item.id === picked) ?? null;
  const impact = state && source ? retractionImpact(state, source.id) : null;
  const lines = impact ? retractionLines(impact) : [];

  async function retract() {
    if (!source || !snapshot.data || !impact) return;
    // Counted from the snapshot the server checks against (expectedRevision), so they match what it did.
    const done = impact;
    setBusy('retract');
    setRetracting(true);
    try {
      await api.dataRequest(workspaceId, { kind: 'retraction', sourceId: source.id, expectedRevision: snapshot.data.revision });
      setPicked(null);
      toast.success(`Source retracted. ${retractionLines(done).join(' ')}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The source could not be retracted.');
      if (err instanceof ApiError && err.status === 409) void snapshot.refetch();
    } finally {
      setRetracting(false);
      setHoldEpoch((n) => n + 1);
      setBusy(null);
      void client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.dataRequests(workspaceId) });
    }
  }

  const disabled = !canEdit || !source || retracting || (busy !== null && busy !== 'retract');

  return (
    <Card data-tour='privacy-retract' className='min-w-0'>
      <CardHeader>
        <CardTitle>Retract a source</CardTitle>
        <CardDescription>
          Blanks a source&apos;s text and facts. Drafts that used it keep their text but stay blocked until you draft them again.
          Their posts waiting in the Queue are held until approved again. This cannot be undone.
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        {snapshot.isPending ? (
          <Skeleton className='h-8 w-full' />
        ) : !state ? (
          <Unavailable query={snapshot} fallback='Sources could not be read.' />
        ) : sources.length === 0 ? (
          <p className='text-muted-foreground text-sm'>No active sources in this workspace.</p>
        ) : (
          <>
            <Select value={picked ?? ''} onValueChange={(value) => setPicked(value ? String(value) : null)}>
              <SelectTrigger className='h-9 w-full min-w-0' aria-label='Source to retract' disabled={!canEdit || retracting}>
                <SelectValue>{source ? sourceName(source) : 'Choose a source'}</SelectValue>
              </SelectTrigger>
              <SelectContent>
                {sources.map((item) => (
                  <SelectItem key={item.id} value={item.id}>
                    <span className='flex min-w-0 flex-col'>
                      <span className='truncate'>{sourceName(item)}</span>
                      <span className='text-muted-foreground text-xs'>
                        {sourceKindLabel(item.kind)}
                        {item.facts && item.facts.length > 0 ? ` · ${plural(item.facts.filter((fact) => fact.approved).length, 'approved fact')}` : ''}
                        {` · used by ${plural(draftsUsing(state, item.id).length, 'draft')}`}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {impact ? (
              <ul className='text-muted-foreground flex list-disc flex-col gap-1 pl-4 text-xs' aria-live='polite'>
                {lines.map((line) => (
                  <li key={line}>{line}</li>
                ))}
                {impact.resetsIdea && <li>Your current idea came from this source and will be reset.</li>}
              </ul>
            ) : (
              !canEdit && <p className='text-muted-foreground text-xs'>Ask an editor or the owner to retract a source.</p>
            )}
          </>
        )}
      </CardContent>
      <CardFooter className='mt-auto flex flex-col items-stretch gap-2'>
        {state && sources.length > 0 && (
          <HoldActionButton
            key={holdEpoch}
            type='horizontal'
            holdDuration={900}
            holdingLabel='Keep holding…'
            completeLabel='Retracting…'
            disabled={disabled}
            onHoldComplete={() => void retract()}
            aria-label={source ? `Hold to retract ${sourceName(source)}` : 'Choose a source to retract'}
            title='Press and hold (or hold Space) to retract this source.'
            className={HOLD_CLASS}
            fillClassName={HOLD_FILL}
            waveClassName={HOLD_WAVE}
            labelClassName='text-sm'
          >
            Hold to retract
          </HoldActionButton>
        )}
        <Link href='/app/ideas' className={linkClass}>
          Review sources in Ideas <LearnMoreChevron className='size-3.5' />
        </Link>
      </CardFooter>
    </Card>
  );
}
