/**
 * The Agent Runtime's HTTP client. Same transport rules as `lib/api/client.ts`: the signed-in session's bearer token and
 * the app's request-guard header on every call; errors become `ApiError` with the server's message. No OpenAI credential
 * ever exists in the browser: Voice Mode sends its WebRTC offer to Rafii's server, which creates the GPT-Live session.
 */
import { APP_GUARD_HEADER, ApiError, type TokenSource } from '@/lib/api/client';
import type { AgentStatus, AgentTurnRequest, AgentTurnResponse, ConversationState, DecideResponse, VoiceSessionStart } from './types';

const base = (workspaceId: string) => `/api/workspaces/${encodeURIComponent(workspaceId)}/agent`;

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = 'Rafii could not complete that request.';
    let code: string | undefined;
    try {
      const body = (await res.json()) as { error?: unknown; code?: unknown };
      if (typeof body?.error === 'string' && body.error) message = body.error;
      if (typeof body?.code === 'string') code = body.code;
    } catch {
      /* keep the generic message */
    }
    throw new ApiError(message, res.status, code);
  }
  return res.json() as Promise<T>;
}

export function createAgentApi(getToken: TokenSource) {
  async function headers(): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }
  async function get<T>(path: string): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(), cache: 'no-store' }));
  }
  async function post<T>(path: string, body: unknown = {}, signal?: AbortSignal): Promise<T> {
    return parse<T>(await fetch(path, { method: 'POST', headers: await headers(), body: JSON.stringify(body), signal }));
  }
  return {
    status: (w: string) => get<AgentStatus>(`${base(w)}/status`),
    turn: (w: string, body: AgentTurnRequest, signal?: AbortSignal) => post<AgentTurnResponse>(`${base(w)}/turns`, body, signal),
    run: (w: string, runId: string) => get<AgentTurnResponse>(`${base(w)}/runs/${encodeURIComponent(runId)}`),
    cancel: (w: string, runId: string) => post<{ runId: string; status: string }>(`${base(w)}/runs/${encodeURIComponent(runId)}/cancel`),
    conversationState: (w: string, conversationId: string) => get<ConversationState>(`${base(w)}/conversations/${encodeURIComponent(conversationId)}/state`),
    decide: (w: string, body: { conversationId: string; messageId: string; proposalId: string; digest: string; decision: 'apply' | 'dismiss'; timeZone?: string }) =>
      post<DecideResponse>(`${base(w)}/approvals/decide`, body),
    attach: (w: string, body: { conversationId: string; data?: string; assetId?: string }) =>
      post<{ assetId: string; index: number | null; href: string }>(`${base(w)}/attachments`, body),
    voiceStart: (w: string, body: { sdp: string; conversationId?: string | null; locale?: string; voice?: string }) =>
      post<VoiceSessionStart>(`${base(w)}/voice/sessions`, body),
    voiceTranscript: (w: string, voiceSessionId: string, turns: { role: 'user' | 'assistant'; text: string; startMs?: number }[]) =>
      post<{ stored: number }>(`${base(w)}/voice/sessions/${encodeURIComponent(voiceSessionId)}/transcript`, { turns }),
    voiceEnd: (w: string, voiceSessionId: string, body: { usageSeconds?: number | null; reason: string }) =>
      post<{ state: string; usageSeconds: number | null }>(`${base(w)}/voice/sessions/${encodeURIComponent(voiceSessionId)}/end`, body),
    /** Authenticated image bytes for a private asset (rendered as an object URL). */
    async media(w: string, assetId: string): Promise<Blob> {
      const res = await fetch(`/api/workspaces/${encodeURIComponent(w)}/media/${encodeURIComponent(assetId)}`, { headers: await headers() });
      if (!res.ok) await parse(res);
      return res.blob();
    }
  };
}

export type AgentApi = ReturnType<typeof createAgentApi>;
