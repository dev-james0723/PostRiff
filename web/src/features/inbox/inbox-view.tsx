'use client';

import { useEffect, useState } from 'react';
import { motion, useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
import { ChannelIcon } from '@/components/channel-icon';
import { StatefulButton } from '@/components/motion/button';
import { Badge } from '@/components/ui/badge';
import { Button } from '@/components/ui/button';
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from '@/components/ui/card';
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog';
import { Empty, EmptyDescription, EmptyHeader, EmptyMedia, EmptyTitle } from '@/components/ui/empty';
import { Skeleton } from '@/components/ui/skeleton';
import { Textarea } from '@/components/ui/textarea';
import { useAudience } from '@/lib/api/hooks';
import { ApiError } from '@/lib/api/client';
import type { Thread } from '@/lib/api/types';
import { checkAccess, useWorkspaceAccess } from '@/lib/auth/access';
import { EASE_OUT } from '@/lib/ease';
import { relativeTime } from '@/lib/time';
import { useWorkspaceApi } from '@/lib/workspace/provider';

const infoContent = {
  title: 'Real replies, one at a time',
  sections: [
    { title: 'Original thread first', description: 'You always see the comment in context before writing.' },
    {
      title: 'Labelled suggestions',
      description: 'An AI suggestion is marked as such in the draft and never sent on its own. You edit, then approve the exact account, thread and text.'
    },
    { title: 'No bulk, no auto-reply', description: 'Each reply is an individual approval with its own receipt.' }
  ]
};

interface Draft {
  draftId: string;
  text: string;
  label: string;
}

/** The request a thread card is waiting on, so only the button that started it shows a spinner. */
type ReplyAction = 'suggest' | 'save' | 'preview' | 'send';

function ThreadCard({ thread, canReply }: { thread: Thread; canReply: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [text, setText] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<{ draftId: string; digest: string; action: string; replyLevel: string } | null>(null);
  const [pending, setPending] = useState<ReplyAction | null>(null);
  const busy = pending !== null;
  // A short "Saved" on the button after a manual save; cleared by the timer or by editing the text.
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    if (!saved) return;
    const timer = window.setTimeout(() => setSaved(false), 1600);
    return () => window.clearTimeout(timer);
  }, [saved]);

  async function makeDraft(origin: 'manual' | 'ai_fixture') {
    setPending(origin === 'manual' ? 'save' : 'suggest');
    setSaved(false);
    try {
      const result = await api.draftReply(workspaceId, thread.threadId, { origin, text });
      setDraft(result);
      if (origin === 'ai_fixture') setText(result.text);
      if (origin === 'manual') setSaved(true);
      toast.success(`Draft saved · ${result.label}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not draft a reply.');
    } finally {
      setPending(null);
    }
  }

  async function openPreview() {
    if (!draft) return;
    setPending('preview');
    try {
      setPreview({ draftId: draft.draftId, ...(await api.replyPreview(workspaceId, draft.draftId)) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Preview failed.');
    } finally {
      setPending(null);
    }
  }

  async function send() {
    if (!preview) return;
    setPending('send');
    try {
      const result = await api.approveReply(workspaceId, preview.draftId, preview.digest);
      toast.success(`${result.status}${result.note ? ` · ${result.note}` : ''}`);
      setPreview(null);
      setDraft(null);
      setText('');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The reply could not be approved.');
    } finally {
      setPending(null);
    }
  }

  return (
    <Card className='h-full'>
      <CardHeader>
        <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
          <ChannelIcon platform={thread.provider} name={thread.provider} />
          @{thread.author || 'someone'}
          <Badge variant='outline'>{thread.provider}</Badge>
          {thread.tombstoned && <Badge variant='secondary'>removed by provider</Badge>}
        </CardTitle>
        <CardDescription>
          post {thread.providerPostId} · {relativeTime(thread.ingestedAt)}
        </CardDescription>
      </CardHeader>
      <CardContent className='flex flex-col gap-3'>
        <blockquote className='border-l-2 pl-3 text-sm'>{thread.text}</blockquote>
        {thread.replyAvailable && canReply ? (
          <div className='flex flex-col gap-2'>
            <Textarea
              rows={2}
              value={text}
              onChange={(event) => {
                setText(event.target.value);
                setSaved(false);
              }}
              placeholder='Write your reply…'
              maxLength={500}
              aria-label='Your reply'
            />
            <div className='flex flex-wrap gap-2'>
              <StatefulButton
                variant='outline'
                size='sm'
                state={pending === 'suggest' ? 'loading' : 'idle'}
                loadingText='Suggesting…'
                icon={<Icons.sparkles className='size-4' />}
                disabled={busy}
                onClick={() => void makeDraft('ai_fixture')}
              >
                Suggest (labelled AI)
              </StatefulButton>
              <StatefulButton
                variant='outline'
                size='sm'
                state={pending === 'save' ? 'loading' : saved ? 'success' : 'idle'}
                loadingText='Saving…'
                successText='Saved'
                disabled={busy || !text.trim()}
                onClick={() => void makeDraft('manual')}
              >
                Save my reply
              </StatefulButton>
              <StatefulButton size='sm' state={pending === 'preview' ? 'loading' : 'idle'} loadingText='Loading preview…' disabled={busy || !draft} onClick={() => void openPreview()}>
                Review & send
              </StatefulButton>
            </div>
            {draft && <p className='text-muted-foreground text-xs'>Draft saved · {draft.label}</p>}
          </div>
        ) : (
          <p className='text-muted-foreground text-xs'>
            {thread.replyAvailable ? 'You need the reply permission to answer here.' : `Replies are ${thread.replyLevel} for this connection — read-only here.`}
          </p>
        )}
      </CardContent>
      <Dialog open={Boolean(preview)} onOpenChange={(open) => !open && setPreview(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{preview?.action ?? 'Send reply'}</DialogTitle>
            <DialogDescription>
              Reply capability: {preview?.replyLevel}. Digest <span className='font-mono'>{preview?.digest.slice(0, 12)}…</span>
            </DialogDescription>
          </DialogHeader>
          <blockquote className='border-l-2 pl-3 text-sm'>{text}</blockquote>
          <DialogFooter>
            <Button variant='outline' onClick={() => setPreview(null)}>
              Cancel
            </Button>
            <StatefulButton state={pending === 'send' ? 'loading' : 'idle'} loadingText='Sending…' disabled={busy || preview?.replyLevel !== 'Direct'} onClick={() => void send()}>
              {preview?.replyLevel === 'Direct' ? 'Approve & send' : 'Sending not available'}
            </StatefulButton>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </Card>
  );
}

export function InboxView() {
  const audience = useAudience();
  const access = useWorkspaceAccess();
  const canReply = checkAccess(access, { permission: 'reply' });
  const reduce = useReducedMotion();
  const data = audience.data;
  return (
    <PageContainer pageTitle='Inbox' pageDescription='Comments on your published posts, with replies you approve one at a time.' infoContent={infoContent}>
      {audience.isLoading || !data ? (
        <Skeleton className='h-64 w-full' />
      ) : data.threads.length === 0 ? (
        <Empty>
          <EmptyHeader>
            <EmptyMedia variant='icon'>
              <Icons.inbox />
            </EmptyMedia>
            <EmptyTitle>No comments yet</EmptyTitle>
            <EmptyDescription>
              Comments appear for connections whose comments capability is Direct, after a verified publication.
            </EmptyDescription>
          </EmptyHeader>
          {data.capabilities.length > 0 && (
            <ul className='text-muted-foreground mt-2 text-sm'>
              {data.capabilities.map((c) => (
                <li key={c.connectionId}>
                  connection {c.connectionId.slice(0, 8)}… · comments {c.commentsRead}
                </li>
              ))}
            </ul>
          )}
          <p className='text-muted-foreground mt-2 text-xs'>{data.limits}</p>
        </Empty>
      ) : (
        <div className='flex flex-col gap-4'>
          <div className='grid gap-4 xl:grid-cols-2'>
            {data.threads.map((thread, index) => (
              <motion.div
                key={thread.threadId}
                initial={{ opacity: 0, y: 8 }}
                animate={{ opacity: 1, y: 0 }}
                transition={reduce ? { duration: 0 } : { duration: 0.28, delay: Math.min(index * 0.05, 0.3), ease: EASE_OUT }}
              >
                <ThreadCard thread={thread} canReply={canReply} />
              </motion.div>
            ))}
          </div>
          <p className='text-muted-foreground text-xs'>{data.limits}</p>
        </div>
      )}
    </PageContainer>
  );
}
