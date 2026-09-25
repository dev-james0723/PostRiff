/**
 * Contract with `/api/workspaces/{id}/agent/*` (Rafii Agent Runtime, docs/design/site-agent/agent-runtime/ARCHITECTURE_LOCK.md).
 * The turn result is surface-neutral: the panel renders `blocks` (site-agent block types), Voice Mode speaks
 * `speakableSummary`, and everything that happened is structured (no client parses prose to learn it).
 */
import type { SiteAgentBlock, SiteAgentPageContext } from '@/lib/site-agent/types';

export type Modality = 'text' | 'voice' | 'image';
export type StepState = 'planned' | 'running' | 'done' | 'needs_user' | 'blocked' | 'failed' | 'canceled';

export interface AgentStep {
  id: string;
  label: string;
  state: StepState;
  kind?: string | null;
  reason?: string | null;
  verified: boolean;
  approvals: string[];
  outputs: { type: string; id: string }[];
}

export interface AgentTask {
  taskId: string;
  title: string;
  status: 'running' | 'completed' | 'cancelled';
  steps: AgentStep[];
  counts?: Partial<Record<StepState, number>>;
}

export interface PendingApproval {
  proposalId: string;
  messageId: string;
  type: string;
  summary: string[];
  digest: string;
  expiresAt?: number;
  requiredPermission?: string;
}

export interface GeneratedAsset {
  assetId: string;
  kind: 'generated' | 'edit' | 'variant' | string;
  model: string;
  parentAssetId?: string | null;
  width?: number;
  height?: number;
  href: string;
  alt: string;
  verified: boolean;
  originalPreserved?: boolean | null;
}

export interface AgentResult {
  version: number;
  traceId: string;
  modality: Modality;
  answerText: string;
  speakableSummary: string;
  references: { type: string; id: string; title?: string | null }[];
  toolActivity: { tool: string; label: string; effect: string; status: string; latencyMs: number; specialist?: string; code?: string }[];
  task: AgentTask | null;
  changedEntities: { type: string; id: string; change: string; verified: boolean }[];
  pendingApprovals: PendingApproval[];
  generatedAssets: GeneratedAsset[];
  warnings: { code: string; message: string }[];
  errors: { code: string; message: string; step?: string }[];
  blocks: SiteAgentBlock[];
  composedBy: 'manager' | 'deterministic' | 'site_agent' | 'grounded';
  language?: string | null;
}

export interface AgentTurnResponse {
  conversationId: string;
  runId: string | null;
  messageId: string | null;
  status: string;
  result: AgentResult | null;
  fallback?: string | null;
  delegated?: boolean;
  traceId?: string;
}

export interface AgentTurnRequest {
  message: string;
  idempotencyKey: string;
  conversationId?: string | null;
  modality: Modality;
  pageContext?: SiteAgentPageContext;
  attachments?: { assetId: string }[];
  timeZone?: string;
  locale?: string;
  model?: string;
  traceId?: string;
  delegationId?: string;
  voiceSessionId?: string;
  supersede?: boolean;
}

export interface AgentStatus {
  runtime: string;
  flags: Record<string, boolean>;
  models: Record<string, string>;
  provider: string | null;
  voiceAvailable: boolean;
  imageAvailable: boolean;
  canUseModel: boolean;
  voice: { available: boolean; blocker: string | null };
  manager: { available: boolean; blocker: string | null };
}

export interface ConversationImage {
  index: number;
  assetId: string;
  origin: string;
  alt?: string | null;
  width?: number;
  height?: number;
}

export interface ConversationState {
  task: AgentTask | null;
  images: ConversationImage[];
  pendingApprovals: Omit<PendingApproval, 'requiredPermission'>[];
}

export interface VoiceSessionStart {
  voiceSessionId: string;
  liveSessionId: string;
  conversationId: string;
  sdp: string;
  dataChannel: string;
  model: string;
  locale: string;
  capMinutes: number;
  allowedClientEvents: string[];
}

export interface DecideResponse {
  outcome: string;
  verified: boolean;
  speakableSummary: string;
  checks: { what: string; expected: unknown; actual: unknown; verified: boolean }[];
}
