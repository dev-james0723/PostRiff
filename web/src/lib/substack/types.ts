import type { Membership } from '@/lib/api/types';

export type SubstackCapabilityStatus =
  | 'available'
  | 'unsupported'
  | 'requires_official_approval'
  | 'requires_account_eligibility'
  | 'permission_missing'
  | 'temporarily_unavailable';

export interface SubstackCapability {
  status: SubstackCapabilityStatus;
  reason: string;
  evidence: string[];
}

export type SubstackCapabilities = Record<string, SubstackCapability>;
export type SubstackConnectionMode = 'public_feed' | 'official_mcp_analytics' | 'official_authorized' | 'official_partnership';
export type SubstackContentType = 'article' | 'note' | 'podcast' | 'video';
export type SubstackAudience = 'free' | 'paid' | 'everyone';

export interface SubstackConnection {
  id: string;
  mode: SubstackConnectionMode;
  publicationUrl: string;
  feedUrl: string;
  status: 'feed_added' | 'connected' | 'disconnected' | 'revoked' | 'permission_missing';
  ownershipVerified: boolean;
  accountAuthenticated: boolean;
  analyticsConnected: boolean;
  publishingAuthorized: boolean;
  createdAt: number | string;
}

export interface SubstackDraft {
  id: string;
  connectionId: string;
  title: string;
  body: string;
  format: 'markdown';
  contentType?: SubstackContentType;
  audience?: SubstackAudience;
  status: 'draft' | 'approved' | 'handoff_ready' | 'canceled';
  contentHash: string;
  approvedHash: string | null;
  scheduledFor: string | null;
  createdAt: number | string;
  updatedAt: number | string;
}

export interface SubstackWorkspace {
  revision: number;
  connections: SubstackConnection[];
  drafts: SubstackDraft[];
  capabilities: SubstackCapabilities;
  enabled: boolean;
  membership: Membership;
}

export interface SubstackDraftInput {
  expectedRevision: number;
  connectionId: string;
  title: string;
  body: string;
  scheduledFor?: string | null;
  contentType?: SubstackContentType;
  audience?: SubstackAudience;
}

export interface SubstackHandoff {
  status: 'manual_action_required';
  publicationUrl: string;
  title: string;
  body: string;
  format: 'markdown';
  contentType?: SubstackContentType;
  audience?: SubstackAudience;
  contentHash: string;
  autoPublished: false;
  scheduledFor: string | null;
}

export interface SubstackFeedItem {
  id?: string;
  title: string;
  url?: string;
  link?: string;
  publishedAt?: string | null;
  summary?: string;
}

export type SubstackHandoffResult = SubstackWorkspace & { handoff: SubstackHandoff };
export type SubstackFeedResult = SubstackWorkspace & {
  feed: { connectionId?: string; items: SubstackFeedItem[]; fetchedAt?: string | number };
};
