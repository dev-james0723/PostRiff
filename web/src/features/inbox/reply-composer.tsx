'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { CONTROL_48, DIALOG_ELEVATED, DIALOG_FOOTER_PLAIN, STATEFUL_ACTION, STATEFUL_GLASS } from '@/features/channels/rafii-materials';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Thread } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { cn } from '@/lib/utils';
import { InboxLevelBadge } from './level-badge';
import { authorLabel, modelWrote, originLabel, type ReplyPreview, type ReplyRecord, type SavedDraft } from './model';

/** The API's reply limit (`audience.py` REPLY_LIMIT). */
const REPLY_LIMIT = 500;

export interface ComposerState {
  text: string;
  draft: SavedDraft | null;
}

/** The request this composer is waiting on, so only the button that started it shows progress. */
type Pending = 'starter' | 'save' | 'review' | 'approve';

function errorMessage(error: unknown, fallback: string) {
  return error instanceof ApiError ? error.message : fallback;
}

function manifestText(preview: ReplyPreview | null): string | null {
  const text = preview?.manifest.text;
  return typeof text === 'string' ? text : null;
}

/** One sentence for someone who cannot do every step, or null when they can. */
export function permissionSentence(canEdit: boolean, canReply: boolean) {
  if (canEdit && canReply) return null;
  if (canEdit) return 'Approving needs the reply permission. Ask a workspace owner.';
  if (canReply) return 'Writing drafts needs the edit permission.';
  return 'Replying needs the edit and reply permissions.';
}

/**
 * The reply composer is the one glass work surface of a conversation (DNA §21.5): a borderless
 * field, quiet glass secondaries and the single inverted commitment action, "Review & approve".
 * Text stays keyed by thread in the page, so switching comments never loses a draft.
 */
