/**
 * Browser client for the hosted PostRiff API. Every request carries the
 * application guard header and, when signed in, the session bearer token.
 * The token source is injected so Supabase and the local dev harness share
 * one client (see `@/lib/auth/session`).
 */
import type {
  ToolRegistry,
  Analytics,
  Audience,
  AuditEvent,
  Bootstrap,
  Catalog,
  ChannelView,
  Conversation,
  DataRequest,
  Health,
  Invitation,
  InvitationCreated,
  LearningSummary,
  Me,
  Member,
  Membership,
  MemoryEgress,
  MemoryFile,
  MemoryProposals,
  Message,
  ModelCatalog,
  MyChannel,
  OAuthComplete,
  OAuthStart,
  PendingInvitation,
  PrivacyNotice,
  ProfileChanges,
  ProviderView,
  ResearchEgress,
  Run,
  SecurityEvent,
  SessionInfo,
  Snapshot,
  Usage,
  WorkspaceListItem
} from './types';

/** Value the API checks on every mutation (`hosted_app._origin`). */
export const APP_GUARD_HEADER = { 'X-PostRiff-Request': 'founder-alpha' } as const;

export class ApiError extends Error {
  status: number;
  code?: string;
  constructor(message: string, status: number, code?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
  }
}

export type TokenSource = () => Promise<string | null>;

const ws = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;

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
    throw new ApiError(message, res.status, code);
  }
  if (res.status === 204) return undefined as T;
  return res.json() as Promise<T>;
}

