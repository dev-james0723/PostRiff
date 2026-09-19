'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useState } from 'react';
import { toast } from 'sonner';
import { ChannelIcon } from '@/components/channel-icon';
import { Icons } from '@/components/icons';
import { StatefulButton } from '@/components/motion/button';
import { DigitSwap } from '@/components/motion/digit-swap';
import { Button } from '@/components/ui/button';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Textarea } from '@/components/ui/textarea';
import { ApiError } from '@/lib/api/client';
import { keys } from '@/lib/api/hooks';
import type { Thread } from '@/lib/api/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { InboxLevelBadge } from './level-badge';
import { authorLabel, modelWrote, originLabel, replyStatusView, type ReplyPreview, type ReplyRecord, type SavedDraft } from './model';

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
  if (canEdit) return 'You can write and save replies; approving one needs the reply permission, which a workspace owner can grant.';
  if (canReply) return 'You can approve replies, but writing and saving a draft needs the edit permission.';
  return 'You can read comments here; writing a reply needs the edit permission and approving one needs the reply permission.';
}

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
      toast.error(errorMessage(error, 'The reply could not be saved.'));
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
          description: 'It replaced the text you had written.',
          action: { label: 'Undo', onClick: () => onChange({ text: previous }) }
        });
      }
    } catch (error) {
      toast.error(errorMessage(error, 'The starter line could not be inserted.'));
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
      toast.error(errorMessage(error, 'The review could not be prepared.'));
    } finally {
      setPending(null);
    }
  }

  async function approve() {
    if (!preview || approvedText === null) return;
    setPending('approve');
    try {
      const result = await api.approveReply(workspaceId, preview.draftId, preview.digest);
      toast.success(`Reply ${replyStatusView(result.status).label.toLowerCase()}`);
      setPreview(null);
      onChange({ text: '', draft: null });
      onApproved({ draftId: result.draftId, status: result.status, text: approvedText, origin: draft?.origin, label: draft?.label, updatedAt: null });
      void client.invalidateQueries({ queryKey: keys.audience(workspaceId) });
      void client.invalidateQueries({ queryKey: keys.audit(workspaceId) });
    } catch (error) {
      toast.error(errorMessage(error, 'The reply could not be approved.'));
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
  const starterLabel = modelWrote(draft?.origin) ? 'Suggest another reply' : 'Insert a starter line';
  let draftLine: string | null = null;
  if (draft && inSync) draftLine = `Draft saved · ${originLabel(draft.origin, draft.label)}`;
  else if (draft && unsaved) draftLine = 'Changed since the last save · a review saves this text first';
  else if (!draft && unsaved && canEdit) draftLine = 'Not saved yet';

  return (
    <div className='flex flex-col gap-2' data-tour='inbox-composer'>
      <div className='relative'>
        <Textarea
          rows={3}
          value={text}
          readOnly={!canEdit || busy}
          onChange={(event) => {
            onChange({ text: event.target.value });
            setSaved(false);
          }}
          placeholder={canEdit ? `Reply to ${authorLabel(thread.author)}…` : 'Writing a reply needs the edit permission'}
          maxLength={REPLY_LIMIT}
          aria-label='Your reply'
          aria-describedby={`reply-limit-${thread.threadId}`}
          className='pb-6'
        />
        <span id={`reply-limit-${thread.threadId}`} className='text-muted-foreground pointer-events-none absolute right-2.5 bottom-1.5 text-[11px] tabular-nums'>
          <DigitSwap value={REPLY_LIMIT - text.length} />
          <span className='sr-only'> characters left</span>
        </span>
      </div>
      <div className='flex flex-wrap gap-2'>
        <StatefulButton
          variant='outline'
          size='sm'
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
          size='sm'
          state={pending === 'save' ? 'loading' : saved ? 'success' : 'idle'}
          loadingText='Saving…'
          successText='Saved'
          disabled={!canEdit || busy || !unsaved}
          onClick={() => void save()}
        >
          Save draft
        </StatefulButton>
        <StatefulButton
          size='sm'
          state={pending === 'review' ? 'loading' : 'idle'}
          loadingText={reviewPhase === 'saving' ? 'Saving…' : 'Preparing review…'}
          disabled={!reviewEnabled}
          onClick={() => void review()}
        >
          Review & approve
        </StatefulButton>
      </div>
      {draftLine && <p className='text-muted-foreground text-xs'>{draftLine}</p>}
      {sentence && <p className='text-muted-foreground text-xs'>{sentence}</p>}

      <Dialog
        open={preview !== null}
        onOpenChange={(open) => {
          if (!open && pending !== 'approve') setPreview(null);
        }}
      >
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Approve this reply</DialogTitle>
            <DialogDescription>Check the account, the comment and the exact text. This text is what gets approved.</DialogDescription>
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
                  <blockquote className='border-l-2 pl-3 break-words whitespace-pre-wrap'>{approvedText}</blockquote>
                ) : (
                  <span className='text-destructive'>The server did not return the reply text, so this reply cannot be approved.</span>
                )}
              </dd>
            </div>
            <div className='text-muted-foreground flex flex-wrap items-center gap-2 text-xs'>
              <span>
                Digest <span className='font-mono'>{preview?.digest.slice(0, 12)}…</span>
              </span>
              <span className='flex items-center gap-1'>
                Reply <InboxLevelBadge level={preview?.replyLevel} />
              </span>
            </div>
          </dl>
          {accountMissing ? (
            <p className='text-destructive text-xs'>
              The connection for {accountLabel} has no {platform} account on record, so this reply cannot be approved.
            </p>
          ) : preview?.replyLevel === 'Direct' ? (
            <p className='text-muted-foreground text-xs'>Approving records your decision. Sending is not switched on yet, so nothing is posted to {platform} for now.</p>
          ) : (
            <p className='text-muted-foreground text-xs'>
              Replies are {preview?.replyLevel ?? 'Unsupported'} for {accountLabel}, so PostRiff cannot send this one.
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
          <DialogFooter>
            <Button variant='outline' disabled={pending === 'approve'} onClick={() => setPreview(null)}>
              Cancel
            </Button>
            <StatefulButton
              state={pending === 'approve' ? 'loading' : 'idle'}
              loadingText='Approving…'
              disabled={busy || !canReply || approvedText === null || accountMissing || preview?.replyLevel !== 'Direct'}
              onClick={() => void approve()}
            >
              {preview?.replyLevel === 'Direct' ? 'Approve reply' : 'Sending not available'}
            </StatefulButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