export function ReplyComposer({
  thread,
  accountLabel,
  platform,
  permalink,
  state,
  onChange,
  onApproved,
  canEdit,
  canReply
}: {
  thread: Thread;
  accountLabel: string;
  platform: string;
  permalink: string | null;
  state: ComposerState;
  onChange: (patch: Partial<ComposerState>) => void;
  onApproved: (reply: ReplyRecord) => void;
  canEdit: boolean;
  canReply: boolean;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [pending, setPending] = useState<Pending | null>(null);
  const [reviewPhase, setReviewPhase] = useState<'saving' | 'preparing'>('preparing');
  // A short "Saved" on the button after a manual save; cleared by the timer or by editing the text.
  const [saved, setSaved] = useState(false);
  const [preview, setPreview] = useState<ReplyPreview | null>(null);
  const { text, draft } = state;
  const busy = pending !== null;
  const trimmed = text.trim();
  // The textarea matches the saved draft exactly: that saved text is what a review shows and what gets approved.
  const inSync = draft !== null && trimmed === draft.text;
  const unsaved = trimmed.length > 0 && !inSync;
  const approvedText = manifestText(preview);
  // The server refuses an approval without a provider account on record (`audience.py` approve_reply).
  const accountMissing = preview !== null && !preview.manifest.providerAccountId;
  const sentence = permissionSentence(canEdit, canReply);

  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 1600);
    return () => window.clearTimeout(timer);
  }, [saved]);

  async function persist(): Promise<SavedDraft> {
    const result = await api.draftReply(workspaceId, thread.threadId, { origin: 'manual', text: trimmed });
    const next: SavedDraft = { draftId: result.draftId, text: result.text, origin: result.origin, label: result.label };
    // The server trims what it stores; the textarea takes the stored text so the two never drift apart.
    onChange({ text: result.text, draft: next });
    return next;
  }

  async function save() {
    setPending('save');
    setSaved(false);
    try {
      await persist();
      setSaved(true);
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't save the reply."));
    } finally {
      setPending(null);
    }
  }

  async function insertStarter() {
    const previous = text;
    setPending('starter');
    setSaved(false);
    try {
      const result = await api.draftReply(workspaceId, thread.threadId, { origin: 'ai_fixture' });
      onChange({ text: result.text, draft: { draftId: result.draftId, text: result.text, origin: result.origin, label: result.label } });
      if (previous.trim() && previous.trim() !== result.text) {
        toast('Starter line inserted', {
          description: 'It replaced your text.',
          action: { label: 'Undo', onClick: () => onChange({ text: previous }) }
        });
      }
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't insert a starter line."));
    } finally {
      setPending(null);
    }
  }

  async function review() {
    setPending('review');
    try {
      let current = draft;
      if (!current || !inSync) {
        setReviewPhase('saving');
        current = await persist();
      }
      setReviewPhase('preparing');
      const result = await api.replyPreview(workspaceId, current.draftId);
      setPreview({ draftId: current.draftId, ...result });
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't prepare the review."));
    } finally {
      setPending(null);
    }
  }

  async function approve() {
    if (!preview || approvedText === null) return;
    setPending('approve');
    try {
      const result = await api.approveReply(workspaceId, preview.draftId, preview.digest);
      // No toast: the approved reply appears in the thread with its status.
      setPreview(null);
      onChange({ text: '', draft: null });
      onApproved({ draftId: result.draftId, status: result.status, text: approvedText, origin: draft?.origin, label: draft?.label, updatedAt: null });
      void client.invalidateQueries({ queryKey: keys.audience(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    } catch (error) {
      toast.error(errorMessage(error, "Couldn't approve the reply."));
      if (error instanceof ApiError && error.status === 409) {
        // The draft changed or was already approved: this review is stale.
        setPreview(null);
        void client.invalidateQueries({ queryKey: keys.audience(workspaceId) });
      }
    } finally {
      setPending(null);
    }
  }

  const reviewEnabled = canReply && !busy && (inSync || (unsaved && canEdit));
  const starterLabel = modelWrote(draft?.origin) ? 'Suggest another' : 'Insert starter line';
  let draftLine: string | null = null;
  if (draft && inSync) draftLine = `Draft saved · ${originLabel(draft.origin, draft.label)}`;
  else if (unsaved && canEdit) draftLine = 'Unsaved changes';

  return (
    <Surface material='glass' radius='card' padding='sm' className='flex flex-col gap-3' data-tour='inbox-composer'>
      {/* The field material sits on the wrapper so the textarea keeps its own focus and disabled behaviour. */}
      <div className='rafii-field relative rounded-[var(--rafii-radius-control)] outline-offset-2 focus-within:outline-2 focus-within:outline-foreground'>
        <Textarea
          rows={3}
          value={text}
          readOnly={!canEdit || busy}
          onChange={(event) => {
            onChange({ text: event.target.value });
            setSaved(false);
          }}
          placeholder={canEdit ? `Reply to ${authorLabel(thread.author)}…` : 'You can’t write replies'}
          maxLength={REPLY_LIMIT}
          aria-label='Your reply'
          aria-describedby={`reply-limit-${thread.threadId}`}
          className='min-h-24 rounded-[inherit] border-0 bg-transparent px-3.5 pt-3 pb-7 focus-visible:border-transparent focus-visible:ring-0 dark:bg-transparent dark:disabled:bg-transparent'
        />
        <span id={`reply-limit-${thread.threadId}`} className='text-muted-foreground pointer-events-none absolute right-3 bottom-2 text-xs tabular-nums'>
          <DigitSwap value={REPLY_LIMIT - text.length} />
          <span className='sr-only'> characters left</span>
        </span>
      </div>
      <div className='flex flex-wrap gap-2'>
        <StatefulButton
          variant='outline'
          className={cn(STATEFUL_GLASS, CONTROL_48)}
          state={pending === 'starter' ? 'loading' : 'idle'}
          loadingText='Inserting…'
          icon={<Icons.text className='size-4' />}
          disabled={!canEdit || busy}
          onClick={() => void insertStarter()}
        >
          {starterLabel}
        </StatefulButton>
        <StatefulButton
          variant='outline'
          className={cn(STATEFUL_GLASS, CONTROL_48)}
          state={pending === 'save' ? 'loading' : saved ? 'success' : 'idle'}
          loadingText='Saving…'
          successText='Saved'
          disabled={!canEdit || busy || !unsaved}
          onClick={() => void save()}
        >
          Save draft
        </StatefulButton>
        <StatefulButton
          variant='primary'
          className={cn(STATEFUL_ACTION, CONTROL_48, 'sm:ml-auto')}
          state={pending === 'review' ? 'loading' : 'idle'}
          loadingText={reviewPhase === 'saving' ? 'Saving…' : 'Preparing review…'}
          disabled={!reviewEnabled}
          onClick={() => void review()}
        >
          Review & approve
        </StatefulButton>
      </div>
      {draftLine && <p className='text-muted-foreground text-xs'>{draftLine}</p>}
      {sentence && <p className='text-muted-foreground text-xs leading-relaxed'>{sentence}</p>}

      <Dialog
        open={preview !== null}
        onOpenChange={(open) => {
          if (!open && pending !== 'approve') setPreview(null);
        }}
      >
        <DialogContent className={cn(DIALOG_ELEVATED, 'sm:max-w-md')}>
          <DialogHeader>
            <DialogTitle className='text-xl font-medium tracking-tight'>Approve reply?</DialogTitle>
            <DialogDescription>This exact text, from this account, is what gets approved.</DialogDescription>
          </DialogHeader>
          <dl className='grid gap-3 text-sm'>
            <div className='grid gap-1'>
              <dt className='text-muted-foreground text-xs'>Account</dt>
              <dd className='flex items-center gap-1.5'>
                <ChannelIcon platform={platform} name={platform} size='xs' />
                {accountLabel} · {platform}
              </dd>
            </div>
            <div className='grid gap-1'>
              <dt className='text-muted-foreground text-xs'>Replying to {authorLabel(thread.author)}</dt>
              <dd className='text-muted-foreground line-clamp-2 break-words'>{thread.text}</dd>
            </div>
            <div className='grid gap-1'>
              <dt className='text-muted-foreground text-xs'>Reply</dt>
              <dd>
                {approvedText !== null ? (
                  <blockquote className='rafii-quiet rounded-[var(--rafii-radius-control)] px-3.5 py-2.5 break-words whitespace-pre-wrap'>{approvedText}</blockquote>
                ) : (
                  <span className='text-destructive'>Couldn&apos;t load the reply text. Close and try again.</span>
                )}
              </dd>
            </div>
            <div className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
              <span className='flex items-center gap-1'>
                Reply <InboxLevelBadge level={preview?.replyLevel} />
              </span>
            </div>
          </dl>
          {accountMissing ? (
            <p className='text-destructive text-xs'>
              Reconnect {accountLabel} on {platform} before approving.
            </p>
          ) : preview?.replyLevel === 'Direct' ? (
            <p className='text-muted-foreground text-xs leading-relaxed'>Sending isn&apos;t available yet. Approving doesn&apos;t post to {platform}.</p>
          ) : (
            <p className='text-muted-foreground text-xs leading-relaxed'>
              Rafii can&apos;t send replies for {accountLabel}.
              {permalink && (
                <>
                  {' '}
                  <a href={permalink} target='_blank' rel='noreferrer' className='text-foreground underline underline-offset-2'>
                    Reply on {platform} ↗
                  </a>
                </>
              )}
            </p>
          )}
          <DialogFooter className={DIALOG_FOOTER_PLAIN}>
            <Button variant='glass' size='control' disabled={pending === 'approve'} onClick={() => setPreview(null)}>
              Cancel
            </Button>
            <StatefulButton
              variant='primary'
              className={cn(STATEFUL_ACTION, CONTROL_48)}
              state={pending === 'approve' ? 'loading' : 'idle'}
              loadingText='Approving…'
              disabled={busy || !canReply || approvedText === null || accountMissing || preview?.replyLevel !== 'Direct'}
              onClick={() => void approve()}
            >
              {preview?.replyLevel === 'Direct' ? 'Approve reply' : 'Not available'}
            </StatefulButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Surface>
  );
}
