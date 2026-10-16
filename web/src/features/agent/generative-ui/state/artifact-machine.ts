/**
 * The client state machine of one generated view (lane F; 02-CONTRACTS §2, §5).
 *
 * Inputs are the server's snapshot (authoritative: GET presentations/{id} or messages/{id}) and the artifact's ordered events.
 * The machine never decides that something is accepted, applied or paid: `ready` arrives from the server and the canonical
 * source is read from the snapshot. While a first generation streams, its candidate source is an untrusted preview (writes
 * stay off); while an edit streams, the last accepted revision stays on screen (state and focus preserved) until the new one is
 * ready. Failures keep the last valid revision, or the native answer when there is none. An unsupported library version falls
 * back to the stored native text with no model call.
 */
import type { JsonValue, UiArtifactV1, UiEventV1, UiPublicManifestV1 } from '@/lib/agent-runtime/ui-contracts';
import type { DeclaredState } from './persisted-state';

export interface UiAttemptView {
  attemptId: string;
  kind: 'generate' | 'repair' | 'edit' | 'retry';
  state: string;
  reason: string | null;
  targetRevision: number;
  baseRevision: number | null;
  retryOf: string | null;
  providerAttempts?: number;
  costState?: string;
  live: boolean;
}

export interface UiArtifactViewV1 {
  artifact: UiArtifactV1;
  manifest: UiPublicManifestV1;
  revisions: { revision: number; kind: string; sourceHash: string; attemptId: string | null; libraryVersion?: string; createdAt: string | null }[];
  attempt: UiAttemptView | null;
  compatibility: { supported: boolean; reason: string | null };
  display: { mode: 'generated' | 'pending' | 'fallback'; reason: string | null; updating: boolean; revokedRefs?: number };
  access: { role: string; isActor: boolean; enabled: boolean; live: boolean; canQuery: boolean; canAct: boolean; canEdit: boolean; canRetry: boolean;
    canPersistState: boolean; manifestExpired: boolean; historical: boolean; revokedRefs: string[]; fallback?: boolean };
  lastSeq: number;
  journeyIds: string[];
  surface: string;
  scope: 'workspace' | 'founder';
  declared?: DeclaredState;
  /** The server shows this view as its native fallback (old library, failed first view): no controls are offered (NC18). */
  fallback?: boolean;
}

export type ArtifactPhase = 'idle' | 'starting' | 'pending' | 'streaming' | 'ready' | 'updating' | 'fallback';

export interface ArtifactNotice {
  kind: 'failed' | 'canceled' | 'interrupted' | 'unsupported' | 'unavailable';
  reason: string | null;
}

export interface ArtifactViewState {
  artifactId: string | null;
  view: UiArtifactViewV1 | null;
  phase: ArtifactPhase;
  candidate: { attemptId: string | null; revision: number; source: string; bytes: number } | null;
  lastSeq: number;
  notice: ArtifactNotice | null;
  needsSnapshot: boolean;
  needsReplay: boolean;
}

export type ArtifactAction =
  | { type: 'start' }
  | { type: 'artifact'; artifactId: string }
  | { type: 'snapshot'; view: UiArtifactViewV1; supportedLibraryHashes?: readonly string[] }
  | { type: 'snapshot_failed'; status: number; code?: string | null }
  | { type: 'event'; event: UiEventV1 }
  | { type: 'reset' };

export const INITIAL_ARTIFACT_STATE: ArtifactViewState = {
  artifactId: null, view: null, phase: 'idle', candidate: null, lastSeq: 0, notice: null, needsSnapshot: false, needsReplay: false
};

const encoder = new TextEncoder();
const decoder = new TextDecoder();

function accepted(view: UiArtifactViewV1 | null): boolean {
  return Boolean(view && view.artifact.validationState === 'accepted' && view.artifact.revision >= 1 && view.display.mode === 'generated');
}

function phaseOf(view: UiArtifactViewV1): ArtifactPhase {
  if (view.display.mode === 'fallback') return 'fallback';
  if (view.display.mode === 'pending') return 'pending';
  return view.display.updating ? 'updating' : 'ready';
}

