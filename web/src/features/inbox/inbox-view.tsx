'use client';

import { useState } from 'react';
import { toast } from 'sonner';
import PageContainer from '@/components/layout/page-container';
import { Icons } from '@/components/icons';
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

function ThreadCard({ thread, canReply }: { thread: Thread; canReply: boolean }) {
  const { api, workspaceId } = useWorkspaceApi();
  const [text, setText] = useState('');
  const [draft, setDraft] = useState<Draft | null>(null);
  const [preview, setPreview] = useState<{ draftId: string; digest: string; action: string; replyLevel: string } | null>(null);
  const [busy, setBusy] = useState(false);

  async function makeDraft(origin: 'manual' | 'ai_fixture') {
    setBusy(true);
    try {
      const result = await api.draftReply(workspaceId, thread.threadId, { origin, text });
      setDraft(result);
      if (origin === 'ai_fixture') setText(result.text);
      toast.success(`Draft saved · ${result.label}`);
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Could not draft a reply.');
    } finally {
      setBusy(false);
    }
  }

  async function openPreview() {
    if (!draft) return;
    setBusy(true);
    try {
      setPreview({ draftId: draft.draftId, ...(await api.replyPreview(workspaceId, draft.draftId)) });
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'Preview failed.');
    } finally {
      setBusy(false);
    }
  }

  async function send() {
    if (!preview) return;
    setBusy(true);
    try {
      const result = await api.approveReply(workspaceId, preview.draftId, preview.digest);
      toast.success(`${result.status}${result.note ? ` · ${result.note}` : ''}`);
      setPreview(null);
      setDraft(null);
      setText('');
    } catch (err) {
      toast.error(err instanceof ApiError ? err.message : 'The reply could not be approved.');
    } finally {
      setBusy(false);
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className='flex flex-wrap items-center gap-2 text-base'>
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
            <Textarea rows={2} value={text} onChange={(event) => setText(event.target.value)} placeholder='Write your reply…' maxLength={500} aria-label='Your reply' />
            <div className='flex flex-wrap gap-2'>
              <Button variant='outline' size='sm' disabled={busy} onClick={() => void makeDraft('ai_fixture')}>
                <Icons.sparkles className='size-4' /> Suggest (labelled AI)
              </Button>
              <Button variant='outline' size='sm' disabled={busy || !text.trim()} onClick={() => void makeDraft('manual')}>
                Save my reply
              </Button>
              <Button size='sm' disabled={busy || !draft} onClick={() => void openPreview()}>
                Review & send
              </Button>
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
            <Button disabled={busy || preview?.replyLevel !== 'Direct'} onClick={() => void send()}>
              {preview?.replyLevel === 'Direct' ? 'Approve & send' : 'Sending not available'}
            </Button>
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
            {data.threads.map((thread) => (
              <ThreadCard key={thread.threadId} thread={thread} canReply={canReply} />
            ))}
          </div>
          <p className='text-muted-foreground text-xs'>{data.limits}</p>
        </div>
      )}
    </PageContainer>
  );
}
