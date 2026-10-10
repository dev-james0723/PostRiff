import type { Recipe, RecipeList, RecipeReport, RecipeSettings } from '@/features/workflow-recipes/types';
import type { LibraryMetadataHistory, LibraryMetadataReceipt, LibraryMetadataSelection } from './library-metadata';
import type { YouTubeOverview, YouTubeActionReview, YouTubeActionReceipt, YouTubeData, YouTubeAgentOverview, YouTubeAgentDraft, YouTubeAgentPolicy, YouTubeAgentMutation, YouTubePolicyStatus, YouTubeAgentPageOptions, YouTubeAgentHistory, YouTubeAgentArchiveResult } from '@/lib/youtube/types';
import type { RadarCatalog, RadarScan, RadarRequest } from '@/lib/growth/radar-types';
import type { PhoneAuthChallenge, TrustedCaller } from '@/lib/phone/types';
import type { HistoryImportStatus } from '@/lib/channels/history-import';
import type { ConnectionHealth } from '@/lib/channels/health';
/**
 * Browser client for the hosted PostRiff API. Every request carries the
 * application guard header and, when signed in, the session bearer token.
 * The token source is injected so Supabase and the local dev harness share
 * one client (see `@/lib/auth/session`).
 */
import type {
  ToolRegistry,
  WorkspaceApiToken, ApiTokenCreated, TokenScope,
  Analytics,
  Asset,
  Audience,
  AuditEvent,
  Bootstrap,
  Catalog,
  ChannelDestination,
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
  MemoryProposals,
  Message,
  MessageWindow,
  MediaMoment,
  NavigationItem,
  NavigationConversation,
  NavigationSearchResult,
  ModelCatalog,
  MyChannel,
  OAuthComplete,
  OAuthStart,
  PendingInvitation,
  PrivacyNotice,
  ProfileChanges,
  ProviderView,
  Run,
  CreditEstimate,
  MediaNotesBody,
  MediaNotesCreditBody,
  MediaNotesResult,
  MemoryFiles,
  PickerCategory,
  PickerSearchResult,
  SkillPreview,
  ProductivityConnectorCatalog,
  ProductivityConnectorSearchResult,
  VideoCommitBody,
  VideoCommitResult,
  VideoUploadBegin,
  VideoUploadTicket,
  VideoResumeTicket,
  SecurityEvent,
  SessionInfo,
  Snapshot,
  ActiveTimeBeat,
  TimeSavingsCalibrationInput,
  TimeSavingsRange,
  TimeSavingsSummary,
  TimeSavingsTaskKind,
  Usage,
  WorkspaceListItem
} from './types';
import type { HelpDocument, HelpDocumentSummary, SiteAgentBody, SiteAgentInsights, SiteAgentMessageBody, SiteAgentProposalView, SiteAgentTurnResult } from '@/lib/site-agent/types';
import type { AgentStylePatch } from '@/lib/agent-runtime/style';
import type { PhoneCall, PhoneInboundCode, PhoneInboundStatus, PhonePreferences, PhoneProviderReadiness, PhoneSettingsData } from '@/lib/phone/types';
import type { TikTokCreatorInfo } from '@/lib/channels/tiktok-rules';
import type { GrowthCatalog, PostCheck, PostRewrite, GenomeResponse, CreatorGenome, PerformanceFeedback, DraftCheckBody, GrowthOverview, Postmortem, AudienceInsights } from '@/lib/growth/types';

/** Value the API checks on every mutation (`hosted_app._origin`). */
export const APP_GUARD_HEADER = { 'X-PostRiff-Request': 'founder-alpha' } as const;

export class ApiError extends Error {
  status: number;
  code?: string;
  requestId?: string;
  constructor(message: string, status: number, code?: string, requestId?: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    this.code = code;
    this.requestId = requestId;
  }
}

export type TokenSource = () => Promise<string | null>;

const ws = (id: string) => `/api/workspaces/${encodeURIComponent(id)}`;
/** A drafting request that has not answered by then is treated as a lost response and resent with its key. */
const DRAFT_TIMEOUT_MS = 150_000;

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

