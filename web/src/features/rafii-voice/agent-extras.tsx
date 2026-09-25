'use client';

/**
 * What an agent answer adds to the site agent's blocks: images Rafii saved (fetched with the session's own
 * credentials — private media never has a public URL), a live checklist while a task still runs, and which
 * specialists helped. Proposals are the site agent's own proposal cards (same blocks, same apply path).
 */
import { useEffect, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import type { AgentResult, GeneratedAsset } from '@/lib/agent-runtime/types';
import { useAgent } from '@/lib/agent-runtime/use-agent';

const STEP_WORDS: Record<string, string> = { planned: 'Not started', running: 'In progress', done: 'Done', needs_user: 'Needs you', blocked: 'Blocked', failed: 'Failed', canceled: 'Cancelled' };

function PrivateImage({ asset }: { asset: GeneratedAsset }) {
  const { api, workspaceId } = useAgent();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let revoked: string | null = null;
    let alive = true;
    api
      .media(workspaceId, asset.assetId)
      .then((blob) => {
        if (!alive) return;
        revoked = URL.createObjectURL(blob);
        setUrl(revoked);
      })
      .catch(() => alive && setFailed(true));
    return () => {
      alive = false;
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [api, workspaceId, asset.assetId]);
  const label = asset.kind === 'edit' ? 'Edited version' : asset.kind === 'variant' ? 'Variant' : 'New image';
  return (
    <figure className='flex flex-col gap-1' data-rafii-asset={asset.assetId}>
      <div className='bg-muted aspect-square w-full max-w-56 overflow-hidden rounded-[var(--rafii-radius-control)]'>
        {url ? (
          // eslint-disable-next-line @next/next/no-img-element -- a private, session-authenticated object URL
          <img src={url} alt={asset.alt} className='size-full object-cover' />
        ) : (
          <span className='text-muted-foreground flex size-full items-center justify-center p-2 text-center text-xs'>{failed ? 'The image could not be loaded.' : 'Loading the image…'}</span>
        )}
      </div>
      <figcaption className='text-muted-foreground text-[11px]'>
        {label} · saved to your library{asset.kind !== 'generated' ? ' · original unchanged' : ''}
        {!asset.verified ? ' · not confirmed' : ''}
      </figcaption>
    </figure>
  );
}

export function AgentExtras({ result, conversationId }: { result: AgentResult; conversationId: string | null }) {
  const { api, workspaceId } = useAgent();
  const running = result.task?.status === 'running';
  const live = useQuery({
    queryKey: ['agent-runtime', 'conversation', workspaceId, conversationId],
    queryFn: () => api.conversationState(workspaceId, conversationId as string),
    enabled: Boolean(running && conversationId),
    refetchInterval: running ? 2500 : false
  });
  const task = (running && live.data?.task?.taskId === result.task?.taskId ? live.data?.task : null) ?? result.task;
  const specialists = Array.from(new Set(result.toolActivity.map((a) => a.specialist).filter(Boolean)));
  return (
    <div className='mt-2 flex flex-col gap-2'>
      {result.generatedAssets.length > 0 && (
        <div className='grid grid-cols-2 gap-2'>
          {result.generatedAssets.map((asset) => (
            <PrivateImage key={asset.assetId} asset={asset} />
          ))}
        </div>
      )}
      {task && running && (
        <ol className='flex flex-col gap-0.5 text-xs' aria-label={`Progress: ${task.title}`} data-rafii-task={task.status}>
          {task.steps.map((step) => (
            <li key={step.id} className='flex gap-1.5' data-state={step.state}>
              <span className='text-muted-foreground w-20 shrink-0'>{STEP_WORDS[step.state] ?? step.state}</span>
              <span>{step.label}</span>
            </li>
          ))}
        </ol>
      )}
      {specialists.length > 0 && (
        <p className='text-muted-foreground text-[11px]'>Worked with: {specialists.map((s) => String(s).replace(/_/g, ' ')).join(', ')}</p>
      )}
      {process.env.NODE_ENV !== 'production' && <p className='text-muted-foreground/70 text-[10px]' data-rafii-trace={result.traceId}>trace {result.traceId}</p>}
    </div>
  );
}
