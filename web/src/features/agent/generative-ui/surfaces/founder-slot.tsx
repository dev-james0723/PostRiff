'use client';

/**
 * The `generated` slot of a Founder Rafii answer (J09; D-A22). Same artifact machinery as consumer answers, through the
 * founder route family (control cookie + CSRF, founder-scoped artifacts, read-only manifest: no write controls). The control
 * app cannot stream, so a fresh founder turn starts its presentation with a blocking POST while the durable events are polled;
 * a founder view never appears in consumer chat and a consumer view never appears here. Native founder facts, receipts,
 * warnings and errors stay outside this slot.
 */
import { useEffect, useState } from 'react';
import type { FounderAgentTurnResponse } from '@/lib/founder/types';
import type { ContinueRequest } from '@/features/agent/generative-ui/bridges/types';
import { isFresh } from '../state/registry';
import { GeneratedArtifact } from './artifact';
import { useFounderUiTransport } from './founder-transport';
import { presentationPlan } from './plan';
import { bundledLibraryHashes } from './renderer-adapter';
import { loadMessageViews, startFounderPresentation, type ArtifactSession } from './session';

export function FounderGeneratedSlot({ response, onContinue }: { response: FounderAgentTurnResponse; latest?: boolean; onContinue?: (request: ContinueRequest) => void }) {
  const transport = useFounderUiTransport();
  const result = response.result;
  const fresh = Boolean(transport && isFresh(transport.scopeKey, response.runId));
  // The founder flags are enforced by the founder routes (POLICY_DISABLED → nothing shown); eligibility comes from the turn.
  const plan = presentationPlan({ enabled: true, handoff: result?.ui, artifacts: result?.uiArtifacts, runId: response.runId, fresh, latest: false, surface: 'founder' });
  const [sessions, setSessions] = useState<ArtifactSession[]>([]);

  useEffect(() => {
    if (!transport || !response.messageId) return;
    let alive = true;
    if (plan.kind === 'load') {
      void loadMessageViews(transport, response.messageId, response.conversationId, bundledLibraryHashes('founder')).then((loaded) => alive && setSessions(loaded));
    } else if (plan.kind === 'post' && response.runId) {
      void startFounderPresentation({ transport, runId: response.runId, messageId: response.messageId, conversationId: response.conversationId, supportedLibraryHashes: bundledLibraryHashes('founder') }).then((started) => {
        if (alive && started.session) setSessions([started.session]);
      });
    }
    return () => {
      alive = false;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [plan.kind, response.messageId, response.runId, transport?.scopeKey]);

  if (!transport || !sessions.length) return null;
  return (
    <>
      {sessions.map((session) => (
        <GeneratedArtifact key={`${session.scopeKey}|${session.artifactId}`} session={session} surface='founder' runId={response.runId} onContinue={onContinue} />
      ))}
    </>
  );
}
