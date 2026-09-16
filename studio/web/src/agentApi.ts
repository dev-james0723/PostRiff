import {api} from './api.ts';
import type {Draft, DraftInput} from './types.ts';

export type AgentStatus = {
  available: boolean;
  transport: 'codex_cli';
  authentication: 'ready'|'login_required'|'unavailable';
  version: string;
  reason: string;
  limits: {timeoutSeconds: number; maxOutputBytes: number};
  publishing: false;
};
export type ContentType = 'article'|'reflection'|'news'|'launch'|'youtube';
export type QuestionSlot = 'source'|'angle'|'objective';
export type SkillBinding = {name: string; sha256: string};
export type Conversation = {
  id: string; revision: number; draftId: string; draftRevision: number;
  contentType: ContentType; state: 'awaiting_answer'|'ready';
  question: null|{slot: QuestionSlot; prompt: string};
  snapshot: DraftInput; objective: string; createdAt: string; updatedAt: string;
};
export type Candidate = {
  canonicalBrief: string;
  variants: {channelId: string; copy: string; notes: string}[];
  warnings: string[];
};
export type Run = {
  id: string; conversationId: string; draftId: string; draftRevision: number;
  inputHash: string; requestId: string;
  state: 'queued'|'running'|'needs_review'|'failed'|'cancelled'|'interrupted'|'applied';
  progress: string; createdAt: string; updatedAt: string;
  startedAt: null|string; finishedAt: null|string; skillBindings: SkillBinding[];
  result: Candidate|null; resultHash: string|null;
  error: null|{code: string; message: string};
  usage: null|{inputTokens: number; outputTokens: number};
  appliedDraftRevision: number|null;
};
export type InputReview = {
  conversation: Conversation; inputHash: string;
  input: Record<string,unknown>; skillBindings: SkillBinding[]; usageNotice: string;
};
export type RunRequest = {expectedRevision: number; inputHash: string; requestId: string; consent: true};

const segment = (value: string) => encodeURIComponent(value);
export const isActiveRun = (run: Run|null) => run?.state==='queued'||run?.state==='running';
export const readyForGeneration = (status: AgentStatus|null) => status?.available===true&&status.authentication==='ready';
export const runStateLabel = (state: Run['state']) => ({queued:'Queued for generation',running:'Generating a candidate',needs_review:'Candidate needs your review',failed:'Generation failed',cancelled:'Generation cancelled',interrupted:'Generation interrupted',applied:'Applied to local draft'})[state];

export const agentApi = {
  status: () => api<AgentStatus>('/api/agent/status'),
  conversations: (draftId: string) => api<{conversations: Conversation[]}>(`/api/agent/conversations?draftId=${segment(draftId)}`),
  create: (draftId: string, expectedDraftRevision: number, contentType: ContentType) => api<{conversation: Conversation}>('/api/agent/conversations',{method:'POST',body:JSON.stringify({draftId,expectedDraftRevision,contentType})}),
  conversation: (id: string) => api<{conversation: Conversation}>(`/api/agent/conversations/${segment(id)}`),
  answer: (id: string, expectedRevision: number, slot: QuestionSlot, value: string) => api<{conversation: Conversation}>(`/api/agent/conversations/${segment(id)}/answer`,{method:'POST',body:JSON.stringify({expectedRevision,slot,value})}),
  review: (id: string) => api<InputReview>(`/api/agent/conversations/${segment(id)}/review`),
  generate: (id: string, request: RunRequest) => api<{run: Run}>(`/api/agent/conversations/${segment(id)}/runs`,{method:'POST',body:JSON.stringify(request)}),
  runs: (draftId: string) => api<{runs: Run[]}>(`/api/agent/runs?draftId=${segment(draftId)}`),
  run: (id: string) => api<{run: Run}>(`/api/agent/runs/${segment(id)}`),
  cancel: (id: string) => api<{run: Run}>(`/api/agent/runs/${segment(id)}/cancel`,{method:'POST',body:'{}'}),
  apply: (id: string, expectedDraftRevision: number, resultHash: string, channels: string[]) => api<{run: Run; draft: Draft}>(`/api/agent/runs/${segment(id)}/apply`,{method:'POST',body:JSON.stringify({expectedDraftRevision,resultHash,channels})}),
};
