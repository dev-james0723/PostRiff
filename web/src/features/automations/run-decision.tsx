'use client';

/**
 * Approve, request changes to, or reject one post of an automation run (`raffi_run_decide`, orchestration §4).
 *
 * Approving shows the exact draft the person approves, the unknown claims that stay out of it, its warnings and the
 * sources whose public use the approval covers, and needs an explicit tick. The payload carries exactly what was
 * shown (the variant revision, the unknowns, the warnings and each source's current facts digest), so the server
 * refuses the approval if anything changed in between. Nothing here publishes: the server commits an approved post
 * at its time, after its own checks.
 */
import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { Checkbox } from '@/components/motion/checkbox';
import { RafiiDialog, RafiiDialogBody, RafiiDialogContent, RafiiDialogFooter, RafiiDialogHeader, Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Textarea } from '@/components/ui/textarea';
import { factsDigest } from '@/features/ideas/use-sources';
import { ApiError } from '@/lib/api/client';
import { useSnapshot } from '@/lib/api/hooks';
import type { RecurringOccurrence, RunItem, Snapshot, SnapshotSource } from '@/lib/api/types';
import { languageLabel } from '@/lib/locales';
import { runLabel } from './schedule';
import { itemName } from './workflow';

export type RunDecision = 'approve' | 'revise' | 'reject';

export interface DecisionTarget {
  run: RecurringOccurrence;
  item: RunItem;
  decision: RunDecision;
  automationName: string;
  timeZone: string;
}

const NOTE_LIMIT = 280;

const TITLES: Record<RunDecision, { title: string; accent: string; action: string; done: string }> = {
  approve: { title: 'Approve', accent: 'this post?', action: 'Approve post', done: 'Approved. It publishes at its time after a final check.' },
  revise: { title: 'Request', accent: 'changes', action: 'Request changes', done: 'Changes requested. It will not publish until a new version is approved.' },
  reject: { title: 'Reject', accent: 'this post?', action: 'Reject post', done: 'Rejected. This post will not be published.' }
};

/** The draft's `rewrite_approval` sources and each one's current facts digest (null while hashing or unavailable). */
function useSourceDigests(sources: SnapshotSource[]) {
  const [digests, setDigests] = useState<Record<string, string | null> | null>(null);
  const signature = JSON.stringify(sources.map((s) => [s.id, (s.facts ?? []).filter((f) => f.approved).map((f) => [f.id, f.text])]));
  useEffect(() => {
    let disposed = false;
    const rows = JSON.parse(signature) as [string, [string, string][]][];
    void Promise.all(rows.map(async ([id, facts]) => [id, await factsDigest(facts.map(([factId, text]) => ({ id: factId, text, approved: true })))] as const)).then((pairs) => {
      if (!disposed) setDigests(Object.fromEntries(pairs));
    });
    return () => {
      disposed = true;
    };
  }, [signature]);
  return digests;
}

export function RunDecisionDialog({ target, onClose, act }: { target: DecisionTarget | null; onClose: () => void; act: (action: string, payload: Record<string, unknown>) => Promise<Snapshot> }) {
  return (
    <RafiiDialog open={target !== null} onOpenChange={(next) => !next && onClose()}>
      {target && <DecisionContent key={`${target.run.id}:${target.item.key}:${target.decision}`} target={target} onClose={onClose} act={act} />}
    </RafiiDialog>
  );
}

