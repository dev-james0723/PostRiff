'use client';

import { Icons } from '@/components/icons';
import { Badge } from '@/components/ui/badge';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Collapsible, CollapsibleContent, CollapsibleTrigger } from '@/components/ui/collapsible';
import type { SnapshotState, VoiceProfile } from '@/lib/api/types';
import { ApprovedDate, SectionUnavailable, type Refetchable } from './brand-parts';
import { describeChanges, reasonLabel, toneLabel, type VoiceRevision } from './voice-model';

/** Revisions shown before the rest fold away. */
const VISIBLE = 3;

function Changes({ changes, against }: { changes: string[] | null; against: number | null }) {
  // No earlier revision, or no stored profile to compare: say nothing rather than guess.
  if (changes === null || against === null) return null;
  if (changes.length === 0) return <p className='text-muted-foreground text-xs'>Same as revision {against}.</p>;
  return (
    <p className='text-muted-foreground text-xs'>
      <span className='sr-only'>Changed from revision {against}: </span>
      <span aria-hidden>Since revision {against}: </span>
      {changes.join(' · ')}
    </p>
  );
}

function RevisionRow({ record, previous, active }: { record: VoiceRevision; previous: VoiceRevision | null; active: boolean }) {
  const reason = reasonLabel(record.reason);
  const tone = toneLabel(record.profile?.tone);
  return (
    <li className='flex min-w-0 flex-col gap-1 py-2.5 first:pt-0 last:pb-0'>
      <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
        <span className='text-sm font-medium'>Revision {record.revision}</span>
        {active && <Badge variant='secondary'>Active</Badge>}
        {tone && <Badge variant='outline'>{tone}</Badge>}
      </div>
      <p className='text-muted-foreground text-xs'>
        <ApprovedDate iso={record.approvedAt} />
        {reason ? ` · ${reason}` : ''}
      </p>
      {previous ? (
        <Changes changes={describeChanges(previous.profile, record.profile)} against={previous.revision} />
      ) : (
        <p className='text-muted-foreground text-xs'>First revision.</p>
      )}
    </li>
  );
}

function ProposedRow({ provisional, active }: { provisional: VoiceProfile; active: VoiceRevision | null }) {
  const tone = toneLabel(provisional.tone);
  return (
    <li className='flex min-w-0 flex-col gap-1 py-2.5 first:pt-0'>
      <div className='flex flex-wrap items-center gap-x-2 gap-y-1'>
        <span className='text-sm font-medium'>Proposed</span>
        <Badge variant='outline'>Waiting for approval</Badge>
        {tone && <Badge variant='outline'>{tone}</Badge>}
      </div>
      <p className='text-muted-foreground text-xs'>Not a revision until an owner approves it.</p>
      {active && <Changes changes={describeChanges(active.profile, provisional)} against={active.revision} />}
    </li>
  );
}

/** Every approved voice revision, newest first, with what changed where both profiles are stored. */
export function RevisionHistory({ state, query }: { state: SnapshotState | undefined; query: Refetchable }) {
  const speaker = state?.speaker;
  const revisions = Array.isArray(speaker?.revisions) ? speaker.revisions : null;
  const byNumber = revisions ? revisions.toSorted((a, b) => a.revision - b.revision) : [];
  const newestFirst = byNumber.toReversed();
  const previousOf = (record: VoiceRevision) => {
    const index = byNumber.indexOf(record);
    return index > 0 ? byNumber[index - 1] : null;
  };
  const active = speaker?.activeRevision ?? null;
  const activeRecord = byNumber.find((r) => r.revision === active) ?? null;
  const visible = newestFirst.slice(0, VISIBLE);
  const folded = newestFirst.slice(VISIBLE);

  return (
    <Card data-tour='brand-history' className='min-w-0'>
      <CardHeader>
        <CardTitle>
          Revisions{revisions ? <span className='text-muted-foreground font-normal'> · {revisions.length}</span> : null}
        </CardTitle>
        <CardDescription>Each approval adds a revision; earlier ones stay listed. A revision records the tone, observations, sample and unknowns, not the purpose or audience.</CardDescription>
      </CardHeader>
      <CardContent>
        {!speaker || !revisions ? (
          <SectionUnavailable message='The revision history could not be read from this workspace.' query={query} />
        ) : revisions.length === 0 && !speaker.provisional ? (
          <p className='text-muted-foreground text-sm'>No approved revisions yet. The first one appears when an owner approves a voice.</p>
        ) : (
          <>
            <ol className='divide-y' aria-label='Voice revisions, newest first'>
              {speaker.provisional && <ProposedRow provisional={speaker.provisional} active={activeRecord} />}
              {visible.map((record) => (
                <RevisionRow key={record.revision} record={record} previous={previousOf(record)} active={record.revision === active} />
              ))}
            </ol>
            {folded.length > 0 && (
              <Collapsible className='mt-2'>
                <CollapsibleTrigger className='group/older text-muted-foreground hover:text-foreground focus-visible:ring-ring/50 flex items-center gap-1 rounded-sm text-xs outline-none focus-visible:ring-2'>
                  <Icons.chevronDown aria-hidden className='size-3.5 -rotate-90 transition-transform duration-(--duration-fast) ease-(--ease-smooth-out) group-data-panel-open/older:rotate-0 motion-reduce:transition-none' />
                  <span className='group-data-panel-open/older:hidden'>Show {folded.length} older</span>
                  <span className='hidden group-data-panel-open/older:inline'>Hide older</span>
                </CollapsibleTrigger>
                <CollapsibleContent className='t-nav-panel'>
                  <ol className='divide-y border-t pt-2.5' aria-label='Older voice revisions'>
                    {folded.map((record) => (
                      <RevisionRow key={record.revision} record={record} previous={previousOf(record)} active={record.revision === active} />
                    ))}
                  </ol>
                </CollapsibleContent>
              </Collapsible>
            )}
          </>
        )}
      </CardContent>
    </Card>
  );
}