export function createApi(getToken: TokenSource) {
  async function headers(auth = true): Promise<Record<string, string>> {
    const base: Record<string, string> = { 'Content-Type': 'application/json', ...APP_GUARD_HEADER };
    if (!auth) return base;
    const token = await getToken();
    if (!token) throw new ApiError('Your session ended. Sign in again.', 401);
    return { ...base, Authorization: `Bearer ${token}` };
  }

  async function get<T>(path: string, auth = true, timeoutMs?: number): Promise<T> {
    return parse<T>(await fetch(path, { headers: await headers(auth), cache: 'no-store', ...(timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : {}) }));
  }

  async function send<T>(method: string, path: string, body: unknown = {}, timeoutMs?: number): Promise<T> {
    return parse<T>(
      await fetch(path, { method, headers: await headers(), body: JSON.stringify(body), ...(timeoutMs ? { signal: AbortSignal.timeout(timeoutMs) } : {}) })
    );
  }

  async function blob(path: string): Promise<Blob> {
    const res = await fetch(path, { headers: await headers() });
    if (!res.ok) await parse(res);
    return res.blob();
  }

  return {
    workflowRecipes: (w: string) => get<RecipeList>(`${ws(w)}/agent/recipes`),
    saveWorkflowRecipe: (w: string, settings: RecipeSettings, expectedVersion: number | null, id?: string) => send<Recipe>(id ? 'PUT' : 'POST', `${ws(w)}/agent/recipes${id ? '/' + encodeURIComponent(id) : ''}`, { settings, expectedVersion }),
    enableWorkflowRecipe: (w: string, id: string, expectedVersion: number, permissionToken: string, requestKey: string) => send<Recipe>('POST', `${ws(w)}/agent/recipes/${encodeURIComponent(id)}/enable`, { expectedVersion, permissionToken, requestKey, confirmed: true }),
    stopWorkflowRecipe: (w: string, id: string, expectedVersion: number, status: 'paused' | 'revoked') => send<Recipe>('POST', `${ws(w)}/agent/recipes/${encodeURIComponent(id)}/stop`, { expectedVersion, status }),
    runWorkflowRecipe: (w: string, id: string, expectedVersion: number, requestKey: string) => send<RecipeList>('POST', `${ws(w)}/agent/recipes/${encodeURIComponent(id)}/run`, { expectedVersion, requestKey }),
    workflowRecipeReport: (w: string, id: string) => get<RecipeReport>(`${ws(w)}/agent/recipes/reports/${encodeURIComponent(id)}`),
    /* Growth advice never sends a post. Each model request has its own explicit confirmation. */
    radarCatalog: (w: string) => get<RadarCatalog>(`${ws(w)}/growth/radar/catalog`),
    radarScans: (w: string) => get<{ scans: RadarScan[] }>(`${ws(w)}/growth/radar/scans`),
    radarQuote: (w: string, body: RadarRequest) => send<RadarScan>('POST', `${ws(w)}/growth/radar/quotes`, body),
    radarStart: (w: string, id: string) => send<RadarScan>('POST', `${ws(w)}/growth/radar/${encodeURIComponent(id)}/start`, { confirmed: true }),
    radarAdvance: (w: string, id: string) => send<RadarScan>('POST', `${ws(w)}/growth/radar/${encodeURIComponent(id)}/advance`, {}, 90_000),
    growthCatalog: (w: string) => get<GrowthCatalog>(`${ws(w)}/growth/catalog`),
    postDoctor: (w: string, body: DraftCheckBody) => send<PostCheck>('POST', `${ws(w)}/growth/check`, body, 30_000),
    postDoctorRewrite: (w: string, body: { checkId: string; model: string; facts: Record<string, string>; confirmed: boolean; requestKey: string }) => send<PostRewrite>('POST', `${ws(w)}/growth/rewrite`, body, 90_000),
    creatorGenome: (w: string) => get<GenomeResponse>(`${ws(w)}/growth/genome`),
    analyzeHistory: (w: string, body: { data?: string; account?: string; connectionId?: string; sourceIds?: string[]; ownContent: boolean; retainText: boolean; confirmed: boolean; requestKey: string }) => send<{ genome: CreatorGenome }>('POST', `${ws(w)}/growth/history`, body, 240_000),
    performanceFeedback: (w: string, jobId: string) => get<PerformanceFeedback>(`${ws(w)}/growth/feedback/${encodeURIComponent(jobId)}`),
    growthOverview: (w: string) => get<GrowthOverview>(`${ws(w)}/growth/postmortems`),
    postmortem: (w: string, body: { jobId: string; horizon: string; confirmed: boolean; requestKey: string }) => send<Postmortem>('POST', `${ws(w)}/growth/postmortems`, body, 90_000),
    audienceInsights: (w: string) => get<AudienceInsights>(`${ws(w)}/growth/audience`),
    analyzeAudience: (w: string, body: { days: number; confirmed: boolean; requestKey: string }) => send<{ clusters: AudienceInsights['clusters']; analyzed: number; available: number; withheld: number; partial: boolean }>('POST', `${ws(w)}/growth/audience`, body, 240_000),
    publicPostDoctor: async (body: { text: string; platform: string; language: string; confirmed: boolean }) => parse<PostCheck>(await fetch('/api/post-doctor', { method: 'POST', headers: await headers(false), body: JSON.stringify(body), signal: AbortSignal.timeout(30_000) })),
    contentDNA: (token: string) => get<{ labels: string[]; description: string }>(`/api/content-dna/${encodeURIComponent(token)}`, false),
    /* public */
    tools: () => get<ToolRegistry>('/api/tools', false),
    catalog: () => get<Catalog>('/api/catalog', false),
    health: () => get<Health>('/api/health', false),
    privacyNotice: () => get<PrivacyNotice>('/api/privacy/notice', false),
    models: () => get<ModelCatalog>('/api/ideas/models', false),
    rescanModels: (w: string) => send<ModelCatalog>('POST', '/api/ideas/models/rescan', { workspaceId: w }),

    tokens: (w: string) => get<{ tokens: WorkspaceApiToken[] }>(`${ws(w)}/tokens`),
    createToken: (w: string, input: { name: string; scopes: TokenScope[]; expiresDays: number }) => send<ApiTokenCreated>('POST', `${ws(w)}/tokens`, input),
    revokeToken: (w: string, id: string) => send<{ tokenId: string; revoked: boolean }>('DELETE', `${ws(w)}/tokens/${encodeURIComponent(id)}`),

    /* account & workspaces */
    bootstrap: (plan: string) => send<Bootstrap>('POST', '/api/auth/verify', { plan }),
    logout: () => send<{ signedOut: boolean }>('POST', '/api/auth/logout'),
    workspaces: () => get<{ workspaces: WorkspaceListItem[] }>('/api/workspaces'),
    sessions: () => get<{ sessions: SessionInfo[] }>('/api/auth/sessions'),
    revokeSession: (sessionId: string) =>
      send<{ sessionId: string; revoked: boolean }>('DELETE', `/api/auth/sessions/${encodeURIComponent(sessionId)}`),
    acceptInvitation: (token: string) =>
      send<{ workspaceId: string } & Membership>('POST', '/api/invitations/accept', { token }),
    leaveWorkspace: (w: string) => send<{ workspaceId: string; status: string }>('POST', `${ws(w)}/leave`),

    /* the signed-in person */
    me: () => get<Me>('/api/me'),
    updateProfile: (changes: ProfileChanges) =>
      send<{ displayName: string; preferences: Me['preferences'] }>('PATCH', '/api/me', changes),
    /** How Rafii talks: the server validates the patch, merges it into the saved style and returns every preference. */
    updateAgentStyle: (patch: AgentStylePatch) =>
      send<{ displayName: string; preferences: Me['preferences'] }>('PATCH', '/api/me', { agentStyle: patch } satisfies ProfileChanges),
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
    /** A connected account's profile picture; the digest in the URL makes a changed picture a new request. */
    channelPicture: (w: string, channelId: string, digest: string) =>
      blob(`${ws(w)}/channels/${encodeURIComponent(channelId)}/picture?v=${encodeURIComponent(digest)}`),
    exportDrafts: (w: string) => blob(`${ws(w)}/export`),
    exportProfile: (w: string) => blob(`${ws(w)}/profile-export`),
    memory: (w: string) => get<MemoryFiles>(`${ws(w)}/memory`),
    /* learned preferences: proposals an owner decides, items an owner can pause or retire */
    memoryProposals: (w: string) => get<MemoryProposals>(`${ws(w)}/memory/proposals`),
    decideProposal: (w: string, id: string, body: { decision: 'remember' | 'edit' | 'dismiss' | 'post_only'; statement?: string; expectedRevision: number }) =>
      send<{ revision: number; proposalId: string; status: string; learning: LearningSummary }>('POST', `${ws(w)}/memory/proposals/${encodeURIComponent(id)}/decide`, body),
    updateLearnedItem: (w: string, id: string, status: 'active' | 'paused' | 'retired', expectedRevision: number) =>
      send<{ revision: number; itemId: string; status: string; learning: LearningSummary }>('PATCH', `${ws(w)}/memory/versions/${encodeURIComponent(id)}`, { status, expectedRevision }),
    deleteAccount: (w: string, confirmation: string) =>
      send<{ deleted: boolean; workspaceDeleted: boolean; identityDeleted: boolean; receiptId: string; providerRevocationPending?: string[] }>('DELETE', `${ws(w)}/account`, { confirmation }),

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
    /* `connectionHealth` is present only where the server admits this workspace to the Health Center (RAFII_CONNECTION_HEALTH_ENABLED). */
    channels: (w: string) => get<{ channels: ChannelView[]; providers: ProviderView[]; connectionHealth?: { available: boolean; href: string } }>(`${ws(w)}/channels`),
    connectionHealth: (w: string) => get<ConnectionHealth>(`${ws(w)}/connection-health`),
    youtubePolicy: (w: string) => get<YouTubePolicyStatus>(`${ws(w)}/youtube-policy`),
    acceptYouTubePolicy: (w: string, body: { policyId: string; privacyRevision: string; termsRevision: string; confirmed: true }) =>
      send<YouTubePolicyStatus>('POST', `${ws(w)}/youtube-policy`, body),
    youtubeOverview: (w: string, c: string) =>
      get<YouTubeOverview>(`${ws(w)}/youtube/${encodeURIComponent(c)}`),
    youtubeAgent: (w: string, c: string, options: YouTubeAgentPageOptions = {}) => {
      const query = new URLSearchParams({ limit: String(options.limit ?? 25) });
      if (options.draftCursor) query.set('draftCursor', options.draftCursor);
      if (options.policyCursor) query.set('policyCursor', options.policyCursor);
      return get<YouTubeAgentOverview>(`${ws(w)}/youtube/${encodeURIComponent(c)}/agent?${query}`);
    },
    youtubeAgentHistory: (w: string, c: string, kind: 'draft' | 'policy', options: { cursor?: string; limit?: number } = {}) => {
      const query = new URLSearchParams({ limit: String(options.limit ?? 25) });
      if (options.cursor) query.set('cursor', options.cursor);
      return get<YouTubeAgentHistory>(`${ws(w)}/youtube/${encodeURIComponent(c)}/agent/history/${kind}?${query}`);
    },
    youtubeAgentArchive: (w: string, c: string, body: { revision: number }) =>
      send<Omit<YouTubeAgentMutation<YouTubeAgentArchiveResult>, 'queued'>>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/agent/history/archive`, body),
    youtubeAgentPrepare: (w: string, c: string, body: Record<string, unknown>) =>
      send<YouTubeAgentMutation<YouTubeAgentDraft>>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/agent/drafts`, body),
    youtubeAgentApprove: (w: string, c: string, id: string, body: Record<string, unknown>) =>
      send<YouTubeAgentMutation<YouTubeAgentDraft>>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/agent/drafts/${encodeURIComponent(id)}/approve`, body),
    youtubeAgentPolicyPreview: (w: string, c: string, body: Record<string, unknown>) =>
      send<YouTubeAgentMutation<YouTubeAgentPolicy>>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/agent/policies/preview`, body),
    youtubeAgentPolicyAction: (w: string, c: string, id: string, action: 'activate' | 'pause' | 'revoke', body: Record<string, unknown>) =>
      send<YouTubeAgentMutation<YouTubeAgentPolicy>>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/agent/policies/${encodeURIComponent(id)}/${action}`, body),
    youtubeRead: (w: string, c: string, resource: string, query: Record<string, unknown> = {}) =>
      send<YouTubeData>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/read/${encodeURIComponent(resource)}`,
        query
      ),
    youtubePreview: (w: string, c: string, body: Record<string, unknown>) =>
      send<YouTubeActionReview>('POST', `${ws(w)}/youtube/${encodeURIComponent(c)}/preview`, body),
    youtubeApprove: (w: string, c: string, id: string, body: Record<string, unknown>) =>
      send<YouTubeActionReceipt>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/actions/${encodeURIComponent(id)}/approve`,
        body
      ),
    youtubeActions: (w: string, c: string) =>
      get<{ actions: YouTubeActionReceipt[] }>(`${ws(w)}/youtube/${encodeURIComponent(c)}/actions`),
    youtubeReconcile: (w: string, c: string, id: string) =>
      send<YouTubeActionReceipt>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/actions/${encodeURIComponent(id)}/reconcile`
      ),
    youtubeNotificationPreview: (w: string, c: string, body: Record<string, unknown>) =>
      send<{ id: string; digest: string; manifest: Record<string, unknown> }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/notifications/preview`,
        body
      ),
    youtubeNotificationApprove: (w: string, c: string, id: string, digest: string) =>
      send<{ status: string }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/notifications/${encodeURIComponent(id)}/approve`,
        { confirmed: true, digest }
      ),
    youtubeStreamKey: (w: string, c: string, id: string) =>
      send<{ streamKey: string; sensitive: true }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/actions/${encodeURIComponent(id)}/stream-key`
      ),
    youtubeStreamConfiguration: (w: string, c: string, streamId: string) =>
      send<{ streamId: string; cdn: Record<string, unknown>; sensitive: true }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/stream-configuration`,
        { streamId }
      ),
    youtubeUploadRecovery: (w: string, c: string, key: string) =>
      send<{ manifest: Record<string, unknown>; digest: string }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/uploads/${encodeURIComponent(key)}/review-recovery`
      ),
    youtubeResumeUpload: (w: string, c: string, key: string, digest: string) =>
      send<{ status: string; resumed: boolean }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/uploads/${encodeURIComponent(key)}/resume`,
        { confirmed: true, digest }
      ),
    youtubeSensitive: (
      w: string,
      c: string,
      capability: 'monetary' | 'memberships',
      enabled: boolean
    ) =>
      send<{ authorized: boolean }>(
        'POST',
        `${ws(w)}/youtube/${encodeURIComponent(c)}/sensitive-authorization`,
        { capability, enabled, confirmed: true }
      ),
    oauthStart: (w: string, provider: string, capability = 'identity', input?: Record<string, unknown>) =>
      send<OAuthStart>('POST', `${ws(w)}/channels/${encodeURIComponent(provider)}/oauth/start`, input ? { capability, input } : { capability }),
    oauthComplete: (w: string, provider: string, state: string, code?: string, error?: string, iss?: string) =>
      send<OAuthComplete>('POST', `${ws(w)}/channels/${encodeURIComponent(provider)}/oauth/complete`, {
        state,
        code,
        error,
        ...(iss ? { iss } : {})
      }),
    channelDestinations: (w: string, id: string) =>
      get<{ connectionId: string; scope?: 'connection' | 'post'; destinations: ChannelDestination[] }>(`${ws(w)}/channels/${encodeURIComponent(id)}/destinations`),
    /** TikTok's current creator settings, read fresh each time the composer shows them. */
    creatorInfo: (w: string, id: string) => get<TikTokCreatorInfo>(`${ws(w)}/channels/${encodeURIComponent(id)}/creator-info`),
    chooseChannelDestination: (w: string, id: string, destinationId: string) =>
      send<{ connectionId: string; destinationId: string }>('POST', `${ws(w)}/channels/${encodeURIComponent(id)}/destination`, { destinationId }),
    ownedPosts: (w: string, id: string, cursor?: string) =>
      send<import('./types').OwnedPostPage>('POST', `${ws(w)}/channels/${encodeURIComponent(id)}/posts`, { confirmed: true, cursor: cursor ?? null, limit: 25 }),
    historyImportStatus: (w: string, id: string) =>
      get<HistoryImportStatus>(`${ws(w)}/channels/${encodeURIComponent(id)}/history-import`),
    requestHistoryImport: (w: string, id: string, body: { confirmed: boolean }) =>
      send<HistoryImportStatus>('POST', `${ws(w)}/channels/${encodeURIComponent(id)}/history-import`, body),
    importOwnedPosts: (w: string, id: string, receipt: string, postIds: string[], expectedRevision: number) =>
      send<Snapshot>('POST', `${ws(w)}/channels/${encodeURIComponent(id)}/posts/import`, { receipt, postIds, expectedRevision, confirmedAuthorship: true }),
    importOwnedPostSelection: (w: string, id: string, selections: { receipt: string; postIds: string[] }[], labels: Record<string, string>, expectedRevision: number) =>
      send<Snapshot>('POST', `${ws(w)}/channels/${encodeURIComponent(id)}/posts/import`, { selections, labels, expectedRevision, confirmedAuthorship: true }),
    verifyChannel: (w: string, id: string) =>
      send<{ connectionId: string; state: string; identityVerified: boolean; detail?: string }>(
        'POST',
        `${ws(w)}/channels/${encodeURIComponent(id)}/verify`
      ),
    insightsCanary: (w: string, id: string) =>
      send<{ state: string; http?: number; providerRead?: boolean; found?: Record<string, number> }>(
        'POST',
        `${ws(w)}/channels/${encodeURIComponent(id)}/insights-canary`,
        { confirmed: true }
      ),
    disconnectChannel: (w: string, id: string) =>
      send<{ disconnected: boolean; remoteRevoked: boolean; revision: number }>(
        'DELETE',
        `${ws(w)}/channels/${encodeURIComponent(id)}`
      ),

    creditPacks: (w: string) => get<{ available: boolean; packs: { id: string; label: string; amountCents: number; currency: string; milliCredits: number }[] }>(`${ws(w)}/billing/credit-packs`),
    creditCheckout: (w: string, packId: string, requestId: string) => send<{ orderId: string; url: string }>('POST', `${ws(w)}/billing/credit-checkout`, { packId, requestId }),

    /* ideas */
    conversations: (w: string) => get<{ conversations: Conversation[] }>(`${ws(w)}/ideas/conversations`),
    navigationConversations: (w: string, cursor?: string | null) =>
      get<{ conversations: NavigationConversation[]; nextCursor: string | null }>(`${ws(w)}/ideas/conversations/navigation${cursor ? `?cursor=${encodeURIComponent(cursor)}` : ''}`),
    searchNavigation: (w: string, query: string) =>
      get<{ results: NavigationSearchResult[] }>(`${ws(w)}/ideas/conversations/search?q=${encodeURIComponent(query)}`),
    navigation: (w: string, id: string, cursor = 0) =>
      get<{ items: NavigationItem[]; nextCursor: number | null; totalMessages: number }>(`${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/navigation?cursor=${cursor}`),
    messageWindow: (w: string, id: string, options: { anchor?: string | null; before?: number } = {}) => {
      const query = options.anchor ? `?anchor=${encodeURIComponent(options.anchor)}` : options.before ? `?before=${options.before}` : '';
      return get<MessageWindow>(`${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/window${query}`);
    },
    saveMoment: (w: string, id: string, body: { assetId: string; title: string; seconds: number }) =>
      send<MediaMoment>('POST', `${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/moments`, body),
    createConversation: (w: string, title: string) =>
      send<Conversation>('POST', `${ws(w)}/ideas/conversations`, { title }),
    onboarding: (w: string, id: string, expectedSeq: number, answer?: string) =>
      send<Message>('POST', `${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/onboarding`, { expectedSeq, ...(answer === undefined ? {} : { answer }) }),
    messages: (w: string, id: string) =>
      get<Conversation & { messages: Message[] }>(`${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/messages`),
    turn: (w: string, id: string, body: Record<string, unknown>) =>
      send<Run>('POST', `${ws(w)}/ideas/conversations/${encodeURIComponent(id)}/turns`, body, DRAFT_TIMEOUT_MS),
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
    creditEstimate: (w: string, body: Record<string, unknown> | MediaNotesCreditBody) =>
      send<CreditEstimate>('POST', `${ws(w)}/ideas/credit-estimates`, body),
    creditQuote: (w: string, body: Record<string, unknown> | MediaNotesCreditBody) =>
      send<{ quoteId: string; maxMilliCredits: number; expiresAt: number; kind: "spending_limit" }>("POST", `${ws(w)}/ideas/credit-quotes`, body),
    quickStart: (w: string, expectedRevision: number, body: Record<string, unknown>) =>
      send<Run & { sourceId: string | null; sourcePolicy: string | null; revision: number }>('POST', `${ws(w)}/ideas/quick-start`, {
        expectedRevision,
        ...body
      }, DRAFT_TIMEOUT_MS),

    /* Universal Library: normalized documents/files use the same signed private-storage boundary as video. */
    library: (w: string, query = '', limit = 100, offset = 0, filters: { kind: string; tag: string; collection: string; sort: string } = { kind: 'all', tag: '', collection: '', sort: 'newest' }) =>
      get<{ assets: Asset[]; query: string; nextOffset: number | null; storage: { usedBytes: number; limitBytes: number } }>(`${ws(w)}/library?${new URLSearchParams({ q: query, limit: String(limit), offset: String(offset), ...filters })}`),
    beginLibraryFile: (w: string, body: { filename: string; mime: string; bytes: number }) =>
      send<{ upload: { assetId: string; url: string; mime: string; bytes: number; filename: string; expiresIn: number } }>('POST', `${ws(w)}/library/files`, body),
    commitLibraryFile: (w: string, assetId: string) =>
      send<{ asset: Asset; status: string }>('POST', `${ws(w)}/library/files/${encodeURIComponent(assetId)}/commit`, {}),
    libraryFile: (w: string, assetId: string) =>
      get<{ asset: Asset; extractedText: string; chunks: { ordinal: number; text: string }[] }>(`${ws(w)}/library/files/${encodeURIComponent(assetId)}`),
    libraryViewerPage: (w: string, assetId: string, page = 1) =>
      get<{ pageCount: number; page: number; url: string; width: number; height: number; text: string }>(`${ws(w)}/library/files/${encodeURIComponent(assetId)}/viewer?page=${encodeURIComponent(String(page))}`, true, 90_000),
    libraryPreviewUrl: (w: string, assetId: string) =>
      get<{ url: string; mime: string; page: number }>(`${ws(w)}/library/files/${encodeURIComponent(assetId)}/preview`, true, 90_000),
    libraryFileUrl: (w: string, assetId: string, download = false) =>
      get<{ url: string; mime: string; filename: string }>(`${ws(w)}/library/files/${encodeURIComponent(assetId)}/url${download ? "?download=1" : ""}`),
    renameLibraryFile: (w: string, assetId: string, title: string) =>
      send<{ asset: Asset }>('PATCH', `${ws(w)}/library/files/${encodeURIComponent(assetId)}`, { title }),
    deleteLibraryFile: (w: string, assetId: string) =>
      send<{ assetId: string; status: string }>('DELETE', `${ws(w)}/library/files/${encodeURIComponent(assetId)}`),

    previewLibraryMetadata: (w: string, changes: LibraryMetadataSelection[]) => send<LibraryMetadataReceipt>('POST', `${ws(w)}/library/metadata/preview`, { changes }),
    libraryMetadataHistory: (w: string) => get<LibraryMetadataHistory>(`${ws(w)}/library/metadata/changes`),
    libraryMetadataReceipt: (w: string, id: string) => get<LibraryMetadataReceipt>(`${ws(w)}/library/metadata/changes/${encodeURIComponent(id)}`),
    applyLibraryMetadata: (w: string, receiptId: string) => send<LibraryMetadataReceipt>('POST', `${ws(w)}/library/metadata/apply`, { receiptId }),
    undoLibraryMetadata: (w: string, receiptId: string) => send<LibraryMetadataReceipt>('POST', `${ws(w)}/library/metadata/undo`, { receiptId }),
    libraryCollections: (w: string) => get<{ collections: { id: string; name: string; count: number }[] }>(`${ws(w)}/library/collections`),
    createLibraryCollection: (w: string, name: string) => send('POST', `${ws(w)}/library/collections`, { name }),
    deleteLibraryCollection: (w: string, id: string) => send('DELETE', `${ws(w)}/library/collections/${encodeURIComponent(id)}`),
    updateLibraryAsset: (w: string, id: string, body: { title?: string; tags?: string[]; collections?: string[] }) => send('PATCH', `${ws(w)}/library/assets/${encodeURIComponent(id)}`, body),
    retryLibraryFile: (w: string, id: string) => send('POST', `${ws(w)}/library/files/${encodeURIComponent(id)}/retry`, {}),
    libraryTranscript: (w: string, id: string, text: string) => send('POST', `${ws(w)}/library/files/${encodeURIComponent(id)}/transcript`, { text }),
    librarySource: (w: string, id: string, expectedRevision: number) => send<{ sourceId: string; revision?: number; clipped: boolean; status: string }>('POST', `${ws(w)}/library/files/${encodeURIComponent(id)}/source`, { expectedRevision }),

    /* chat attachments (chat-context SPEC §5.6–5.9); the video bytes go to storage via `upload.ts`, never here */
    mediaNotes: (w: string, body: MediaNotesBody) => send<MediaNotesResult>('POST', `${ws(w)}/ideas/media-notes`, body),
    beginVideoUpload: (w: string, body: VideoUploadBegin) => send<VideoUploadTicket>('POST', `${ws(w)}/media/videos`, body),
    resumeVideoUpload: (w: string, assetId: string, body: { mime: 'video/mp4' | 'video/quicktime'; bytes: number }) =>
      send<VideoResumeTicket>('POST', `${ws(w)}/media/videos/${encodeURIComponent(assetId)}/resume`, body),
    commitVideoUpload: (w: string, assetId: string, body: VideoCommitBody) =>
      send<VideoCommitResult & Partial<Snapshot>>('POST', `${ws(w)}/media/videos/${encodeURIComponent(assetId)}/commit`, body),
    abortVideoUpload: (w: string, assetId: string) =>
      send<{ assetId: string; status: 'aborted' }>('DELETE', `${ws(w)}/media/videos/${encodeURIComponent(assetId)}`),
    /** A short-lived signed playback URL for a video (videos only). */
    mediaUrl: (w: string, assetId: string) =>
      get<{ url: string; expiresAt: number; mime: string }>(`${ws(w)}/media/${encodeURIComponent(assetId)}/url`),
    siteAgentSearch: (w: string, q: string, categories: readonly PickerCategory[] = [], limit = 8) =>
      get<PickerSearchResult>(
        `${ws(w)}/site-agent/search?${new URLSearchParams({ q, ...(categories.length ? { categories: categories.join(',') } : {}), limit: String(limit) })}`
      ),
    skillPreview: (w: string, skillId: string) =>
      get<SkillPreview>(`${ws(w)}/skills/${encodeURIComponent(skillId)}`),
    connectorCatalog: (w: string) => get<ProductivityConnectorCatalog>(`${ws(w)}/connectors`),
    connectorOauthStart: (w: string, provider: string) =>
      send<{ transactionId: string; provider: string; authorizeUrl: string; scopes: string[]; expiresAt: number }>(
        'POST',
        `${ws(w)}/connectors/${encodeURIComponent(provider)}/oauth/start`
      ),
    connectorOauthComplete: (
      w: string,
      provider: string,
      state: string,
      code?: string,
      error?: string
    ) =>
      send<{
        connected: boolean;
        connectionId?: string;
        provider?: string;
        account?: string;
        scopes?: string[];
        expiresAt?: number | null;
        reason?: string;
      }>('POST', `${ws(w)}/connectors/${encodeURIComponent(provider)}/oauth/complete`, {
        state,
        code,
        error
      }),
    connectorSearch: (w: string, connectionId: string, query: string, limit = 12) =>
      send<ProductivityConnectorSearchResult>(
        'POST',
        `${ws(w)}/connectors/${encodeURIComponent(connectionId)}/search`,
        { query, limit }
      ),
    connectorRefresh: (w: string, connectionId: string) =>
      send<{ connectionId: string; provider: string; refreshed: boolean; expiresAt: number | null }>(
        'POST',
        `${ws(w)}/connectors/${encodeURIComponent(connectionId)}/refresh`
      ),
    connectorDisconnect: (w: string, connectionId: string) =>
      send<{
        connectionId: string;
        provider: string;
        disconnected: boolean;
        providerRevocationPending: boolean;
      }>('DELETE', `${ws(w)}/connectors/${encodeURIComponent(connectionId)}`),

    /* Rafii side panel (site agent) */
    siteAgentTurn: (w: string, body: Record<string, unknown>) => send<SiteAgentTurnResult>('POST', `${ws(w)}/site-agent/turns`, body),
    siteAgentCompose: (w: string, runId: string) => send<SiteAgentTurnResult>('POST', `${ws(w)}/site-agent/runs/${encodeURIComponent(runId)}/compose`),
    siteAgentCancel: (w: string, runId: string) =>
      send<{ runId: string; status: string; note?: string }>('POST', `${ws(w)}/site-agent/runs/${encodeURIComponent(runId)}/cancel`),
    siteAgentEvents: (w: string, runId: string, cursor = 0) =>
      get<SiteAgentTurnResult>(`${ws(w)}/site-agent/runs/${encodeURIComponent(runId)}/events?cursor=${cursor}`),
    siteAgentCompoundContinue: (w: string, body: { conversationId: string; messageId: string; timeZone?: string }) =>
      send<{ message: SiteAgentMessageBody; status: 'advanced' | 'unchanged' }>('POST', `${ws(w)}/site-agent/compound/continue`, body),
    siteAgentApplyProposal: (w: string, body: Record<string, unknown>) =>
      send<{ proposal: SiteAgentProposalView; revision: number }>('POST', `${ws(w)}/site-agent/proposals/apply`, body),
    siteAgentDismissProposal: (w: string, body: Record<string, unknown>) =>
      send<{ proposal: SiteAgentProposalView }>('POST', `${ws(w)}/site-agent/proposals/dismiss`, body),
    siteAgentFeedback: (w: string, body: { messageId: string; value: 'helpful' | 'not_helpful'; reason?: string | null }) =>
      send<{ messageId: string; feedback: NonNullable<SiteAgentBody['feedback']> }>('POST', `${ws(w)}/site-agent/feedback`, body),
    siteAgentInsights: (w: string) => get<SiteAgentInsights>(`${ws(w)}/site-agent/insights`),
    helpCatalogue: (w: string) => get<{ snapshot: string; productVersion: string; documents: HelpDocumentSummary[] }>(`${ws(w)}/site-agent/help`),
    helpDocument: (w: string, documentId: string) => get<HelpDocument>(`${ws(w)}/site-agent/help/${encodeURIComponent(documentId)}`),

    /* time back: the person's own estimate, kept apart from platform analytics */
    timeSavings: (w: string, range: TimeSavingsRange = '30d') => get<TimeSavingsSummary>(`${ws(w)}/time-savings?range=${encodeURIComponent(range)}`),
    /** `keepalive` lets the last beat leave while the page is being hidden or closed. */
    recordActiveTime: async (w: string, beat: ActiveTimeBeat, options: { keepalive?: boolean } = {}) =>
      parse<{ accepted: boolean; activeSeconds: number; sequence: number }>(
        await fetch(`${ws(w)}/time-savings/activity`, { method: 'POST', headers: await headers(), body: JSON.stringify(beat), keepalive: options.keepalive === true })
      ),
    calibrateTimeSavings: (w: string, input: TimeSavingsCalibrationInput) =>
      send<{ taskKind: TimeSavingsTaskKind; calibration: TimeSavingsSummary['calibration'] }>('POST', `${ws(w)}/time-savings/calibrations`, input),

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
    phoneSettings: (w: string) => get<PhoneSettingsData>(`${ws(w)}/phone`),
    phoneAuthStatus: (id: string) => get<PhoneAuthChallenge>(`/api/phone/verify-call/${encodeURIComponent(id)}`),
    phoneAuthApprove: (id: string, passkeyToken: string, useAvailableCredits: boolean) => send<{ state: string }>('POST', `/api/phone/verify-call/${encodeURIComponent(id)}/approve`, { passkeyToken, useAvailableCredits }),
    phoneAuthDismiss: (id: string, action: 'deny' | 'fallback' | 'cancel') => send<{ state: string }>('POST', `/api/phone/verify-call/${encodeURIComponent(id)}/${action}`),
    phoneTrustedCallers: (w: string) => get<{ callers: TrustedCaller[] }>(`${ws(w)}/phone/trusted-callers`),
    phoneRevokeCaller: (w: string, id: string, passkeyToken: string) => send<{ revoked: boolean }>('POST', `${ws(w)}/phone/trusted-callers/${encodeURIComponent(id)}/revoke`, { passkeyToken }),

    phoneInboundCode: (w: string, body: { conversationId?: string | null; maxMilliCredits?: number; useAvailableCredits?: boolean }) => send<PhoneInboundCode>('POST', `${ws(w)}/phone/inbound-codes`, body),
    phoneInboundStatus: (w: string, id: string) => get<PhoneInboundStatus>(`${ws(w)}/phone/inbound-codes/${encodeURIComponent(id)}`),
    phoneInboundRevoke: (w: string, id: string) => send<{ revoked: boolean }>('DELETE', `${ws(w)}/phone/inbound-codes/${encodeURIComponent(id)}`),
    phoneProviderReadiness: (w: string) => get<PhoneProviderReadiness>(`${ws(w)}/phone/provider-readiness`),
    phonePreferences: (w: string, patch: Partial<PhonePreferences>) => send<{ preferences: PhonePreferences }>('PATCH', `${ws(w)}/phone/preferences`, patch),
    phoneVerify: (w: string, number: string) => send<{ sent: boolean }>('POST', `${ws(w)}/phone/verification`, { number }),
    phoneConfirm: (w: string, code: string) => send<{ verified: boolean }>('POST', `${ws(w)}/phone/verification/confirm`, { code }),
    phoneDelete: (w: string) => send<{ deleted: boolean }>('DELETE', `${ws(w)}/phone/number`),
    phoneCall: (w: string, body: { idempotencyKey: string; conversationId?: string | null; maxMilliCredits?: number; useAvailableCredits?: boolean; callDurationLimitSeconds?: number }) => send<PhoneCall>('POST', `${ws(w)}/phone/calls`, body),
    phoneEnd: (w: string, id: string) => send<{ ended: boolean; state?: string }>('POST', `${ws(w)}/phone/calls/${encodeURIComponent(id)}/end`),
    phoneSchedule: (w: string, schedule: { weekdays: string[]; localTime: string; timeZone: string }) => send<{ id: string }>('POST', `${ws(w)}/phone/schedules`, { schedule }),
    phoneDeleteSchedule: (w: string, id: string) => send<{ deleted: boolean }>('DELETE', `${ws(w)}/phone/schedules/${encodeURIComponent(id)}`),
    supportTickets: (w: string) => get<{ tickets: { id: string; category: string; status: string; revision: number }[] }>(`${ws(w)}/support/tickets`),
    supportTicket: (w: string, id: string) => get<{ messages: { role: string; body: string; createdAt: string }[] }>(`${ws(w)}/support/tickets/${encodeURIComponent(id)}`),
    supportMessage: (w: string, body: { requestId: string; message: string; category?: string }, id?: string) => send('POST', `${ws(w)}/support/tickets${id ? '/' + encodeURIComponent(id) : ''}`, body),
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