function appendDelta(candidate: NonNullable<ArtifactViewState['candidate']>, text: string, offset: number): NonNullable<ArtifactViewState['candidate']> | 'gap' {
  if (offset > candidate.bytes) return 'gap';
  const bytes = encoder.encode(text);
  if (offset + bytes.length <= candidate.bytes) return candidate; // already applied (replay overlap)
  const tail = offset === candidate.bytes ? text : decoder.decode(bytes.subarray(candidate.bytes - offset));
  const source = candidate.source + tail;
  return { ...candidate, source, bytes: candidate.bytes + encoder.encode(tail).length };
}

export function reduceArtifact(state: ArtifactViewState, action: ArtifactAction): ArtifactViewState {
  switch (action.type) {
    case 'reset':
      return INITIAL_ARTIFACT_STATE;
    case 'start':
      return { ...state, phase: state.view ? state.phase : 'starting', notice: null };
    case 'artifact':
      return state.artifactId === action.artifactId ? state : { ...state, artifactId: action.artifactId };
    case 'snapshot_failed':
      if (action.status === 404 || action.status === 403) {
        return { ...state, view: null, candidate: null, phase: 'fallback', needsSnapshot: false, notice: { kind: 'unavailable', reason: action.code ?? null } };
      }
      return { ...state, needsSnapshot: false, notice: state.view ? state.notice : { kind: 'unavailable', reason: action.code ?? null } };
    case 'snapshot': {
      const view = action.view;
      const supported = action.supportedLibraryHashes;
      const unsupported = Boolean(supported && supported.length && view.artifact.libraryHash && view.artifact.revision >= 1 && !supported.includes(view.artifact.libraryHash));
      const safeView: UiArtifactViewV1 = unsupported
        ? { ...view, artifact: { ...view.artifact, canonicalSource: null }, display: { mode: 'fallback', reason: 'library_unsupported', updating: false } }
        : view;
      const phase = phaseOf(safeView);
      // A first generation still streaming keeps its preview; anything else drops it (the snapshot is authoritative).
      const keepCandidate = phase === 'pending' && state.candidate && safeView.attempt?.attemptId === state.candidate.attemptId;
      // The snapshot read right after a failed edit confirms that failure (its current attempt failed for the same reason): the
      // notice stays, so "That change couldn't be made" (or why: no allowance, paid AI paused) is still there to read. A reload
      // starts without a notice, so an old failure is never reported again.
      const attempt = safeView.attempt;
      const failed = state.notice && state.notice.kind === 'failed' ? state.notice : null;
      const confirmed = Boolean(failed && attempt && !attempt.live && attempt.state === 'failed' && attempt.reason === failed.reason);
      return {
        ...state, artifactId: view.artifact.artifactId, view: safeView, phase, needsSnapshot: false,
        candidate: keepCandidate ? state.candidate : null, lastSeq: Math.max(state.lastSeq, view.lastSeq),
        notice: unsupported || safeView.display.reason === 'library_unsupported' ? { kind: 'unsupported', reason: 'library_unsupported' }
          : phase === 'fallback' ? { kind: 'failed', reason: safeView.display.reason } : state.notice && (phase !== 'ready' || confirmed) ? state.notice : null
      };
    }
    case 'event': {
      const event = action.event;
      if (state.artifactId && event.artifactId !== state.artifactId) return state;
      const next: ArtifactViewState = { ...state, artifactId: event.artifactId, lastSeq: Math.max(state.lastSeq, event.seq) };
      const payload = (event.payload ?? {}) as Record<string, JsonValue>;
      switch (event.kind) {
        case 'ui.started':
          return { ...next, candidate: { attemptId: event.attemptId, revision: event.revision, source: '', bytes: 0 }, notice: null,
            phase: accepted(state.view) ? 'updating' : 'streaming' };
        case 'ui.delta': {
          if (!next.candidate || (event.attemptId && next.candidate.attemptId && event.attemptId !== next.candidate.attemptId)) return next;
          const text = typeof payload.append === 'string' ? payload.append : typeof payload.text === 'string' ? payload.text : '';
          const offset = typeof payload.offset === 'number' ? payload.offset : next.candidate.bytes;
          const applied = appendDelta(next.candidate, text, offset);
          if (applied === 'gap') return { ...next, needsReplay: true };
          return { ...next, candidate: applied, needsReplay: false, phase: accepted(state.view) ? 'updating' : 'streaming' };
        }
        case 'ui.checkpoint': {
          const cursor = typeof payload.cursor === 'number' ? payload.cursor : null;
          if (next.candidate && cursor !== null && cursor > next.candidate.bytes) return { ...next, needsReplay: true };
          return next;
        }
        case 'ui.ready':
          // Validated, persisted and settled on the server: read the canonical source from the snapshot.
          return { ...next, needsSnapshot: true, notice: null };
        case 'ui.failed':
        case 'ui.canceled':
        case 'ui.interrupted': {
          const kind = event.kind === 'ui.failed' ? 'failed' : event.kind === 'ui.canceled' ? 'canceled' : 'interrupted';
          const reason = typeof payload.reason === 'string' ? payload.reason : null;
          const keep = accepted(state.view);
          return { ...next, candidate: null, needsSnapshot: true, notice: { kind, reason }, phase: keep ? 'ready' : 'fallback' };
        }
        case 'ui.state_changed': {
          const revision = typeof payload.stateRevision === 'number' ? payload.stateRevision : 0;
          return state.view && revision > state.view.artifact.stateRevision ? { ...next, needsSnapshot: true } : next;
        }
        case 'ui.binding_changed':
          return { ...next, needsSnapshot: true };
        default:
          return next;
      }
    }
    default:
      return state;
  }
}

