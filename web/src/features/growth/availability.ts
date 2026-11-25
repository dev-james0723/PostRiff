import type { Usage } from '@/lib/api/types';
import type { GrowthCatalog } from '@/lib/growth/types';

const reasons: Record<string, string> = {
  used: 'This lifetime preview has already been used.',
  permission_required: 'Ask a workspace editor to run this preview.',
  feature_disabled: 'This preview is not enabled here yet.',
  consent_required: 'Review the allowed AI routes before analysis.',
  funding_unavailable: 'Platform funding is unavailable. Your lifetime preview remains unused.',
  rate_limited: 'Preview funding is temporarily at its run limit.',
  plan_unavailable: 'This preview is unavailable for this plan.'
};
export type GrowthAction = 'check' | 'genome' | 'rewrite' | 'audience' | 'postmortem' | 'radar' | 'calibration';
/** Existing server lifetime projection only. A future paid contract must be reconciled before enabling it. */
export function growthAvailability(usage: Usage | null | undefined, action: GrowthAction) {
  if (!usage) return { available: false, detail: 'Growth availability is still loading.' };
  if (usage.billingMode === 'legacy_allowances') return { available: true, detail: 'Your legacy daily allowance applies.' };
  if (usage.billingMode === 'free_preview' && (action === 'check' || action === 'genome')) {
    const preview = usage.freePreview[action === 'check' ? 'postDoctor' : 'genome'];
    const label = action === 'check' ? 'Post Doctor check' : 'recent-20 Genome analysis';
    return { available: preview.eligible && preview.remaining > 0, detail: `${preview.remaining} lifetime ${label} remaining. ${preview.eligible ? 'Platform funded; no user credits charged.' : reasons[preview.reason ?? ''] ?? 'This preview is unavailable.'}` };
  }
  return { available: false, detail: 'This AI task is unavailable until its server funding and credit approval route is qualified. Saved results and manual review remain available.' };
}

export function rewriteAvailability(usage: Usage | null | undefined, catalog: GrowthCatalog | null | undefined, catalogReady: boolean) {
  const unavailable = { available: false, detail: 'Rewrite funding is unavailable. Saved results and manual review remain available.' };
  if (!usage || !catalog || !catalogReady || !catalog.consented) return unavailable;
  if (usage.billingMode === 'legacy_allowances') return growthAvailability(usage, 'rewrite');
  const credits = catalog.rewriteCredits;
  if (usage.billingMode !== 'managed_credits' || credits?.billingMode !== 'managed_credits' || credits.available !== true || credits.estimateAvailable !== true) return unavailable;
  return { available: true, detail: 'Review and approve the maximum credits for the complete rewrite and recheck.' };
}

export function baseCheckAvailability(usage: Usage | null | undefined, catalog: GrowthCatalog | null | undefined, catalogReady: boolean) {
  if (usage?.billingMode !== 'managed_credits') return growthAvailability(usage, 'check');
  const projection = catalog?.baseChecks;
  if (!catalogReady || projection?.billingMode !== 'managed_credits' || projection.available !== true) {
    const detail = projection?.reason === 'funding_unavailable'
      ? 'Platform funding for this check is unavailable.'
      : reasons[projection?.reason ?? ''] ?? 'This check is unavailable until server funding is qualified.';
    return { available: false, detail: `${detail} Saved results and manual review remain available.` };
  }
  return { available: true, detail: 'Platform-funded check; no customer credits charged. Availability is rechecked before submission.' };
}

export function genomeAvailability(usage: Usage | null | undefined, catalog: GrowthCatalog | null | undefined, catalogReady: boolean, csvImport = false) {
  const lifetime = usage?.billingMode === 'free_preview'
    ? `${usage.freePreview.genome.remaining} lifetime recent-20 Genome analysis remaining. `
    : '';
  const unavailable = (detail = 'Genome availability must be refreshed before analysis.') => ({
    available: false,
    detail: `${lifetime}${detail} Saved results and manual review remain available.`
  });
  if (!usage || !catalogReady || catalog?.genome !== true || catalog.consented !== true) return unavailable();
  if (usage.billingMode === 'legacy_allowances') return growthAvailability(usage, 'genome');
  if (usage.billingMode !== 'managed_credits' && usage.billingMode !== 'free_preview') return unavailable();
  const projection = catalog.genomeAnalysis;
  const mode = usage.billingMode === 'managed_credits' ? 'managed_credits' : 'free';
  if (projection?.billingMode !== mode || projection.available !== true || projection.maxPosts !== 20) {
    return unavailable(projection?.reason === 'funding_unavailable'
      ? 'Platform funding is unavailable.'
      : reasons[projection?.reason ?? ''] ?? 'This analysis is unavailable until server funding is qualified.');
  }
  if (csvImport && projection.csvImport?.available !== true) {
    return unavailable(projection.csvImport?.reason === 'permission_required'
      ? 'Ask the workspace owner to import owned CSV history.'
      : reasons[projection.csvImport?.reason ?? ''] ?? 'CSV import is unavailable for this workspace.');
  }
  if (usage.billingMode === 'free_preview') return growthAvailability(usage, 'genome');
  return { available: true, detail: 'Platform-funded analysis of up to 20 owned posts; no customer credits charged. Availability is rechecked before submission.' };
}
