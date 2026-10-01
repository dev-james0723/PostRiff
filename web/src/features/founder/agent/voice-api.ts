/**
 * Founder voice over the customer Voice Mode controller (`lib/agent-runtime/voice-session.ts`, CONTRACTS §8.E): the
 * same WebRTC transport, transcript and hang-up rules, with a founder host whose API reaches the founder routes instead
 * of a workspace's:
 *
 *   start        POST /agent/voice/sessions?mode=            → the GPT-Live session (SDP answer; server-held key)
 *   delegation   POST /agent/voice/sessions/{id}/delegations → one founder turn, modality voice (founder tools only)
 *   transcript   POST /agent/voice/sessions/{id}/transcript  → text of what was said (no audio)
 *   end          POST /agent/voice/sessions/{id}/end         → ends and settles the call on the ops workspace
 *
 * Every request carries the data mode it was started in, so a Demo call never answers from Live. The voice front end
 * has no tools of its own: each delegated request is an ordinary founder turn in the call's conversation, and Rafii
 * only says what that turn returned. Progress polling is not offered (the founder runtime has no task steps to read),
 * so it answers empty instead of calling the server. Pure module: no React, no network of its own; the fetch, the page
 * context and the error mapping are passed in, which is how the node test exercises it.
 */
import type { AgentApi } from '@/lib/agent-runtime/client';
import type { AgentTurnRequest, AgentTurnResponse, ConversationState, VoiceSessionStart } from '@/lib/agent-runtime/types';
import type { FounderMode, FounderPageContext } from '@/lib/founder/types';

export interface FounderFetchOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE';
  body?: unknown;
  signal?: AbortSignal;
}

export type FounderFetchFn = <T>(path: string, init?: FounderFetchOptions) => Promise<T>;

/** `GET /agent/voice/status`: whether voice can start here and, when not, every fixed blocker code. */
export interface FounderVoiceStatus {
  available: boolean;
  blockers: string[];
  mode: FounderMode;
  capMinutes: number;
  model: string | null;
  delegation: string;
}

/** The part of the customer agent API the voice controller calls; the founder routes answer each one. */
export type FounderVoiceApi = Pick<AgentApi, 'turn' | 'conversationState' | 'voiceStart' | 'voiceTranscript' | 'voiceEnd'>;

/** What a blocker code means, in words; the code itself is always shown beside it. */
export const VOICE_BLOCKER_COPY: Record<string, string> = {
  founder_voice_disabled: 'Founder voice is switched off here (the server flag RAFII_FOUNDER_VOICE_ENABLED is not set).',
  ops_workspace_not_configured: 'No founder workspace is set yet. Create one in Settings → Contact & calls → Founder workspace.',
  consumer_runtime_unavailable: 'Control runs without the Rafii app runtime here, so it cannot open a voice session.',
  agent_runtime_off: 'Rafii’s agent runtime is off here, so spoken questions would have nothing to answer them.',
  voice_route_unavailable: 'GPT-Live is not configured here (no OpenAI key for the live route).',
  voice_session_ended: 'That voice session has ended. Start voice again.',
  status_unavailable: 'Voice status could not be read. Typing still works.'
};

export function voiceBlockerCopy(code: string): string {
  return VOICE_BLOCKER_COPY[code] ?? 'Voice is unavailable here for a reason this page does not know yet.';
}

/** The fixed codes a status names, in the order the server gave them; an unavailable status without codes still says so. */
export function voiceBlockers(status: Pick<FounderVoiceStatus, 'available' | 'blockers'> | null | undefined): string[] {
  if (!status) return ['status_unavailable'];
  const codes = Array.isArray(status.blockers) ? status.blockers.filter((code): code is string => typeof code === 'string' && /^[a-z][a-z0-9_]{0,63}$/.test(code)) : [];
  if (!status.available && codes.length === 0) return ['status_unavailable'];
  return status.available ? [] : codes;
}

/** The founder route for a voice operation, with the call's data mode. */
export function voicePath(mode: FounderMode, sessionId?: string | null, action?: 'delegations' | 'transcript' | 'end'): string {
  const base = '/agent/voice/sessions';
  const path = sessionId ? `${base}/${encodeURIComponent(sessionId)}/${action ?? 'end'}` : base;
  return `${path}?mode=${mode === 'demo' ? 'demo' : 'live'}`;
}