export type ArtifactRender =
  | { mode: 'generated'; artifact: UiArtifactV1; accepted: true; updating: boolean }
  | { mode: 'preview'; artifact: UiArtifactV1 | null; source: string; accepted: false }
  | { mode: 'pending' }
  | { mode: 'fallback'; text: string; reason: string | null };

/** What a surface should draw now. Generated source is only the server's canonical source; a preview is never interactive. */
export function renderOf(state: ArtifactViewState): ArtifactRender {
  const view = state.view;
  if (view && accepted(view) && view.artifact.canonicalSource) {
    return { mode: 'generated', artifact: view.artifact, accepted: true, updating: state.phase === 'updating' || Boolean(view.display.updating) };
  }
  if (state.phase === 'fallback' || view?.display.mode === 'fallback') {
    return { mode: 'fallback', text: view?.artifact.fallbackText ?? '', reason: view?.display.reason ?? state.notice?.reason ?? null };
  }
  if (state.candidate && state.candidate.source) {
    const artifact = view?.artifact ?? null;
    return { mode: 'preview', artifact: artifact ? { ...artifact, canonicalSource: null } : null, source: state.candidate.source, accepted: false };
  }
  return { mode: 'pending' };
}

/** A short, deduplicated status line for the native layer (never DSL, never raw server text). */
export function statusLine(state: ArtifactViewState): string | null {
  const notice = state.notice;
  if (state.phase === 'starting' || state.phase === 'pending') return 'Preparing the interactive view…';
  if (state.phase === 'streaming') return 'Building the interactive view…';
  if (state.phase === 'updating') return 'Updating the view…';
  if (notice?.kind === 'unsupported') return 'This view was made with an older version. The answer above is still complete.';
  if (notice?.kind === 'canceled') return state.view && accepted(state.view) ? 'The change was stopped. The previous view is kept.' : 'The interactive view was stopped. The answer above is complete.';
  if (notice?.kind === 'interrupted') return state.view && accepted(state.view) ? 'The change didn’t finish. The previous view is kept.' : 'The interactive view didn’t finish. The answer above is complete.';
  if (notice?.kind === 'failed') {
    if (notice.reason === 'revision_conflict') return 'This view changed in another tab. The latest version is shown.';
    return state.view && accepted(state.view) ? 'That change couldn’t be made. The previous view is kept.' : 'The interactive view isn’t available for this answer. The answer above is complete.';
  }
  if (notice?.kind === 'unavailable') return 'This interactive view is no longer available.';
  return null;
}
