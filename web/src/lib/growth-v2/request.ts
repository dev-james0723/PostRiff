/**
 * Shared transport for the RAFII Product Growth routes (first week, sources, relationships, results, series, visual
 * packs, briefs, proof). Same guard header, bearer session and error shape as `@/lib/api/client`; kept separate so the
 * shared client stays untouched (the coworker client follows the same rule). Workspace routes are session-only.
 */
import { ApiError, APP_GUARD_HEADER, type TokenSource } from '@/lib/api/client';

export const ws = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;
export const seg = encodeURIComponent;

/** 404 `feature_disabled`: the deployment has this feature off. The UI hides it instead of showing an error. */
export function isFeatureDisabled(error: unknown): boolean {
  return error instanceof ApiError && error.status === 404 && error.code === 'feature_disabled';
}

/** Client errors are answers, not outages: retrying them only repeats the refusal. */
export function shouldRetry(failureCount: number, error: unknown): boolean {
  if (error instanceof ApiError && error.status >= 400 && error.status < 500) return false;
  return failureCount < 2;
}

export function errorMessage(error: unknown, fallback = 'That did not work. Try again.'): string {
  return error instanceof ApiError || error instanceof Error ? error.message || fallback : fallback;
}

export function errorCode(error: unknown): string | undefined {
  return error instanceof ApiError ? error.code : undefined;
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

export function createRequester(getToken: TokenSource) {
  async function headers(json = true): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { ...(json ? { 'Content-Type': 'application/json' } : {}), ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }
  return {
    get: async <T>(path: string): Promise<T> => parse<T>(await fetch(path, { headers: await headers(false), cache: 'no-store' })),
    send: async <T>(method: 'POST' | 'PUT' | 'PATCH' | 'DELETE', path: string, body: unknown = {}, timeoutMs?: number): Promise<T> =>
      parse<T>(
        await fetch(path, {
          method,
          headers: await headers(),
          body: JSON.stringify(body),
          ...(timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : {})
        })
      ),
    /** Raw bytes upload (source files). The server sniffs content; the declared type is only a hint. */
    upload: async <T>(path: string, file: Blob, contentType: string, extra: Record<string, string> = {}): Promise<T> => {
      const token = await getToken();
      if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
      return parse<T>(
        await fetch(path, {
          method: 'POST',
          headers: { ...APP_GUARD_HEADER, Authorization: `Bearer ${token}`, 'Content-Type': contentType, ...extra },
          body: file
        })
      );
    },
    blob: async (path: string): Promise<Blob> => {
      const res = await fetch(path, { headers: await headers(false) });
      if (!res.ok) await parse(res);
      return res.blob();
    }
  };
}

/** A fresh idempotency key for one user intent (a retry of the same intent reuses it). */
export function idempotencyKey(prefix: string): string {
  const random = typeof crypto !== 'undefined' && 'randomUUID' in crypto ? crypto.randomUUID() : `${Date.now()}-${Math.random()}`;
  return `${prefix}-${random}`.replace(/[^A-Za-z0-9_-]/g, '').slice(0, 80);
}