/** The control envelope's `data`, or the body itself when the route answered without one. */
export function unwrapData<T>(body: unknown): T {
  if (body && typeof body === 'object' && 'data' in body && 'requestId' in body) return (body as { data: T }).data;
  return body as T;
}

function compact(body: Record<string, unknown>): Record<string, unknown> {
  return Object.fromEntries(Object.entries(body).filter(([, value]) => value !== undefined && value !== null && value !== ''));
}

/** The longest message a founder turn accepts (`founder_agent.MAX_MESSAGE`). */
export const MAX_SPOKEN_REQUEST = 4000;

export interface FounderVoiceApiOptions {
  fetch: FounderFetchFn;
  mode: FounderMode;
  /** The founder page context each delegated request carries (read when the request is sent). */
  pageContext: () => FounderPageContext;
  /** Maps a failed request to the error the voice controller understands (it tells refusals from unknown outcomes). */
  toError?: (error: unknown) => unknown;
}

export class FounderVoiceRequestError extends Error {
  status: number;
  code: string;
  constructor(message: string, status: number, code: string) {
    super(message);
    this.name = 'FounderVoiceRequestError';
    this.status = status;
    this.code = code;
  }
}

/**
 * The words Rafii says for a delegated answer: the turn's own spoken summary, else the delegation's `speakable` (the
 * server's speakable form of the same answer). Nothing is composed here; with neither, the controller says only that
 * the answer is in the panel.
 */
export function withSpokenSummary<T extends AgentTurnResponse & { speakable?: unknown }>(response: T): T {
  const spoken = typeof response?.speakable === 'string' ? response.speakable.trim() : '';
  if (!response?.result || response.result.speakableSummary?.trim() || !spoken) return response;
  return { ...response, result: { ...response.result, speakableSummary: spoken } };
}

export function createFounderVoiceApi({ fetch, mode, pageContext, toError = (error) => error }: FounderVoiceApiOptions): FounderVoiceApi {
  async function post<T>(path: string, body: Record<string, unknown>): Promise<T> {
    try {
      return unwrapData<T>(await fetch<unknown>(path, { method: 'POST', body }));
    } catch (error) {
      throw toError(error);
    }
  }
  const emptyState: ConversationState = { task: null, images: [], pendingApprovals: [] };
  return {
    voiceStart: (_workspace: string, body: { sdp: string; conversationId?: string | null; locale?: string; voice?: string }) =>
      post<VoiceSessionStart>(voicePath(mode), compact({ sdp: body.sdp, mode, conversationId: body.conversationId, locale: body.locale, voice: body.voice })),
    turn: async (_workspace: string, body: AgentTurnRequest): Promise<AgentTurnResponse> => {
      if (!body.voiceSessionId || !body.delegationId) {
        throw toError(new FounderVoiceRequestError('This spoken request has no voice session to answer it. Start voice again.', 400, 'voice_session_missing'));
      }
      const out = await post<AgentTurnResponse & { speakable?: unknown }>(
        voicePath(mode, body.voiceSessionId, 'delegations'),
        compact({ delegationId: body.delegationId, message: body.message.slice(0, MAX_SPOKEN_REQUEST), timeZone: body.timeZone, locale: body.locale, pageContext: pageContext() })
      );
      return withSpokenSummary(out);
    },
    conversationState: async (_workspace: string, _conversationId: string): Promise<ConversationState> => emptyState,
    voiceTranscript: (_workspace: string, voiceSessionId: string, turns: { role: 'user' | 'assistant'; text: string; startMs?: number }[]) =>
      post<{ stored: number }>(voicePath(mode, voiceSessionId, 'transcript'), { turns }),
    voiceEnd: (_workspace: string, voiceSessionId: string, body: { usageSeconds?: number | null; reason: string }) =>
      post<{ state: string; usageSeconds: number | null }>(voicePath(mode, voiceSessionId, 'end'), compact({ usageSeconds: body.usageSeconds, reason: body.reason }))
  };
}

/** One call per data mode and environment: the controller's "workspace" key, so a switch of either ends the call. */
export function founderVoiceKey(mode: FounderMode, environment: string | null): string {
  return `founder:${mode}:${environment ?? 'unknown'}`;
}
