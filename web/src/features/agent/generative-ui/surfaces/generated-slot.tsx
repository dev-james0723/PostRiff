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
import { useCallback, useEffect, useState } from 'react';
import type { Message } from '@/lib/api/types';
import type { AgentResult } from '@/lib/agent-runtime/types';
import type { UiSurface } from '@/lib/agent-runtime/ui-contracts';
import { useAgent } from '@/lib/agent-runtime/use-agent';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { isFresh, markFresh } from '../state/registry';
import { GeneratedArtifact } from './artifact';
import { ExpandedArtifact } from './expanded';
import { QuietButton } from './frame';
import { presentationPlan } from './plan';
import { loadMessageViews, startPresentation, type ArtifactSession } from './session';
import { useConsumerUiTransport } from './transport';

export function GeneratedAnswerSlot({ message, conversationId, surface, latest, onContinue }: {
  message: Message;
  conversationId: string | null;
  surface: UiSurface;
  latest: boolean;
  onContinue?: (request: ContinueRequest) => void;
}) {
  const agent = useAgent();
  const transport = useConsumerUiTransport();
  const result = (message.body as { agent?: AgentResult & { modality?: string } }).agent;
  const enabled = Boolean(agent.status?.genui?.enabled);
  const refs = result?.uiArtifacts;
  const refKey = (refs ?? []).map((r) => r.artifactId).join(',');
  const [requested, setRequested] = useState(false);
  const fresh = Boolean(transport && (requested || isFresh(transport.scopeKey, message.runId)));
  const plan = presentationPlan({ enabled, handoff: result?.ui, artifacts: refs, runId: message.runId, fresh, latest, surface, modality: result?.modality });
  const [sessions, setSessions] = useState<ArtifactSession[]>([]);
  const [problem, setProblem] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<ArtifactSession | null>(null);

  useEffect(() => {
    if (!transport) return;
    let alive = true;
    if (plan.kind === 'load') {
      void loadMessageViews(transport, message.messageId, conversationId).then((loaded) => {
        if (alive) setSessions(loaded);
      });
    } else if (plan.kind === 'post' && message.runId) {
      void startPresentation({ transport, runId: message.runId, conversationId, surface }).then((started) => {
        if (!alive) return;
        if (started.session) setSessions([started.session]);
        else if (started.status && started.status !== 404 && started.code !== 'ui_disabled') {
          setProblem(started.code === 'ui_not_eligible' ? 'An interactive view isn’t available for this answer.' : 'The interactive view couldn’t start. The answer above is complete.');
        }
      });
    } else {
      setSessions([]);
    }
    return () => {
      alive = false;
    };
    // The plan's kind, the message, its views and the scope decide; nothing else restarts it.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.kind, refKey, message.messageId, message.runId, transport?.scopeKey]);

  const build = useCallback(() => {
    if (!transport || !message.runId) return;
    markFresh(transport.scopeKey, message.runId);
    setRequested(true);
  }, [transport, message.runId]);

  if (!transport || plan.kind === 'none') return problem ? <p role='status' className='text-muted-foreground text-xs'>{problem}</p> : null;
  if (plan.kind === 'offer' && !sessions.length) {
    return <div className='flex flex-col gap-1'><QuietButton onClick={build}>Build interactive view</QuietButton>
      <p className='text-muted-foreground text-xs'>Builds a view of this answer you can filter and explore. It uses the same allowance as the answer.</p></div>;
  }
  return (
    <>
      {sessions.map((session) => (
        <GeneratedArtifact key={`${session.scopeKey}|${session.artifactId}`} session={session} surface={surface} runId={message.runId} onContinue={onContinue}
          onExpand={() => setExpanded(session)} />
      ))}
      {problem && <p role='status' className='text-muted-foreground text-xs'>{problem}</p>}
      {expanded && <ExpandedArtifact session={expanded} open onOpenChange={(open) => !open && setExpanded(null)} runId={message.runId} onContinue={onContinue} />}
    </>
  );
}