function DecisionContent({ target, onClose, act }: { target: DecisionTarget; onClose: () => void; act: (action: string, payload: Record<string, unknown>) => Promise<Snapshot> }) {
  const { run, item, decision, automationName, timeZone } = target;
  const snapshot = useSnapshot();
  const state = snapshot.data?.state;
  const variant = item.variantId ? state?.variants?.find((v) => v.id === item.variantId) : undefined;
  const rewriteSources = useMemo(() => (state?.sources ?? []).filter((s) => variant?.sourceIds.includes(s.id) && s.sourcePolicy === 'rewrite_approval'), [state?.sources, variant?.sourceIds]);
  const digests = useSourceDigests(rewriteSources);
  const [confirmed, setConfirmed] = useState(false);
  const [note, setNote] = useState('');
  const [sending, setSending] = useState(false);
  const text = TITLES[decision];
  const when = item.publishAt ? runLabel(item.publishAt * 1000, timeZone) : null;
  const edited = variant && typeof item.variantRevision === 'number' && variant.revision !== item.variantRevision;
  const digestsReady = digests !== null && rewriteSources.every((s) => typeof digests[s.id] === 'string');
  const unknowns = variant?.unknowns ?? [];
  const warnings = variant?.warnings ?? [];

  const blocked =
    decision === 'approve'
      ? !variant
        ? 'The draft for this post is not in the workspace, so there is nothing exact to approve. Open the run’s drafts instead.'
        : variant.rejected
          ? 'This draft was set aside, so it cannot be approved.'
          : rewriteSources.length > 0 && digests !== null && !digestsReady
            ? 'This browser cannot compute the facts fingerprint the approval needs. Try another browser.'
            : null
      : null;
  const ready = !sending && !blocked && (decision !== 'approve' || (confirmed && digestsReady)) && (decision !== 'revise' || note.trim().length > 0);

  async function send() {
    if (!ready) return;
    setSending(true);
    try {
      await act('raffi_run_decide', {
        occurrenceId: run.id,
        itemKey: item.key,
        decision,
        confirmed: true,
        variantRevision: variant?.revision ?? item.variantRevision ?? null,
        excludedUnknowns: unknowns,
        acknowledgedWarnings: warnings,
        sourceUse: rewriteSources.flatMap((s) => (digests?.[s.id] ? [{ sourceId: s.id, factsDigest: digests[s.id] }] : [])),
        ...(note.trim() ? { note: note.trim() } : {})
      });
      toast.success(text.done);
      onClose();
    } catch (error) {
      if (error instanceof ApiError && error.code === 'approval_expired') toast.error('Too late to approve: its publish time has passed, so it will not be published.');
      else toast.error(error instanceof ApiError ? error.message : 'That did not go through. Try again.');
      setSending(false);
    }
  }

  const intro =
    decision === 'approve'
      ? when
        ? `You approve this exact text for ${itemName(item)} at ${when}. Rafii checks the account again before it posts; if anything changed, it does not post.`
        : 'You approve this exact text.'
      : decision === 'revise'
        ? 'Tell Rafii what to change. This post will not publish until a new version is approved.'
        : 'This post will not be published. The other posts in this run are not affected.';

  return (
    <RafiiDialogContent size='md'>
      <RafiiDialogHeader eyebrow={automationName} title={text.title} accent={text.accent} intro={intro} />
      <RafiiDialogBody className='flex flex-col gap-4'>
        <p className='flex flex-wrap items-center gap-2 text-sm'>
          <ChannelIcon platform={item.platform} size='sm' className='rounded-md' />
          <span className='min-w-0 break-words font-medium'>{itemName(item)}</span>
          <span className='text-muted-foreground'>· {languageLabel(item.language)}</span>
          {when && <span className='text-muted-foreground'>· {when}</span>}
        </p>
        {variant ? (
          <Surface material='paper' radius='control' padding='sm'>
            <p className='rafii-eyebrow mb-1.5'>The exact post</p>
            <p className='text-sm leading-relaxed break-words whitespace-pre-wrap' data-decision-text>
              {variant.text}
            </p>
          </Surface>
        ) : (
          <p className='text-muted-foreground text-sm'>The draft for this post is not in the workspace.</p>
        )}
        {edited && <Note>This draft was edited after Rafii wrote it. You are deciding on the text as it is now.</Note>}
        {variant?.proposedUpdate && <Note>A newer version of this draft is waiting in Queue → Drafts. This decision is about the text shown here.</Note>}
        {decision === 'approve' && unknowns.length > 0 && (
          <section className='flex flex-col gap-1.5'>
            <h3 className='text-sm font-medium'>Left out because they could not be checked</h3>
            <ul className='text-muted-foreground flex list-disc flex-col gap-1 pl-5 text-sm'>
              {unknowns.map((unknown) => (
                <li key={unknown}>{unknown}</li>
              ))}
            </ul>
            <p className='text-muted-foreground text-xs'>Approving confirms these stay out of the post.</p>
          </section>
        )}
        {decision === 'approve' && warnings.length > 0 && (
          <section className='flex flex-col gap-1.5'>
            <h3 className='text-sm font-medium'>Warnings you acknowledge</h3>
            <ul className='flex list-disc flex-col gap-1 pl-5 text-sm'>
              {warnings.map((warning) => (
                <li key={warning}>{warning}</li>
              ))}
            </ul>
          </section>
        )}
        {decision === 'approve' && rewriteSources.length > 0 && (
          <section className='flex flex-col gap-1.5'>
            <h3 className='text-sm font-medium'>Sources this approval covers</h3>
            <ul className='flex flex-col gap-2 text-sm'>
              {rewriteSources.map((source) => {
                const digest = digests?.[source.id];
                const already = Boolean(digest && (source.useApprovals ?? []).some((u) => u.factsDigest === digest));
                const facts = (source.facts ?? []).filter((f) => f.approved);
                return (
                  <li key={source.id} className='flex flex-col gap-0.5'>
                    <span className='font-medium break-words'>{source.title || 'Untitled source'}</span>
                    <span className='text-muted-foreground text-xs'>
                      {already ? 'Public use of its approved facts is already approved.' : `Approving also approves public use of its ${facts.length} approved fact${facts.length === 1 ? '' : 's'}, rewritten in your words.`}
                    </span>
                  </li>
                );
              })}
            </ul>
          </section>
        )}
        {decision !== 'approve' && (
          <div className='flex flex-col gap-1.5'>
            <label htmlFor='run-decision-note' className='text-sm font-medium'>
              {decision === 'revise' ? 'What should change?' : 'Why not (optional)'}
            </label>
            <Textarea id='run-decision-note' value={note} onChange={(e) => setNote(e.target.value.slice(0, NOTE_LIMIT))} maxLength={NOTE_LIMIT} rows={3} className='rafii-field text-base md:text-sm' placeholder={decision === 'revise' ? 'Shorter, and mention the venue' : ''} />
            <span className='text-muted-foreground text-xs'>
              {note.length}/{NOTE_LIMIT}
            </span>
          </div>
        )}
        {blocked && <Note>{blocked}</Note>}
        {decision === 'approve' && !blocked && (
          <Checkbox
            checked={confirmed}
            onCheckedChange={setConfirmed}
            label={when ? `I read this exact post and approve publishing it at ${when}.` : 'I read this exact post and approve it.'}
            className='min-h-11 items-start gap-2.5 [&>span]:text-sm'
          />
        )}
      </RafiiDialogBody>
      <RafiiDialogFooter className='flex-row flex-wrap justify-end gap-2'>
        <Button variant='quiet' size='control' onClick={onClose} disabled={sending}>
          Not now
        </Button>
        <Button variant='action' size='control' disabled={!ready} onClick={() => void send()}>
          {decision === 'approve' ? <Icons.check /> : decision === 'reject' ? <Icons.close /> : <Icons.edit />}
          {sending ? 'Sending…' : text.action}
        </Button>
      </RafiiDialogFooter>
    </RafiiDialogContent>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return (
    <p className='text-muted-foreground flex items-start gap-1.5 text-xs'>
      <Icons.info aria-hidden className='mt-0.5 size-3.5 shrink-0' />
      <span className='min-w-0'>{children}</span>
    </p>
  );
}
