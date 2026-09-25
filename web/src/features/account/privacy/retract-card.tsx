'use client';

import { useState } from 'react';
import Link from 'next/link';
import { useQueryClient } from '@tanstack/react-query';
import { toast } from 'sonner';
import { rafiiSelectTrigger } from '@/components/auth/form-styles';
import { HoldActionButton } from '@/components/motion/hold-action-button';
import { StateMessage } from '@/components/rafii';
import { LearnMoreChevron } from '@/components/ui/learn-more-chevron';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Snapshot } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { SettingsSection } from '../settings-section';
import type { BusyProps } from './export-cards';
import { activeSources, draftsUsing, plural, retractionImpact, retractionLines, sourceKindLabel, sourceName } from './privacy-model';
import { Unavailable, type Refetchable } from './section';

/* Same destructive tint as the Ideas page's hold-to-withdraw, so the gesture reads the same everywhere. */
const HOLD_CLASS = 'rafii-glass h-12 w-full min-w-0 rounded-[var(--rafii-radius-control)] px-4 text-foreground [--hold-radius:var(--rafii-radius-control)]';
const HOLD_FILL = 'bg-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const HOLD_WAVE = 'text-[color-mix(in_oklch,var(--destructive)_28%,var(--secondary))]';
const linkClass = 't-learn rafii-focus text-foreground inline-flex min-h-9 items-center gap-0.5 rounded-sm text-sm font-medium hover:underline';

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
    setBusy('retract');
    setRetracting(true);
    try {
      await api.dataRequest(workspaceId, { kind: 'retraction', sourceId: source.id, expectedRevision: snapshot.data.revision });
      setPicked(null);
      // The impact lines were shown before the hold; the toast only confirms the irreversible step.
      toast.success('Source retracted');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Couldn’t retract the source. Try again.');
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
    <SettingsSection
      id='privacy-retract'
      title='Retract a source'
      description='Blanks a source’s text and facts. Drafts that used it are blocked until drafted again. This can’t be undone.'
      className='h-full'
      bodyClassName='flex-1'
      data-tour='privacy-retract'
    >
      {snapshot.isPending ? (
        <Skeleton className='h-12 w-full rounded-[var(--rafii-radius-control)]' />
      ) : !state ? (
        <Unavailable query={snapshot} fallback='Couldn’t read sources.' />
      ) : sources.length === 0 ? (
        <StateMessage kind='empty' layout='inline' title='No sources yet' />
      ) : (
        <>
          <Select value={picked ?? ''} onValueChange={(value) => setPicked(value ? String(value) : null)}>
            <SelectTrigger className={rafiiSelectTrigger} aria-label='Source to retract' disabled={!canEdit || retracting}>
              <SelectValue>{source ? sourceName(source) : 'Choose a source'}</SelectValue>
            </SelectTrigger>
            <SelectContent className='rafii-elevated rounded-2xl bg-transparent ring-0'>
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
            <ul className='text-muted-foreground flex list-disc flex-col gap-1 pl-4 text-xs leading-relaxed' aria-live='polite'>
              {lines.map((line) => (
                <li key={line}>{line}</li>
              ))}
              {impact.resetsIdea && <li>Your current idea came from this source and will be reset.</li>}
            </ul>
          ) : (
            !canEdit && <p className='text-muted-foreground text-xs'>Only editors and the owner can retract.</p>
          )}
        </>
      )}
      <div className='mt-auto flex flex-col items-stretch gap-2 pt-1'>
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
          Sources in Ideas <LearnMoreChevron className='size-3.5' />
        </Link>
      </div>
    </SettingsSection>
  );
}
