'use client';

/**
 * The `generated` slot of a consumer answer (full chat, panel, tablet and phone sheets; lane F, D-A19/D-A21). It sits between
 * the native answer blocks and the follow-ups/provenance in SiteAgentAnswer, so native text, warnings, review cards, approvals
 * and receipts stay outside the generated subtree.
 *
 * - An answer with views (`body.agent.uiArtifacts`) loads their snapshots: zero provider attempts on reload, reopen, a second tab
 *   or another member's screen.
 * - Only a turn answered in this tab (marked fresh by the composer) starts its one presentation, with the run's stable key.
 * - An eligible answer without a view (reloaded too early, or asked by voice) offers an explicit "Build interactive view".
 * - With the feature off for this workspace nothing renders: the native answer is the whole answer.
 */
import { useCallback, useEffect, useState, useSyncExternalStore } from 'react';
import type { Message } from '@/lib/api/types';
import type { AgentResult } from '@/lib/agent-runtime/types';
import type { UiSurface } from '@/lib/agent-runtime/ui-contracts';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { isFresh, markFresh, onUiScopeChange, registryVersion } from '../state/registry';
import { GeneratedArtifact } from './artifact';
import { ExpandedArtifact } from './expanded';
import { QuietButton } from './frame';
import { presentationPlan } from './plan';
import { loadMessageViews, startPresentation, type ArtifactSession } from './session';
import { bundledLibraryHashes, GeneratedRenderer } from './renderer-adapter';
import { GENERATED_HOST_ATTR } from './selectors';
import { useConsumerUiTransport } from './transport';

const PENDING = { mode: 'pending' } as const;
const noop = () => undefined;

/** A start that failed for a reason that may pass (network, server busy, a stream that ended early): offer to build again. */
export function transient(status: number, code: string | null): boolean {
  return status === 0 || status === 408 || status === 429 || status >= 500 || code === 'ui_stream_failed';
}

export function GeneratedAnswerSlot({ message, conversationId, surface, latest, onContinue, onNavigate }: {
  message: Message;
  conversationId: string | null;
  surface: UiSurface;
  latest: boolean;
  onContinue?: (request: ContinueRequest) => void;
  /** In-app navigation for an `@OpenUrl("/app/…")` in the view (same-origin paths only; the surface may close itself). */
  onNavigate?: (path: string) => void;
}) {
  const agent = useAgent();
  const transport = useConsumerUiTransport();
  // Fresh marks are set by the composer when the turn's response arrives, possibly after this slot first rendered.
  useSyncExternalStore(onUiScopeChange, registryVersion, registryVersion);
  const result = (message.body as { agent?: AgentResult & { modality?: string } }).agent;
  const enabled = Boolean(agent.status?.genui?.enabled);
  const refs = result?.uiArtifacts;
  const refKey = (refs ?? []).map((r) => r.artifactId).join(',');
  const [requested, setRequested] = useState(false);
  const fresh = Boolean(transport && (requested || isFresh(transport.scopeKey, message.runId)));
  const plan = presentationPlan({ enabled, handoff: result?.ui, artifacts: refs, runId: message.runId, fresh, latest, surface, modality: result?.modality });
  const [sessions, setSessions] = useState<ArtifactSession[]>([]);
  const [starting, setStarting] = useState(false);
  const [problem, setProblem] = useState<{ text: string; code: string | null; again: boolean } | null>(null);
  const [attempt, setAttempt] = useState(0);
  const [expanded, setExpanded] = useState<ArtifactSession | null>(null);

  useEffect(() => {
    if (!transport) return;
    let alive = true;
    if (plan.kind === 'load') {
      void loadMessageViews(transport, message.messageId, conversationId, bundledLibraryHashes('consumer')).then((loaded) => {
        if (alive) setSessions(loaded);
      });
    } else if (plan.kind === 'post' && message.runId) {
      setStarting(true);
      setProblem(null);
      // The run's stable key: a second surface, a remount or "build again" after a network failure resends the same request,
      // which the server answers with the existing attempt (never a second generation).
      void startPresentation({ transport, runId: message.runId, conversationId, surface, supportedLibraryHashes: bundledLibraryHashes('consumer') }).then((started) => {
        if (!alive) return;
        setStarting(false);
        if (started.session) {
          setSessions([started.session]);
          return;
        }
        if (started.code === 'ui_disabled') return;
        const again = transient(started.status, started.code);
        setProblem({ code: started.code ?? (started.status ? `http_${started.status}` : 'ui_unreachable'), again,
          text: started.code === 'ui_not_eligible' ? 'An interactive view isn’t available for this answer.'
            : again ? 'The interactive view didn’t start. The answer above is complete.' : 'The interactive view couldn’t start. The answer above is complete.' });
      });
    } else {
      setSessions([]);
    }
    return () => {
      alive = false;
    };
    // The plan's kind, the message, its views, the scope and an explicit "build again" decide; nothing else restarts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.kind, refKey, message.messageId, message.runId, transport?.scopeKey, attempt]);

  const build = useCallback(() => {
    if (!transport || !message.runId) return;
    markFresh(transport.scopeKey, message.runId);
    setRequested(true);
    setAttempt((n) => n + 1);
  }, [transport, message.runId]);

  const host = { [GENERATED_HOST_ATTR]: '', 'data-ui-plan': plan.kind, 'data-ui-problem': problem?.code ?? undefined } as Record<string, string | undefined>;
  if (!transport || plan.kind === 'none') return problem ? <p role='status' className='text-muted-foreground text-xs'>{problem.text}</p> : null;
  if ((plan.kind === 'offer' && !sessions.length) || (problem?.again && !sessions.length)) {
    return (
      <div {...host} className='flex flex-col gap-1'>
        {problem && <p role='status' className='text-muted-foreground text-xs'>{problem.text}</p>}
        <QuietButton onClick={build}>Build interactive view</QuietButton>
        <p className='text-muted-foreground text-xs'>Builds a view of this answer you can filter and explore. It uses the same allowance as the answer.</p>
      </div>
    );
  }
  return (
    <>
      {starting && !sessions.length && (
        // The view is being created: show its frame now (C's pending state) instead of waiting for the first event.
        <div {...host} data-surface={surface} className='flex min-w-0 flex-col gap-2'>
          <GeneratedRenderer render={PENDING} view={null} transport={transport} surface={surface} status='Preparing the interactive view…' active onContinue={noop} />
        </div>
      )}
      {sessions.map((session) => (
        <GeneratedArtifact key={`${session.scopeKey}|${session.artifactId}`} session={session} surface={surface} runId={message.runId} onContinue={onContinue}
          onExpand={() => setExpanded(session)} onNavigate={onNavigate} />
      ))}
      {problem && !problem.again && <p {...host} role='status' className='text-muted-foreground text-xs'>{problem.text}</p>}
      {expanded && <ExpandedArtifact session={expanded} open onOpenChange={(open) => !open && setExpanded(null)} runId={message.runId} onContinue={onContinue}
        onNavigate={onNavigate} />}
    </>
  );
}
