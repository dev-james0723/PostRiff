export interface YouTubeCapability {
  label: string;
  state:
    | 'READY'
    | 'IMPLEMENTED / E2E NOT PROVEN'
    | 'BLOCKED — GOOGLE APPROVAL'
    | 'BLOCKED — ACCOUNT ELIGIBILITY'
    | 'NOT AUTHORIZED'
    | 'UNSUPPORTED BY OFFICIAL API';
  canExecute: boolean;
  reason: string;
}
export interface YouTubeResource {
  id: string;
  snippet?: {
    title?: string;
    thumbnails?: Partial<
      Record<'default' | 'medium' | 'high' | 'standard' | 'maxres', {
        url?: string;
        width?: number;
        height?: number;
      }>
    >;
    description?: string;
    videoId?: string;
    liveChatId?: string;
    language?: string;
    name?: string;
    textDisplay?: string;
    textOriginal?: string;
    displayMessage?: string;
    type?: string;
    parentId?: string;
    authorDisplayName?: string;
    scheduledStartTime?: string;
    scheduledEndTime?: string;
    categoryId?: string;
    topLevelComment?: YouTubeResource;
    resourceId?: { videoId: string };
  };
  status?: {
    privacyStatus?: string;
    podcastStatus?: string;
    lifeCycleStatus?: string;
    publishAt?: string;
  };
  contentDetails?: { boundStreamId?: string };
  replies?: { comments: YouTubeResource[] };
}
export interface YouTubeOverview {
  channelId: string;
  identity: YouTubeResource & {
    statistics?: Record<string, string>;
    status?: Record<string, unknown>;
  };
  capabilities: Record<string, YouTubeCapability>;
  actualScopes: string[];
  counterProvenance: string;
  operationalAlerts: { category: string; method: string; observedAt: number; retryAt?: number }[];
  sensitiveAuthorizations: { monetary: boolean; memberships: boolean };
  project: Record<string, unknown>;
  quota: {
    remainingState: string;
    resetTimeZone: string;
    note: string;
    workspaceUsageToday: { method: string; attempts: number; estimatedUnits: number | null }[];
    admission?: {
      configuredProjectCeilings: Record<string, number>;
      workspaceCeilings: Record<string, number>;
      workspaceUsageToday: Record<string, { reservedUnits: number; admittedRequests: number; delayedRequests: number }>;
      approvedQuotaEvidence: boolean;
      pendingQueueLimit: number;
      requestsPerMinute: number;
      resetAt: number;
      resetTimeZone: string;
      actualGoogleRemaining: null;
    };
  };
  uploads: {
    operationKey: string;
    stage: string;
    bytesSent: number;
    totalBytes: number;
    videoId?: string;
    errorCategory?: string;
    publishAt?: string;
  }[];
  readiness: {
    implementation: string;
    googleApproval: string;
    realE2E: string;
    production: string;
  };
}
export interface YouTubeData {
  source: string;
  items?: YouTubeResource[];
  nextPageToken?: string;
  nextReadAt?: number;
  limitation?: string;
  coverage?: { complete?: boolean; rowBudget?: number };
  data?: { columnHeaders?: { name: string }[]; rows?: (string | number)[][] };
  reports?: { id: string; startTime: string; endTime: string; createTime: string }[];
  reportTypes?: { id: string; name: string }[];
  jobs?: { id: string; name: string; reportTypeId: string }[];
  [key: string]: unknown;
}
export interface YouTubeActionReview {
  id: string;
  digest: string;
  executed: false;
  confirmationTarget: string;
  manifest: {
    action: string;
    channelId: string;
    inputs: Record<string, unknown>;
    destructive: boolean;
    approvalExpiresAt: number;
  };
}
export interface YouTubeActionReceipt {
  id: string;
  status: string;
  action?: string;
  receipt?: {
    action?: string;
    message?: string;
    result?: YouTubeResource;
    verification?: { verified: boolean; note?: string };
  };
}

export interface YouTubeAgentDraft {
  id: string;
  digest: string;
  connectionId: string;
  channelId: string;
  assetId: string;
  variantId: string;
  status: 'proposed' | 'queued';
  uploadWorkflow: 'upload_now' | 'upload_later';
  uploadAt: number;
  timing: { local: string; timeZone: string; fold: number; timestamp: number };
  publishOptions: { title: string; description: string; privacyStatus: string; mode?: string };
  recommendations: string[];
  jobId?: string;
  approvalMode?: 'manual_approval' | 'authorized_autopilot';
}

export interface YouTubeAgentPolicy {
  id: string;
  digest: string;
  channelId: string;
  status: 'prepared' | 'active' | 'paused' | 'revoked';
  drafts: { id: string; digest: string }[];
  assetIds: string[];
  timeZone: string;
  startsAt: number;
  endsAt: number;
  maxDaily: number;
  intervention?: { code: string; message: string; at: number };
}

export interface YouTubeAgentOverview {
  channelId: string;
  drafts: YouTubeAgentDraft[];
  policies: YouTubeAgentPolicy[];
  planningMode: string;
  executionState: string;
  autopilotGate: { canActivate: boolean; reason: string };
  pauseNotice: string;
}

export interface YouTubeAgentMutation<T> {
  revision: number;
  result: T;
  queued: boolean;
  executed: false;
  providerVerified: false;
}
