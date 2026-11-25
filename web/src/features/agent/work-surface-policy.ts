import type { ModelOption, ModelCatalog, Usage } from '@/lib/api/types';
import type { SlashCommand } from '@/lib/agent-runtime/commands';

export function workSurfaceCommands(commands: SlashCommand[], mode: Usage['billingMode'] | undefined) {
  return mode === 'legacy_allowances' ? commands : commands.filter(command => command.kind === 'client');
}

/** Display/submit gating only: the server remains the spending and entitlement authority. */
export function workSurfacePolicy(usage: Usage | null | undefined, cost: ModelOption['costClass'] | undefined, image: boolean, capability?: Pick<NonNullable<ModelCatalog['imageGeneration']>, 'available' | 'creditEstimateAvailable'>) {
  const managed = usage?.billingMode === 'managed_credits';
  const free = usage?.billingMode === 'free_preview';
  const creditMode = image ? managed : cost === 'paid' && Boolean(managed && !usage?.aiUsageExempt || usage?.billingMode === 'legacy_allowances' && usage.credits);
  let blocked: string | null = null;
  if (!usage?.billingMode) blocked = 'Task availability is still loading.';
  else if (!image && !cost) blocked = 'Writing availability is still loading.';
  else if (image && free) blocked = 'Image generation needs an active managed-credit plan. Your saved work remains available.';
  else if (image && !capability?.available) blocked = 'Image generation is not available here.';
  else if (image && managed && !capability?.creditEstimateAvailable) blocked = 'A qualified image credit estimate is not available yet.';
  else if (!image && free && cost === 'paid') blocked = 'Free has no managed writing allowance. Save your idea, try the preview, or choose your own writing route.';
  else if (creditMode && (!usage?.credits || !usage.credits.spendAvailable)) blocked = 'Managed credit spending is not available. Review Usage & plan; your saved work remains available.';
  return { managed, free, creditMode, blocked };
}

export function writingCostDescription(usage: Usage | null | undefined): string {
  if (!usage) return 'Writing availability is unavailable. Saving sources is free.';
  if (usage.billingMode === 'managed_credits') return usage.aiUsageExempt
    ? 'Your server-assigned application quota applies to writing. Separately paid tools need their own approval.'
    : 'Managed drafts use a task estimate and your approved maximum credits. Saving sources is free.';
  if (usage.billingMode === 'free_preview') return 'Free has no managed writing allowance. Save sources, use the preview, or choose your own writing route.';
  const remaining = usage.entitlement.writingBatchesRemaining;
  return `${remaining} writing batch${remaining === 1 ? '' : 'es'} left. Only legacy cloud drafts use one; saving sources is free.`;
}
