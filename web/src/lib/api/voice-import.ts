/**
 * Typed browser client for the voice import routes (ENGINEERING-SPEC §5.1), all under
 * `/api/workspaces/{workspaceId}/voice-imports`. Same guard header, bearer session and error shape as `./client`;
 * kept separate so the shared client stays untouched. Export files are parsed in the browser
 * (`@/lib/voice-import`); this client only ever sends normalised post records.
 */
import { ApiError, APP_GUARD_HEADER } from './client';
import type { TokenSource } from './client';
import type { ImportRequest, ItemsBody, PostCorrection, VoiceAnalysis, VoiceImport, VoiceImportsView, VoicePost, VoicePostPage } from '../voice-import/types';

const seg = encodeURIComponent;
const base = (workspaceId: string) => `/api/workspaces/${seg(workspaceId)}/voice-imports`;

/**
 * The list route answers 404 (`feature_disabled`) while voice import is switched off for the deployment, and an older
 * server has no such route at all. Either way the feature is not there, and the UI shows nothing for it.
 */
export function voiceImportUnavailable(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404;
}

async function parse<T>(res: Response): Promise<T> {
  if (!res.ok) {
    let message = 'The workspace could not complete that request.';
    let code: string | undefined;
    try {
      const body = (await res.json()) as { error?: unknown; code?: unknown };
      if (typeof body?.error === 'string' && body.error) message = body.error;
      if (typeof body?.code === 'string') code = body.code;
    } catch {
      /* keep the generic message */
    }
    const requestId = res.headers.get('X-Request-ID') ?? undefined;
    throw new ApiError(message, res.status, code, requestId && /^[a-f0-9]{32}$/.test(requestId) ? requestId : undefined);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export interface PostQuery {
  provider?: string;
  accountKey?: string;
  status?: string;
  cursor?: string;
}

export function createVoiceImportApi(getToken: TokenSource) {
  async function headers(): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }
  async function get<T>(path: string): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(), cache: 'no-store' }));
  }
  async function send<T>(method: 'POST' | 'DELETE', path: string, body: unknown = {}): Promise<T> {
    return parse<T>(await fetch(path, { method, headers: await headers(), body: method === 'DELETE' ? undefined : JSON.stringify(body) }));
  }

  return {
    /** Runs, the coverage receipt, what each platform's routes can do, and the analysis in progress (any member). */
    list: (w: string) => get<VoiceImportsView>(base(w)),
    /** One consent for the whole account or upload. An official run then proceeds on the server; an export run waits for `sendItems`. */
    request: (w: string, body: ImportRequest) => send<{ import: VoiceImport }>('POST', base(w), body),
    /** At most 200 records and 512 kB. `final` closes the upload. */
    sendItems: (w: string, importId: string, body: ItemsBody) => send<{ import: VoiceImport }>('POST', `${base(w)}/${seg(importId)}/items`, body),
    cancel: (w: string, importId: string) => send<{ import: VoiceImport }>('POST', `${base(w)}/${seg(importId)}/cancel`),
    /** A new run from where the last one stopped. */
    refresh: (w: string, importId: string) => send<{ import: VoiceImport }>('POST', `${base(w)}/${seg(importId)}/refresh`),
    /** Removes the run and the posts this account supplied. */
    remove: (w: string, importId: string) => send<{ deleted: boolean; posts: number }>('DELETE', `${base(w)}/${seg(importId)}`),
    /** Up to 50 posts with short excerpts, for display to workspace members. */
    posts: (w: string, query: PostQuery = {}) => {
      const search = new URLSearchParams();
      for (const key of ['provider', 'accountKey', 'status', 'cursor'] as const) {
        const value = query[key];
        if (value) search.set(key, value);
      }
      const suffix = search.toString();
      return get<VoicePostPage>(`${base(w)}/posts${suffix ? `?${suffix}` : ''}`);
    },
    correctPost: (w: string, postId: string, body: PostCorrection) => send<{ post: VoicePost }>('POST', `${base(w)}/posts/${seg(postId)}`, body),
    /** Owner only: the cost of an AI reading of the eligible posts. Nothing is spent by asking. */
    analysisQuote: (w: string, groupKey?: string) => send<{ quote: Record<string, unknown> }>('POST', `${base(w)}/analysis`, { ...(groupKey ? { groupKey } : {}), quote: true }),
    /** Owner only: starts the analysis a quote described. */
    analysisStart: (w: string, quoteId: string, groupKey?: string) => send<{ analysis: VoiceAnalysis }>('POST', `${base(w)}/analysis`, { ...(groupKey ? { groupKey } : {}), quoteId })
  };
}

export type VoiceImportApi = ReturnType<typeof createVoiceImportApi>;
