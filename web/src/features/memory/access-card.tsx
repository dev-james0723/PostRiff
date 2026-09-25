'use client';

import { useState, type ReactNode } from 'react';
import { toast } from 'sonner';
import type { AnimatedBadgeStatus } from '@/components/motion/animated-badge';
import { Switch } from '@/components/motion/switch';
import { AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription, AlertDialogFooter, AlertDialogHeader, AlertDialogTitle } from '@/components/ui/alert-dialog';
import { LoadingButton } from '@/components/ui/loading-button';
import { Skeleton } from '@/components/ui/skeleton';
import { Panel, StatusChip } from '@/features/workspace/rafii-parts';
import { ApiError } from '@/lib/api/client';
import { useAct, useInvalidate, useMembers, useMemory, useSnapshot } from '@/lib/api/hooks';
import type { MemoryEgress, ResearchEgress } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { memoryFileLabel } from './memory-files';
import { formatDate } from '@/lib/time';
import { Unavailable } from './memory-states';

/** "A, B and C" / "A, B or C". */
function listNames(names: string[], last: 'and' | 'or') {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} ${last} ${names.at(-1)}`;
}

/** When an owner decision last changed and, for owners, whether they made it (a workspace can have several owners). */
function useDecidedLine(decidedAt: number | null, decidedBy: string | null, isOwner: boolean) {
  const members = useMembers();
  if (!decidedAt) return null;
  const when = formatDate(decidedAt);
  if (!isOwner || !members.data) return `Last changed ${when}.`;
  const byYou = members.data.members.some((m) => m.you && m.userId === decidedBy);
  return byYou ? `Changed by you on ${when}.` : `Changed by another owner on ${when}.`;
}

/** Mutation errors say what the server said; a stale revision offers a reload of everything this page reads. */
function useSaveError() {
  const invalidate = useInvalidate();
  return (err: unknown, fallback: string) => {
    const message = err instanceof ApiError ? err.message : fallback;
    if (err instanceof ApiError && err.status === 409) {
      toast.error(message, { action: { label: 'Reload', onClick: () => invalidate('snapshot', 'memory', 'memoryProposals') } });
    } else {
      toast.error(message);
    }
  };
}

/**
 * An owner turns a switch; nothing is sent until they confirm here. The dialog says what will be shared and with whom,
 * stays open while the change saves, and only its confirm button sends `confirmed: true`.
 */
function useConfirmedChoice() {
  const [open, setOpen] = useState(false);
  // Kept after closing so the dialog's copy doesn't flip while it animates out.
  const [requested, setRequested] = useState(false);
  return {
    open,
    requested,
    ask: (value: boolean) => {
      setRequested(value);
      setOpen(true);
    },
    close: () => setOpen(false)
  };
}

function ConfirmChoice({ open, pending, title, description, confirmLabel, cancelLabel, onConfirm, onClose }: { open: boolean; pending: boolean; title: string; description: string; confirmLabel: string; cancelLabel: string; onConfirm: () => void; onClose: () => void }) {
  return (
    <AlertDialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !pending) onClose();
      }}
    >
      <AlertDialogContent className='rafii-elevated rounded-[var(--rafii-radius-mobile-dialog)] p-5 ring-0 md:rounded-[var(--rafii-radius-dialog)] md:p-6'>
        <AlertDialogHeader>
          <AlertDialogTitle>{title}</AlertDialogTitle>
          <AlertDialogDescription>{description}</AlertDialogDescription>
        </AlertDialogHeader>
        <AlertDialogFooter>
          <AlertDialogCancel variant='glass' size='control' disabled={pending}>
            {cancelLabel}
          </AlertDialogCancel>
          <LoadingButton variant='action' size='control' loading={pending} loadingLabel='Saving…' onClick={onConfirm}>
            {confirmLabel}
          </LoadingButton>
        </AlertDialogFooter>
      </AlertDialogContent>
    </AlertDialog>
  );
}

function AccessRow({ title, status, badge, description, note, control }: { title: string; status: AnimatedBadgeStatus; badge: string; description: ReactNode; note?: string | null; control?: ReactNode }) {
  return (
    <div className='rafii-quiet flex flex-col gap-3 rounded-[var(--rafii-radius-control)] p-4 sm:flex-row sm:items-start sm:justify-between'>
      <div className='flex min-w-0 flex-col gap-1.5'>
        <div className='flex flex-wrap items-center gap-2'>
          <span className='text-foreground text-sm font-medium'>{title}</span>
          <StatusChip status={status}>{badge}</StatusChip>
        </div>
        <p className='text-muted-foreground max-w-prose text-sm leading-relaxed'>{description}</p>
        {note ? <p className='text-muted-foreground text-xs'>{note}</p> : null}
      </div>
      {control}
    </div>
  );
}

function CloudRow({ egress, isOwner }: { egress: MemoryEgress | undefined; isOwner: boolean }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const saveError = useSaveError();
  const decidedLine = useDecidedLine(egress?.decidedAt ?? null, egress?.decidedBy ?? null, isOwner);
  const choice = useConfirmedChoice();

  if (!egress) {
    return <AccessRow title='Cloud model access' status='warning' badge='Unavailable' description='Couldn’t load this setting.' />;
  }

  const shared = egress.sharedFiles ?? [];
  const privacy = (egress.shareablePrivacy ?? []).map((value) => value.replace(/_/g, ' '));
  const withheld = egress.withheldBoundaries;
  const files = shared.length > 0 ? listNames(shared.map((name) => memoryFileLabel(name).toLowerCase()), egress.cloud ? 'and' : 'or') : 'your memory';
  const allFiles = shared.length > 0 ? listNames(shared.map((name) => memoryFileLabel(name).toLowerCase()), 'and') : 'your memory';
  const boundaryRule =
    (privacy.length > 0 && shared.includes('BOUNDARIES.md') ? ` Only boundaries marked ${listNames(privacy, 'or')} are included.` : '') +
    (withheld > 0 ? ` ${withheld} private or local-only boundar${withheld === 1 ? 'y stays' : 'ies stay'} out.` : '');

  // Sent only from the dialog's confirm button, after the owner has read what changes.
  function decide(cloud: boolean) {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'memory_egress', payload: { cloud, confirmed: true } },
      {
        // The row's switch and badge show the result; no toast.
        onSuccess: () => {
          choice.close();
          invalidate('memory');
        },
        onError: (err) => {
          choice.close();
          saveError(err, 'The sharing choice could not be saved.');
        }
      }
    );
  }

  const description =
    (egress.cloud
      ? `The cloud model reads ${files} when it drafts${privacy.length > 0 && shared.includes('BOUNDARIES.md') ? `, with only boundaries marked ${listNames(privacy, 'or')}` : ''}.`
      : `The cloud model doesn’t read ${files}.`) + (withheld > 0 ? ` ${withheld} private boundar${withheld === 1 ? 'y never reaches' : 'ies never reach'} it.` : '');

  return (
    <>
      <AccessRow
        title='Cloud model access'
        status={egress.cloud ? 'success' : 'neutral'}
        badge={egress.cloud ? 'Shared' : 'Not shared'}
        description={description}
        note={isOwner ? decidedLine : ['Only an owner can change this.', decidedLine].filter(Boolean).join(' ')}
        control={<Switch checked={egress.cloud} disabled={!isOwner || act.isPending || !snapshot.data} onCheckedChange={choice.ask} ariaLabel='Let the cloud model read your memory files' label='Allow' />}
      />
      {isOwner && (
        <ConfirmChoice
          open={choice.open}
          pending={act.isPending}
          title={choice.requested ? 'Let the cloud model read your memory files?' : 'Stop sharing memory files with the cloud model?'}
          description={
            choice.requested
              ? `The cloud model will receive ${allFiles} each time it drafts for this workspace.${boundaryRule}`
              : `The cloud model will stop receiving ${allFiles}. Local writers still read them.`
          }
          confirmLabel={choice.requested ? 'Allow cloud access' : 'Stop sharing'}
          cancelLabel={choice.requested ? 'Keep it off' : 'Keep sharing'}
          onConfirm={() => decide(choice.requested)}
          onClose={choice.close}
        />
      )}
    </>
  );
}

function ResearchRow({ research, isOwner }: { research: ResearchEgress | undefined; isOwner: boolean }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const saveError = useSaveError();
  const decidedLine = useDecidedLine(research?.decidedAt ?? null, research?.decidedBy ?? null, isOwner);
  const choice = useConfirmedChoice();

  if (!research) {
    return <AccessRow title='Web research' status='warning' badge='Unavailable' description='Couldn’t load this setting.' />;
  }

  const onText = 'Drafts can look up missing facts on the web.';
  const offText = 'Drafts use only what you supply.';
  const processors = research.processors ?? [];
  const disclosure = processors.length > 0 ? `Lookups go to: ${processors.join('; ')}. They never receive your sources, memory files or drafts.` : '';

  // No switch applies on the person's own machine (always on) or when research is off for everyone here.
  if (!research.hosted || research.enabled === false) {
    const on = research.enabled !== false;
    return (
      <AccessRow
        title='Web research'
        status={on ? 'success' : 'neutral'}
        badge={on ? 'On' : 'Off'}
        description={on ? `${onText} ${disclosure}` : offText}
        note={on ? 'Always on when drafting on your own machine.' : research.hosted ? 'Web research isn’t available right now.' : 'Turned off on this machine.'}
      />
    );
  }

  // Sent only from the dialog's confirm button, after the owner has read what is sent and to whom.
  function decide(web: boolean) {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'research_egress', payload: { web, confirmed: true } },
      {
        // The row's switch and badge show the result; no toast.
        onSuccess: () => {
          choice.close();
          invalidate('memory');
        },
        onError: (err) => {
          choice.close();
          saveError(err, 'The research choice could not be saved.');
        }
      }
    );
  }

  return (
    <>
      <AccessRow
        title='Web research'
        status={research.web ? 'success' : 'neutral'}
        badge={research.web ? 'On' : 'Off'}
        description={`${research.web ? onText : offText} ${disclosure}`}
        note={isOwner ? decidedLine : ['Only an owner can change this.', decidedLine].filter(Boolean).join(' ')}
        control={<Switch checked={research.web} disabled={!isOwner || act.isPending || !snapshot.data} onCheckedChange={choice.ask} ariaLabel='Let Rafii look facts up on the web' label='Allow' />}
      />
      {isOwner && (
        <ConfirmChoice
          open={choice.open}
          pending={act.isPending}
          title={choice.requested ? 'Turn on web research?' : 'Turn off web research?'}
          description={choice.requested ? `${onText} ${disclosure || 'Couldn’t check which services receive the lookups.'}` : offText}
          confirmLabel={choice.requested ? 'Turn on' : 'Turn off'}
          cancelLabel={choice.requested ? 'Keep it off' : 'Keep it on'}
          onConfirm={() => decide(choice.requested)}
          onClose={choice.close}
        />
      )}
    </>
  );
}

/**
 * Who reads the memory files besides routes on the person's own machine: the cloud model and web research,
 * each an owner decision with its real state and consequence. A setting the API leaves out reads Unavailable, never Off.
 */
export function AccessCard({ className }: { className?: string }) {
  const memory = useMemory();
  const isOwner = checkAccess(useWorkspaceAccess(), { permission: 'owner' });

  return (
    <Panel
      material='glass'
      data-tour='memory-access'
      titleId='memory-access-title'
      title='Who reads these files'
      description='Local writers always read these files. An owner decides who else can.'
      className={className}
      bodyClassName='gap-2'
    >
      {memory.data ? (
        <>
          <CloudRow egress={memory.data.egress} isOwner={isOwner} />
          <ResearchRow research={memory.data.research} isOwner={isOwner} />
        </>
      ) : memory.isLoading ? (
        <div className='flex flex-col gap-2' role='status' aria-label='Loading access settings'>
          <Skeleton className='h-20 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-20 w-full rounded-[var(--rafii-radius-control)]' />
        </div>
      ) : (
        <Unavailable message='Couldn’t load access settings.' query={memory} />
      )}
    </Panel>
  );
}
