/** The Rafii side panel's contract with `/api/workspaces/{id}/site-agent/*` (site agent spec §6.1, §11.3, §13). */
import type { ChatAutomation, SafeEvent } from '@/lib/api/types';

export interface SiteAgentPageContext {
  route: string;
  selectedEntity?: { type: string; id: string } | null;
  visibleState?: Record<string, string | number | boolean | string[]>;
  uiCapabilities?: string[];
  clientBuild?: string;
}

export interface SiteAgentCitation {
  id: string;
  ref?: string;
  documentId: string;
  title: string;
  section: string;
  href: string;
  retrievedAt: string;
  authority: string;
}

export interface SiteAgentProposalView {
  id: string;
  type: 'automation_change' | 'schedule_draft' | 'reschedule_post';
  status: 'proposed' | 'applied' | 'dismissed' | 'expired' | 'superseded' | 'failed';
  taskId: string;
  name: string;
  changes: Record<string, unknown>[];
  summary: string[];
  preview: {
    before: SiteAgentPlanView;
    after: SiteAgentPlanView;
  };
  requiredPermission: 'edit' | 'owner' | 'approve';
  expiresAt: number;
  digest: string;
  variantId?: string;
  channelId?: string;
  localTime?: string;
  timeZone?: string;
  jobId?: string | null;
  result?: { taskId?: string; status?: string; version?: number; summary?: string[]; needs?: string[]; reviewId?: string | null; localTime?: string; timeZone?: string; cancelledJobId?: string | null } | null;
  appliedAt?: number;
  closedReason?: string;
}

export interface SiteAgentPlanView {
  status?: string;
  scheduleText?: string;
  policy?: string | null;
  plan: { step?: string; when?: string; text?: string }[];
  platforms: { platform?: string; canPublish?: boolean }[];
  needs: string[];
  nextPublish?: string | null;
}

export type SiteAgentBlock =
  | { type: 'text'; text: string }
  | { type: 'citation_list'; citations: SiteAgentCitation[] }
  | { type: 'navigation_card'; label: string; href: string; routeId: string; reason?: string | null; auto?: boolean }
  | {
      type: 'diagnostic_card';
      title: string;
      status: string;
      evidence: string[];
      cause?: string | null;
      steps: string[];
      verified: boolean;
      links: { label: string; href: string }[];
    }
  | { type: 'proposal_diff'; proposal: SiteAgentProposalView }
  | { type: 'question_form'; prompt: string; options: string[] }
  | { type: 'warning'; message: string; code: string }
  | { type: 'handoff_card'; traceId: string; summary: string[]; href: string }
  | { type: 'error'; message: string; code: string }
  | { type: 'result_list'; title: string; items: { kind: string; title: string; excerpt?: string | null; meta?: string | null; href?: string | null }[]; empty?: string | null };

export interface SiteAgentContextSummary {
  route?: string | null;
  entity?: { type: string; id: string } | null;
  read: string[];
  withheld: string[];
  stale?: boolean;
}

export interface SiteAgentBody {
  version: number;
  runId: string;
  status: 'running' | 'completed' | 'cancelled';
  intent: string;
  language?: string;
  blocks: SiteAgentBlock[];
  citations?: SiteAgentCitation[];
  grounding?: { required: boolean; sufficient: boolean; missing: string[] };
  proposals?: SiteAgentProposalView[];
  context?: SiteAgentContextSummary;
  model?: { id: string | null; composedBy: 'model' | 'grounded' };
  followUps?: string[];
  feedback?: { value: 'helpful' | 'not_helpful'; reason?: string | null; at: string } | null;
  refs?: { type: string; id: string; title?: string }[];
  /** Rafii's own question: a reply that picks an option ("the second one") runs `request` on that item. */
  pending?: { request: string; candidates: { type: string; id: string; title?: string }[] } | null;
  role?: 'question';
  page?: { routeId?: string | null; title?: string | null; entity?: { type: string; id: string } | null };
}

export interface SiteAgentMessageBody {
  text?: string;
  pending?: boolean;
  cancelled?: boolean;
  runId?: string;
  siteAgent?: SiteAgentBody;
  automation?: ChatAutomation;
  memoryProposal?: { statement?: string } & Record<string, unknown>;
  intent?: string;
  failed?: boolean;
}

export interface SiteAgentTurnResult {
  conversationId: string;
  runId: string | null;
  status: string;
  needsCompose?: boolean;
  events?: SafeEvent[];
  cursor?: number;
  messageId?: string | null;
  message?: SiteAgentMessageBody | null;
  delegated?: boolean;
  kind?: 'draft' | 'automation' | 'schedule' | 'memory' | 'answer';
  result?: Record<string, unknown>;
}

export interface HelpDocumentSummary {
  documentId: string;
  title: string;
  summary?: string | null;
  sourceType: string;
  routeFamilies: string[];
}

export interface HelpDocument extends HelpDocumentSummary {
  owner: string;
  productVersion: string;
  effectiveFrom: string;
  snapshot: string;
  sha256: string;
  sections: { heading: string; anchor: string; text: string }[];
}

export interface SiteAgentInsights {
  days: number;
  turns: number;
  byIntent: Record<string, number>;
  outcomes: Record<string, number>;
  composedBy: Record<string, number>;
  fallbacks: Record<string, number>;
  blockedTools: number;
  unanswered: number;
  feedback: Record<string, number>;
  since: string;
}
