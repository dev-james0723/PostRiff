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
