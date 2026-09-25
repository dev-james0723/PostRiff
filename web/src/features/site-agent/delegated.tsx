'use client';

/**
 * Messages the writing pipeline produced when Rafii handed a request to it (a draft run, an automation, a memory
 * preference). The panel shows each one compactly and links to where it lives; the full drafts, previews and plan
 * cards stay on the conversation page and in the Queue.
 */
import Link from 'next/link';
import { useState } from 'react';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { ChatAutomationCard } from '@/features/automations/chat-automation-card';
import { useRun } from '@/features/agent/use-run';
import { ApiError } from '@/lib/api/client';
import { keys, useSnapshot } from '@/lib/api/hooks';
import type { Snapshot } from '@/lib/api/types';
import type { SiteAgentMessageBody } from '@/lib/site-agent/types';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { RichText } from './answer';

const STAGES: Record<string, string> = { queued: 'Waiting for the writer', writing: 'Writing the drafts', drafting: 'Writing the drafts', researched: 'Reading sources' };

function WritingRun({ runId, conversationId, onNavigate }: { runId: string; conversationId: string | null; onNavigate?: () => void }) {
  const run = useRun(runId);
  const snapshot = useSnapshot();
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const [saving, setSaving] = useState(false);
  const [saved, setSaved] = useState<number | null>(null);
  const [error, setError] = useState<string | null>(null);
  if (!run) return <p className='text-muted-foreground text-xs'>Loading the draft run…</p>;
  const variants = run.artifact?.variants ?? [];
  const stage = run.events.filter((e) => e.type === 'progress.updated').at(-1)?.stage;
  const rework = Boolean(run.artifact?.reworkOf);
  // The drafts this run saved: a proposed update on the reworked draft, or new drafts (read from the workspace, so a reload keeps them).
  const results = (snapshot.data?.state.variants ?? []).filter((v) => v.proposedUpdate?.runId === runId || (!v.proposedUpdate && v.runId === runId));

  async function save() {
    if (!run?.artifactHash) return;
    setSaving(true);
    setError(null);
    try {
      const snapshot = client.getQueryData<Snapshot>(keys.snapshot(workspaceId)) ?? (await api.snapshot(workspaceId));
      const applied = await api.applyRun(workspaceId, run.runId, snapshot.revision, run.artifactHash);
      setSaved(applied.variants ?? variants.length);
      await client.invalidateQueries({ queryKey: keys.snapshot(workspaceId) });
    } catch (err) {
      setError(err instanceof ApiError ? err.message : 'The drafts could not be saved.');
    } finally {
      setSaving(false);
    }
  }

  return (
    <Surface material='glass' padding='sm' className='flex flex-col gap-2'>
      {run.status === 'running' || run.status === 'queued' ? (
        <span role='status' className='text-muted-foreground flex items-center gap-2 text-xs'>
          <Icons.spinner className='size-3.5 animate-spin motion-reduce:animate-none' aria-hidden />
          {STAGES[stage ?? ''] ?? 'Writing the drafts'}
        </span>
      ) : run.status === 'failed' || run.status === 'cancelled' ? (
        <span role='status' className='text-sm'>
          {run.status === 'failed' ? (run.events.findLast((e) => e.type === 'run.failed')?.message ?? 'The writer did not finish.') : 'Stopped before the drafts finished.'}
        </span>
      ) : (
        <>
          <span className='text-sm font-medium'>
            {variants.length} draft{variants.length === 1 ? '' : 's'} ready: {Array.from(new Set(variants.map((v) => v.account ? `${v.platform} · ${v.account}` : v.platform))).join(', ')}
          </span>
          <p className='text-muted-foreground text-xs'>
            {rework
              ? 'Saving adds this as a proposed update to your draft: the current text stays until you accept it. Nothing is scheduled or published.'
              : 'They are candidates until you save them. Saving adds them to your drafts; nothing is scheduled or published.'}
          </p>
          <div className='flex flex-wrap items-center gap-2'>
            {run.status === 'applied' || saved !== null ? (
              results.length > 0 ? (
                results.map((v) => (
                  <Link key={v.id} href={`/app/queue?view=drafts&draft=${encodeURIComponent(v.id)}`} onClick={onNavigate} className='rafii-focus text-sm font-medium underline underline-offset-2'>
                    {v.proposedUpdate?.runId === runId ? `Review the update to your ${v.platform} draft` : `Open the ${v.platform} draft`}
                  </Link>
                ))
              ) : (
                <Link href='/app/queue?view=drafts' onClick={onNavigate} className='rafii-focus text-sm font-medium underline underline-offset-2'>
                  Saved{saved !== null ? ` (${saved})` : ''} · Open Drafts
                </Link>
              )
            ) : (
              <Button type='button' variant='action' size='sm' className='min-h-9 px-3' disabled={saving || !run.artifactHash} onClick={() => void save()}>
                {saving ? 'Saving…' : 'Save to drafts'}
              </Button>
            )}
            {conversationId && (
              <Link href={`/app/agent/${conversationId}`} onClick={onNavigate} className='rafii-focus text-xs underline underline-offset-2'>
                Review in conversation
              </Link>
            )}
          </div>
        </>
      )}
      {error && (
        <p role='alert' className='text-destructive text-xs'>
          {error}
        </p>
      )}
    </Surface>
  );
}

export function DelegatedMessage({ body, runId, conversationId, latest, onAsk, onNavigate }: {
  body: SiteAgentMessageBody;
  runId: string | null;
  conversationId: string | null;
  latest: boolean;
  onAsk?: (text: string) => void;
  onNavigate?: () => void;
}) {
  return (
    <div className='flex min-w-0 flex-col gap-2'>
      {body.text && !body.automation && <RichText text={body.text} />}
      {body.automation && <ChatAutomationCard automation={body.automation} reply={body.text} onQuickReply={latest && onAsk ? onAsk : undefined} />}
      {body.memoryProposal && (
        <p className='text-muted-foreground text-xs'>
          Saved as a preference for an owner to remember, reword or dismiss on{' '}
          <Link href='/app/workspace/memory' onClick={onNavigate} className='rafii-focus underline underline-offset-2'>
            Memory
          </Link>
          . It changes nothing until then.
        </p>
      )}
      {runId && !body.automation && !body.memoryProposal && <WritingRun runId={runId} conversationId={conversationId} onNavigate={onNavigate} />}
    </div>
  );
}
