import type { DiscordDestination } from '@/lib/api/types';

export type DiscordEngagementPermissions = { analytics: boolean; inbox: boolean; reply: boolean };
export interface DiscordEngagementJob {
  id: string;
  state: string;
  approvedAt: number;
  parentMessageId: string;
  text: string;
  timing: { timestamp: number; timeZone: string };
  cancelRequested: boolean;
  approvalDigest: string;
  previewDispatchPending: boolean;
  url?: string;
}
export interface DiscordEngagementStatus {
  implemented: boolean;
  enabled: boolean;
  canReply: boolean;
  destinations: { target: DiscordDestination; targetDigest: string; contentAccess: 'mentions_only' | 'approved_content'; broaderContentEligible: boolean; permissions: DiscordEngagementPermissions; expiresAt: number | null }[];
  jobs: DiscordEngagementJob[];
  limits: { inbox: string; analytics: string; retention: string; broaderAccess: string; unavailable: string[] };
}
export interface DiscordEngagementMessage {
  id: string;
  parentMessageId: string | null;
  content: string | null;
  contentAvailability: 'visible_bot_mention' | 'visible_approved_content' | 'restricted';
  author: string | null;
  replyable: boolean;
  url: string;
}
interface DiscordMetric {
  value: number | null;
  availability: 'available' | 'unavailable';
  source: string;
  definition: string;
  lowerBound: boolean;
}
export interface DiscordEngagementRead {
  kind: 'analytics' | 'inbox';
  contentAccess: 'mentions_only' | 'approved_content';
  target: DiscordDestination;
  observedAt: number;
  coverage: 'latest_page_only';
  pageLimit: number;
  mayHaveOlderMessages: boolean;
  messages?: DiscordEngagementMessage[];
  server?: { approximateMembers: DiscordMetric; approximateOnline: DiscordMetric };
  managedMessages?: { messageId: string; jobId: string; reactions: DiscordMetric; repliesObserved: DiscordMetric }[];
  unavailableMetrics?: string[];
}
export interface DiscordReplyReview {
  reviewId: string;
  digest: string;
  expiresAt: number;
  parent: DiscordEngagementMessage;
  manifest: {
    actor: string;
    channelId: string;
    destinationId: string;
    payload: { text: string };
    timing: { timestamp: number; timeZone: string };
    discord: { target: DiscordDestination };
    engagementReply: { parentMessageId: string };
  };
}
export interface DiscordReplyApproval {
  jobId: string;
  state: string;
  approvalDigest: string;
  duplicate?: boolean;
}
