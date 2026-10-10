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
import { useAct, useInvalidate, useMembers, useMemory, useModels, useSnapshot } from '@/lib/api/hooks';
import type { MediaConsent, MemoryEgress, ResearchEgress } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { formatDate } from '@/lib/time';
import { Unavailable } from './memory-states';
import { useMemoryText } from './memory-copy';
import { useGenUiLocale } from '@/features/agent/generative-ui/core/locale';

/** "A, B and C" / "A, B or C". */
function listNames(names: string[], last: 'and' | 'or') {
  if (names.length <= 1) return names[0] ?? '';
  return `${names.slice(0, -1).join(', ')} ${last} ${names.at(-1)}`;
}

/** When an owner decision last changed and, for owners, whether they made it (a workspace can have several owners). */
export function useDecidedLine(decidedAt: number | null, decidedBy: string | null, isOwner: boolean) {
  const members = useMembers();
  if (!decidedAt) return null;
  const when = formatDate(decidedAt);
  if (!isOwner || !members.data) return `Last changed ${when}.`;
  const byYou = members.data.members.some((m) => m.you && m.userId === decidedBy);
  return byYou ? `Changed by you on ${when}.` : `Changed by another owner on ${when}.`;
}

/** Mutation errors say what the server said; a stale revision offers a reload of everything this page reads. */
export function useSaveError() {
  const copy = useMemoryText();
  const invalidate = useInvalidate();
  return (err: unknown, fallback: string) => {
    const message = err instanceof ApiError ? err.message : fallback;
    if (err instanceof ApiError && err.status === 409) {
      toast.error(message, { action: { label: copy('Reload'), onClick: () => invalidate('snapshot', 'memory', 'memoryProposals') } });
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

export function ConfirmChoice({ open, pending, title, description, confirmLabel, cancelLabel, onConfirm, onClose }: { open: boolean; pending: boolean; title: string; description: string; confirmLabel: string; cancelLabel: string; onConfirm: () => void; onClose: () => void }) {
  const copy = useMemoryText();
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
          <LoadingButton variant='action' size='control' data-tour='memory-access-confirm' loading={pending} loadingLabel={copy('Saving…')} onClick={onConfirm}>
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
  const copy = useMemoryText();
  const locale = useGenUiLocale();
  const t = (en: string, hant: string, hans: string) => locale.language === 'zh-Hant' ? hant : locale.language === 'zh-Hans' ? hans : en;
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const saveError = useSaveError();
  const decidedLine = useDecidedLine(egress?.decidedAt ?? null, egress?.decidedBy ?? null, isOwner);
  const choice = useConfirmedChoice();

  if (!egress) {
    return <AccessRow title={copy('Cloud model access')} status='warning' badge={copy('Unavailable')} description={copy('Couldn’t load this setting.')} />;
  }

  const shared = egress.sharedFiles ?? [];
  const privacy = (egress.shareablePrivacy ?? []).map((value) => value.replace(/_/g, ' '));
  const withheld = egress.withheldBoundaries;
  const files = shared.length > 0 ? listNames(shared, egress.cloud ? 'and' : 'or') : t('your memory', '你的記憶', '你的记忆');
  const allFiles = shared.length > 0 ? listNames(shared, 'and') : t('your memory', '你的記憶', '你的记忆');
  const boundaryRule =
    (privacy.length > 0 && shared.includes('BOUNDARIES.md') ? t(` Only boundaries marked ${listNames(privacy, 'or')} are included.`, ' 僅包含 public 或 workspace_only 分類的界線。', ' 仅包含 public 或 workspace_only 分类的边界。') : '') +
    (withheld > 0 ? t(` ${withheld} private or local-only boundaries stay out.`, ` ${withheld} 項私人或僅限本機的界線不會送出。`, ` ${withheld} 项私人或仅限本机的边界不会发送。`) : '');

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
          saveError(err, copy('The sharing choice could not be saved.'));
        }
      }
    );
  }

  const description = egress.cloud
    ? t(`The cloud model may receive ${files}, subject to voice selection, source grants and prompt limits.`, `雲端模型可接收 ${files}，實際內容取決於語氣選擇、來源授權及提示上限。`, `云端模型可接收 ${files}，实际内容取决于语气选择、来源授权及提示上限。`) + boundaryRule
    : t(`The cloud model does not receive ${files}.`, `雲端模型不會接收 ${files}。`, `云端模型不会接收 ${files}。`);

  return (
    <>
      <AccessRow
        title={copy('Cloud model access')}
        status={egress.cloud ? 'success' : 'neutral'}
        badge={egress.cloud ? copy('Shared') : copy('Not shared')}
        description={description}
        note={isOwner ? decidedLine : [copy('Only an owner can change this.'), decidedLine].filter(Boolean).join(' ')}
        control={<Switch checked={egress.cloud} disabled={!isOwner || act.isPending || !snapshot.data} onCheckedChange={choice.ask} ariaLabel={copy('Let the cloud model read your memory files')} label={copy('Allow')} />}
      />
      {isOwner && (
        <ConfirmChoice
          open={choice.open}
          pending={act.isPending}
          title={choice.requested ? copy('Let the cloud model read your memory files?') : copy('Stop sharing memory files with the cloud model?')}
          description={
            choice.requested
              ? t(`The cloud model may receive ${allFiles} for this workspace, subject to voice selection, source grants and prompt limits.${boundaryRule}`, `允許此工作區的雲端模型接收 ${allFiles}，仍須遵從語氣選擇、來源授權及提示上限。${boundaryRule}`, `允许此工作区的云端模型接收 ${allFiles}，仍须遵从语气选择、来源授权及提示上限。${boundaryRule}`)
              : t(`The cloud model will stop receiving ${allFiles}. Local route permissions remain unchanged.`, `雲端模型將停止接收 ${allFiles}。本機路徑權限維持不變。`, `云端模型将停止接收 ${allFiles}。本机路径权限保持不变。`)
          }
          confirmLabel={choice.requested ? copy('Allow cloud access') : copy('Stop sharing')}
          cancelLabel={choice.requested ? copy('Keep it off') : copy('Keep sharing')}
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
 * The owner's confirmation for photo and video reading (chat-context SPEC §8.1, §13). Names the processors from the
 * server, says it applies to everyone and that notes are kept; turning it off deletes the notes. Also opened from a
 * chip (S26), so it is exported.
 */
export function MediaConsentConfirm({ open, allow, pending, media, creditMode = false, onConfirm, onClose }: { open: boolean; allow: boolean; pending: boolean; media: MediaConsent | undefined; creditMode?: boolean; onConfirm: () => void; onClose: () => void }) {
  const vision = media?.current.vision?.label ?? 'the photo reader';
  const image = media?.current.image?.label ?? 'the image editor';
  return (
    <ConfirmChoice
      open={open}
      pending={pending}
      title={allow ? 'Allow Rafii to look at photos and videos?' : 'Turn off photo reading?'}
      description={
        allow
          ? `This applies to everyone in this workspace. Photos and video frames marked Reference are sent to ${vision} to describe them, and Rafii's notes are shared with the writer you choose. Photos you ask Rafii to edit are sent to ${image}. Notes are kept with each photo until you turn this off.${creditMode ? ' Each read uses credits.' : ''}`
          : 'Rafii stops looking at photos and videos and deletes the notes it kept.'
      }
      confirmLabel={allow ? 'Allow' : 'Turn off'}
      cancelLabel='Cancel'
      onConfirm={onConfirm}
      onClose={onClose}
    />
  );
}

function MediaRow({ media, isOwner }: { media: MediaConsent | undefined; isOwner: boolean }) {
  const snapshot = useSnapshot();
  const act = useAct();
  const invalidate = useInvalidate();
  const saveError = useSaveError();
  const decidedLine = useDecidedLine(media?.decidedAt ?? null, media?.decidedBy ?? null, isOwner);
  const choice = useConfirmedChoice();

  if (!media) {
    return <AccessRow title='Photos and videos' status='warning' badge='Unavailable' description='Couldn’t load this setting.' />;
  }
  // A new reader needs the owner's OK again; until then nothing is sent, so the row reads Off.
  const allowed = media.cloud && !media.reconfirm;

  // Sent only from the dialog's confirm button, after the owner has read what is sent and to whom.
  function decide(cloud: boolean) {
    act.mutate(
      { revision: snapshot.data?.revision ?? 0, action: 'media_egress', payload: { cloud, confirmed: true } },
      {
        onSuccess: () => {
          choice.close();
          invalidate('memory');
        },
        onError: (err) => {
          choice.close();
          saveError(err, 'The photo reading choice could not be saved.');
        }
      }
    );
  }

  const pendingNew = media.cloud && media.reconfirm ? 'The workspace owner needs to allow the new photo reader.' : null;
  const note = [pendingNew, isOwner ? null : 'Only an owner can change this.', decidedLine].filter(Boolean).join(' ') || null;
  return (
    <>
      <AccessRow
        title='Photos and videos'
        status={allowed ? 'success' : 'neutral'}
        badge={allowed ? 'Allowed' : 'Off'}
        description='Let Rafii look at photos and videos you attach, to write about what’s in them.'
        note={note}
        control={<Switch checked={allowed} disabled={!isOwner || act.isPending || !snapshot.data} onCheckedChange={choice.ask} ariaLabel='Let Rafii look at photos and videos you attach' label='Allow' />}
      />
      {isOwner && <MediaConsentConfirm open={choice.open} allow={choice.requested} pending={act.isPending} media={media} onConfirm={() => decide(choice.requested)} onClose={choice.close} />}
    </>
  );
}

/**
 * Who reads the memory files besides routes on the person's own machine: the cloud model and web research,
 * each an owner decision with its real state and consequence. A setting the API leaves out reads Unavailable, never Off.
 */
export function AccessCard({ className, memoryOnly = false }: { className?: string; memoryOnly?: boolean }) {
  const copy = useMemoryText();
  const memory = useMemory();
  const models = useModels();
  const isOwner = checkAccess(useWorkspaceAccess(), { permission: 'owner' });
  // Photo reading shows only where it can work (SPEC §5.11: route configured, priced and the flag on).
  const mediaAvailable = Boolean(models.data?.attachments?.notes.available);

  return (
    <Panel
      material='glass'
      data-tour='memory-access'
      titleId='memory-access-title'
      title={copy('Who reads these files')}
      description={copy('Eligible files depend on voice selection, route permissions and prompt limits. An owner controls cloud access.')}
      className={className}
      bodyClassName='gap-2'
    >
      {memory.data ? (
        <>
          <CloudRow egress={memory.data.egress} isOwner={isOwner} />
          {!memoryOnly && <ResearchRow research={memory.data.research} isOwner={isOwner} />}
          {!memoryOnly && mediaAvailable && <MediaRow media={memory.data.media} isOwner={isOwner} />}
        </>
      ) : memory.isLoading ? (
        <div className='flex flex-col gap-2' role='status' aria-label={copy('Loading access settings')}>
          <Skeleton className='h-20 w-full rounded-[var(--rafii-radius-control)]' />
          <Skeleton className='h-20 w-full rounded-[var(--rafii-radius-control)]' />
        </div>
      ) : (
        <Unavailable message={copy('Couldn’t load access settings.')} query={memory} />
      )}
    </Panel>
  );
}