export function createApi(getToken: TokenSource) {
  async function headers(auth = true): Promise<Record<string, string>> {
    const base: Record<string, string> = { 'Content-Type': 'application/json', ...APP_GUARD_HEADER };
    if (!auth) return base;
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { ...base, Authorization: `Bearer ${token}` };
  }

  async function get<T>(path: string, auth = true): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(auth), cache: 'no-store' }));
  }

  async function send<T>(method: string, path: string, body: unknown = {}): Promise<T> {
    return parse<T>(
      await fetch(path, { method, headers: await headers(), body: JSON.stringify(body) })
    );
  }

  async function blob(path: string): Promise<Blob> {
    const res = await fetch(path, { headers: await headers() });
    if (!res.ok) await parse(res);
    return res.blob();
  }

  return {
    /* public */
    tools: () => get<ToolRegistry>('/api/tools', false),
    catalog: () => get<Catalog>('/api/catalog', false),
    health: () => get<Health>('/api/health', false),
    privacyNotice: () => get<PrivacyNotice>('/api/privacy/notice', false),
    models: () => get<ModelCatalog>('/api/ideas/models', false),
    rescanModels: (w: string) => send<ModelCatalog>('POST', '/api/ideas/models/rescan', { workspaceId: w }),

    /* account & workspaces */
    bootstrap: (plan: string) => send<Bootstrap>('POST', '/api/auth/verify', { plan }),
    logout: () => send<{ signedOut: boolean }>('POST', '/api/auth/logout'),
    workspaces: () => get<{ workspaces: WorkspaceListItem[] }>('/api/workspaces'),
    sessions: () => get<{ sessions: SessionInfo[] }>('/api/auth/sessions'),
    revokeSession: (sessionId: string) =>
      send<{ sessionId: string; revoked: boolean }>('DELETE', `/api/auth/sessions/${encodeURIComponent(sessionId)}`),
    acceptInvitation: (token: string) =>
      send<{ workspaceId: string; role: string }>('POST', '/api/invitations/accept', { token }),
    leaveWorkspace: (w: string) => send<{ workspaceId: string; status: string }>('POST', `${ws(w)}/leave`),

    /* the signed-in person */
    me: () => get<Me>('/api/me'),
    updateProfile: (changes: ProfileChanges) =>
      send<{ displayName: string; preferences: Me['preferences'] }>('PATCH', '/api/me', changes),
    myChannels: () => get<{ channels: MyChannel[] }>('/api/me/channels'),
    securityEvents: () => get<{ events: SecurityEvent[] }>('/api/me/security-events'),
    /* `available` is false when the deployment cannot confirm the person's email (the dev harness without a lookup) */
    myInvitations: () => get<{ invitations: PendingInvitation[]; available: boolean }>('/api/me/invitations'),
    acceptMyInvitation: (id: string) =>
      send<{ workspaceId: string; role: string }>('POST', `/api/me/invitations/${encodeURIComponent(id)}/accept`),
    declineMyInvitation: (id: string) =>
      send<{ invitationId: string; state: string }>('POST', `/api/me/invitations/${encodeURIComponent(id)}/decline`),
    enableMfa: () => send<{ enforced: boolean; enforcedAt: number | null }>('POST', '/api/auth/mfa'),
    disableMfa: () => send<{ enforced: boolean; enforcedAt: number | null }>('DELETE', '/api/auth/mfa'),
    revokeOtherSessions: () =>
      send<{ revoked: number; refreshRevoked: boolean; current: string }>('POST', '/api/auth/sessions/revoke-others'),

    /* snapshot + single mutation channel */
    snapshot: (w: string) => get<Snapshot>(ws(w)),
    act: (w: string, expectedRevision: number, action: string, payload: Record<string, unknown> = {}) =>
      send<Snapshot>('POST', `${ws(w)}/actions`, { expectedRevision, action, payload }),
    media: (w: string, assetId: string) => blob(`${ws(w)}/media/${encodeURIComponent(assetId)}`),
    exportDrafts: (w: string) => blob(`${ws(w)}/export`),
    exportProfile: (w: string) => blob(`${ws(w)}/profile-export`),
    memory: (w: string) => get<{ files: MemoryFile[]; egress?: MemoryEgress; research?: ResearchEgress; learning?: LearningSummary }>(`${ws(w)}/memory`),
    /* learned preferences: proposals an owner decides, items an owner can pause or retire */
    memoryProposals: (w: string) => get<MemoryProposals>(`${ws(w)}/memory/proposals`),
    decideProposal: (w: string, id: string, body: { decision: 'remember' | 'edit' | 'dismiss' | 'post_only'; statement?: string; expectedRevision: number }) =>
      send<{ revision: number; proposalId: string; status: string; learning: LearningSummary }>('POST', `${ws(w)}/memory/proposals/${encodeURIComponent(id)}/decide`, body),
    updateLearnedItem: (w: string, id: string, status: 'active' | 'paused' | 'retired', expectedRevision: number) =>
      send<{ revision: number; itemId: string; status: string; learning: LearningSummary }>('PATCH', `${ws(w)}/memory/versions/${encodeURIComponent(id)}`, { status, expectedRevision }),
    deleteAccount: (w: string, confirmation: string) =>
      send<{ deleted: boolean }>('DELETE', `${ws(w)}/account`, { confirmation }),

    /* usage & billing */
    usage: (w: string) => get<Usage>(`${ws(w)}/usage`),
    checkout: (w: string, planTermsId: string, successPath?: string, cancelPath?: string) =>
      send<{ url: string; sessionId: string }>('POST', `${ws(w)}/billing/checkout`, {
        planTermsId,
        successPath,
        cancelPath
      }),
    portal: (w: string, returnPath?: string) =>
      send<{ url: string }>('POST', `${ws(w)}/billing/portal`, { returnPath }),

    /* channels */
    channels: (w: string) => get<{ channels: ChannelView[]; providers: ProviderView[] }>(`${ws(w)}/channels`),
    oauthStart: (w: string, provider: string, capability = 'publish') =>
      send<OAuthStart>('POST', `${ws(w)}/channels/${encodeURIComponent(provider)}/oauth/start`, { capability }),
    oauthComplete: (w: string, provider: string, state: string, code?: string, error?: string) =>
      send<OAuthComplete>('POST', `${ws(w)}/channels/${encodeURIComponent(provider)}/oauth/complete`, {
        state,
        code,
        error
      }),
    verifyChannel: (w: string, id: string) =>
      send<{ connectionId: string; state: string; identityVerified: boolean; detail?: string }>(
        'POST',
        `${ws(w)}/channels/${encodeURIComponent(id)}/verify`
      ),
    disconnectChannel: (w: string, id: string) =>
      send<{ disconnected: boolean; remoteRevoked: boolean; revision: number }>(
        'DELETE',
        `${ws(w)}/channels/${encodeURIComponent(id)}`
      ),

    /* ideas */
    conversations: (w: string) => get<{ conversations: Conversation[] }>(`${ws(w)}/ideas/conversations`),
    createConversation: (w: string, title: string) =>
      send<Conversation>('POST', `${ws(w)}/ideas/conversations`, { title }),
    messages: (w: string, id: string) =>
      get<Conversation & { messages: Message[] }>(`${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/messages`),
    turn: (w: string, id: string, body: Record<string, unknown>) =>
      send<Run>('POST', `${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/turns`, body),
    attach: (w: string, id: string, body: Record<string, unknown>) =>
      send<Record<string, unknown>>('POST', `${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/attachments`, body),
    runEvents: (w: string, runId: string, cursor = 0) =>
      get<Run>(`${ws(w)}/ideas/runs/${encodeURIComponent(runId)}/events?cursor=${cursor}`),
    cancelRun: (w: string, runId: string) =>
      send<{ runId: string; status: string }>('POST', `${ws(w)}/ideas/runs/${encodeURIComponent(runId)}/cancel`),
    applyRun: (w: string, runId: string, expectedRevision: number, artifactHash: string) =>
      send<{ runId: string; status: string; revision: number; variants?: number }>(
        'POST',
        `${ws(w)}/ideas/runs/${encodeURIComponent(runId)}/apply`,
        { expectedRevision, artifactHash }
      ),
    quickStart: (w: string, expectedRevision: number, body: Record<string, unknown>) =>
      send<Run & { sourceId: string; sourcePolicy: string; revision: number }>('POST', `${ws(w)}/ideas/quick-start`, {
        expectedRevision,
        ...body
      }),

    /* analytics & audience */
    analytics: (w: string) => get<Analytics>(`${ws(w)}/analytics/summary`),
    audience: (w: string) => get<Audience>(`${ws(w)}/audience/threads`),
    draftReply: (w: string, threadId: string, body: Record<string, unknown>) =>
      send<{ draftId: string; origin: string; text: string; label: string }>(
        'POST',
        `${ws(w)}/audience/threads/${encodeURIComponent(threadId)}/reply-drafts`,
        body
      ),
    replyPreview: (w: string, draftId: string) =>
      send<{ manifest: Record<string, unknown>; digest: string; action: string; replyLevel: string }>(
        'POST',
        `${ws(w)}/audience/reply-drafts/${encodeURIComponent(draftId)}/reply-preview`
      ),
    approveReply: (w: string, draftId: string, digest: string) =>
      send<{ draftId: string; status: string; note?: string }>(
        'POST',
        `${ws(w)}/audience/reply-drafts/${encodeURIComponent(draftId)}/reply`,
        { digest, confirmed: true }
      ),

    /* members, invitations, audit */
    members: (w: string) => get<{ members: Member[]; membership: Membership }>(`${ws(w)}/members`),
    updateMember: (w: string, userId: string, role: string, permissions: Record<string, boolean>) =>
      send<Record<string, unknown>>('PATCH', `${ws(w)}/members/${encodeURIComponent(userId)}`, { role, permissions }),
    removeMember: (w: string, userId: string) =>
      send<{ userId: string; status: string; note?: string }>('DELETE', `${ws(w)}/members/${encodeURIComponent(userId)}`),
    transferOwnership: (w: string, newOwnerId: string) =>
      send<{ ownerId: string; previousOwnerId: string }>('POST', `${ws(w)}/transfer-ownership`, { newOwnerId }),
    invitations: (w: string) => get<{ invitations: Invitation[] }>(`${ws(w)}/invitations`),
    invite: (w: string, email: string, role: string, permissions: Record<string, boolean> = {}) =>
      send<InvitationCreated>('POST', `${ws(w)}/invitations`, { email, role, permissions }),
    revokeInvitation: (w: string, invitationId: string) =>
      send<{ invitationId: string; state: string }>('DELETE', `${ws(w)}/invitations/${encodeURIComponent(invitationId)}`),
    audit: (w: string) => get<{ events: AuditEvent[] }>(`${ws(w)}/audit`),

    /* privacy */
    dataRequests: (w: string) => get<{ requests: DataRequest[] }>(`${ws(w)}/data-requests`),
    dataRequest: (w: string, body: Record<string, unknown>) =>
      send<Record<string, unknown> & { kind: string; status: string }>('POST', `${ws(w)}/data-requests`, body)
  };
}

export type PostRiffApi = ReturnType<typeof createApi>;

/** Micro-dollars → display. `null` is shown as an em dash, never as $0. */
export function usd(micro: number | null | undefined) {
  return micro == null ? '—' : `$${(micro / 1_000_000).toFixed(2)}`;
}

/** Cents → display in the plan currency. */
export function cents(value: number, currency = 'USD') {
  return new Intl.NumberFormat('en-US', { style: 'currency', currency, minimumFractionDigits: 0 }).format(
    value / 100
  );
}
