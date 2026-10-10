import type { SnapshotState, VoiceProfile } from '@/lib/api/types';

export const BRAND_BRAIN_V11 = process.env.NEXT_PUBLIC_BRAND_BRAIN_V11 === '1';
export interface BrainView {
  schema: string;
  proposalDigest: string | null;
  proposalStatus: 'none' | 'proposed' | 'reviewing' | 'stale';
  impact: { drafts: number | null; heldPosts: number | null; needsReview: number | null; currentlyHeld: number | null; impactDigest: string };
  limits: { maxSamples: number; maxInputBytes: number; maxTextChars: number };
  versions: { revision: number; profile: VoiceProfile; approvedAt: string; approvedBy?: string; stale: boolean; restoreEligible: boolean }[];
  analysisQuote?: { id: string; route: string; model: string; estimatedMicroUsd: number; expiresAt: number; sourceDigest: string; workspaceRevision: number; status: 'quoted' | 'consumed'; creditLimit?: { quoteId: string; maxMilliCredits: number; policy: string; expiresAt: number; kind: 'spending_limit' } } | null;
  preview?: { kind: 'guideline' | 'paired'; generated: boolean; label: string; prompt: string; language: string; platform: string; neutral: { guidance: string[]; text?: string }; proposed: { guidance: string[]; proposalDigest: string; text?: string }; receipt: { model: string | null; provider: string | null; generationKind?: 'model' | 'template'; comparabilityDigest?: string; memory?: unknown[]; paid: false; activeRevisionUnchanged: boolean } } | null;
  lastReceipt?: { action: string; actor: string; at: number; requestId: string; activeRevisionBefore: number | null; activeRevisionAfter: number | null; needsReview: number; heldPosts: number } | null;
}
export function brainView(state?: SnapshotState): BrainView | null {
  const view = state?.brandBrain;
  return view && typeof view === 'object' && 'schema' in view ? view as BrainView : null;
}
export type BrainAction = (action: string, payload: Record<string, unknown>) => Promise<boolean>;
export type BrainTranslate = (en: string, hant: string, hans: string) => string;
