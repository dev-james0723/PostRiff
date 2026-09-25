/**
 * Typed browser client for the Rafii coworker routes (docs/design/site-agent/adaptive-social-coworker/API.md).
 * Same guard header, bearer session and error shape as `@/lib/api/client`; kept separate so the shared client
 * stays untouched. Workspace routes are session-only: the server refuses API tokens.
 */
import { ApiError, APP_GUARD_HEADER, type TokenSource } from '@/lib/api/client';
import type {
  AttentionResponse,
  CoworkerStatus,
  EngagementSummary,
  ListeningView,
  MarkResult,
  NoteInput,
  NotificationCenter,
  NotificationPreferences,
  Opportunity,
  OverlayItem,
  OverlaysView,
  PerformanceView,
  PreferencePatch,
  PreferenceSaved,
  PrepareResult,
  PushDevice,
  PushSubscriptionBody,
  Recipe,
  RecipeInput,
  SlotAction,
  SlotActionResult,
  Verified,
  Watchlist,
  WeekDetail,
  WeeklyList
} from './types';

const ws = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;
const seg = encodeURIComponent;

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

export function createCoworkerApi(getToken: TokenSource) {
  async function headers(): Promise<Record<string, string>> {
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { 'Content-Type': 'application/json', ...APP_GUARD_HEADER, Authorization: `Bearer ${token}` };
  }
  async function get<T>(path: string): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(), cache: 'no-store' }));
  }
  async function send<T>(method: string, path: string, body: unknown = {}): Promise<T> {
    return parse<T>(await fetch(path, { method, headers: await headers(), body: method === 'DELETE' ? undefined : JSON.stringify(body) }));
  }
  const co = (w: string) => `${ws(w)}/coworker`;

  return {
    /* status + attention */
    status: (w: string) => get<CoworkerStatus>(`${co(w)}/status`),
    attention: (w: string) => get<AttentionResponse>(`${co(w)}/attention`),

    /* notification centre */
    notifications: (w: string, options: { unread?: boolean; before?: number } = {}) => {
      const query = new URLSearchParams();
      if (options.unread) query.set('unread', '1');
      if (options.before) query.set('before', String(options.before));
      const suffix = query.toString();
      return get<NotificationCenter>(`${ws(w)}/notifications${suffix ? `?${suffix}` : ''}`);
    },
    markNotification: (w: string, deliveryId: string, action: 'read' | 'acted' | 'dismissed') =>
      send<MarkResult>('POST', `${ws(w)}/notifications/${seg(deliveryId)}/${action}`),
    preferences: (w: string) => get<NotificationPreferences>(`${ws(w)}/notification-preferences`),
    setPreference: (w: string, patch: PreferencePatch) => send<PreferenceSaved>('PATCH', `${ws(w)}/notification-preferences`, patch),
    pushDevices: (w: string) => get<{ devices: PushDevice[] }>(`${ws(w)}/push-subscriptions`),
    subscribePush: (w: string, body: PushSubscriptionBody) => send<{ subscriptionId: string; active: boolean } & Verified>('POST', `${ws(w)}/push-subscriptions`, body),
    unsubscribePushEndpoint: (w: string, endpoint: string) => send<{ revoked: number } & Verified>('POST', `${ws(w)}/push-subscriptions/unsubscribe`, { endpoint }),
    revokePushDevice: (w: string, subscriptionId: string) => send<{ revoked: number } & Verified>('DELETE', `${ws(w)}/push-subscriptions/${seg(subscriptionId)}`),

    /* weekly social operator */
    weekly: (w: string) => get<WeeklyList>(`${co(w)}/weekly`),
    createRecipe: (w: string, input: RecipeInput) => send<{ recipe: Recipe | null } & Verified>('POST', `${co(w)}/weekly/recipes`, input),
    updateRecipe: (w: string, recipeId: string, input: RecipeInput) => send<{ recipe: Recipe | null } & Verified>('PATCH', `${co(w)}/weekly/recipes/${seg(recipeId)}`, input),
    recipeStatus: (w: string, recipeId: string, status: 'active' | 'paused' | 'deleted') =>
      send<{ recipe: Recipe | null } & Verified>('POST', `${co(w)}/weekly/recipes/${seg(recipeId)}/status`, { status }),
    prepareWeek: (w: string, recipeId: string) => send<PrepareResult>('POST', `${co(w)}/weekly/recipes/${seg(recipeId)}/prepare`, {}),
    week: (w: string, weekId: string) => get<WeekDetail>(`${co(w)}/weekly/weeks/${seg(weekId)}`),
    slotAction: (w: string, weekId: string, slotId: string, action: SlotAction, body: { answer?: string; reason?: string } = {}) =>
      send<SlotActionResult>('POST', `${co(w)}/weekly/weeks/${seg(weekId)}/slots/${seg(slotId)}/${action}`, body),

    /* personalization */
    overlays: (w: string) => get<OverlaysView>(`${co(w)}/overlays`),
    exportOverlays: (w: string) => get<OverlaysView & { schema: string; exportedAt: number }>(`${co(w)}/overlays/export`),
    addNote: (w: string, input: NoteInput) => send<{ note: OverlayItem | null } & Verified>('POST', `${co(w)}/overlays/notes`, input),
    editNote: (w: string, noteId: string, input: NoteInput) => send<{ note: OverlayItem | null } & Verified>('PATCH', `${co(w)}/overlays/notes/${seg(noteId)}`, input),
    overlayStatus: (w: string, itemId: string, status: 'active' | 'disabled' | 'retired') =>
      send<{ id: string; status: string | null } & Verified>('POST', `${co(w)}/overlays/${seg(itemId)}/status`, { status }),
    resetOverlays: (w: string, scope: 'notes' | 'learned' | 'all') => send<{ reset: string; remaining: number } & Verified>('POST', `${co(w)}/overlays/reset`, { scope, confirmed: true }),

    /* performance learning */
    performance: (w: string) => get<PerformanceView>(`${co(w)}/performance`),
    decideHypothesis: (w: string, id: string, decision: 'experiment' | 'dismissed' | 'rejected') =>
      send<{ id: string; status: string; causal: boolean } & Verified>('POST', `${co(w)}/performance/hypotheses/${seg(id)}/decide`, { decision }),

    /* listening + engagement */
    listening: (w: string) => get<ListeningView>(`${co(w)}/listening`),
    saveWatchlist: (w: string, input: { query: string; goal: string }) => send<{ watchlist: Watchlist | null } & Verified>('POST', `${co(w)}/listening/watchlists`, input),
    decideOpportunity: (w: string, id: string, decision: 'act' | 'dismiss') =>
      send<{ opportunity: Opportunity | null } & Verified>('POST', `${co(w)}/listening/opportunities/${seg(id)}/decide`, { decision }),
    engagement: (w: string) => get<EngagementSummary>(`${co(w)}/engagement`)
  };
}

export type CoworkerApi = ReturnType<typeof createCoworkerApi>;
