import type { Usage } from '@/lib/api/types';
import type { RadarCatalog, RadarScan } from '@/lib/growth/radar-types';

export function radarAvailability(usage: Usage | null | undefined, catalog: RadarCatalog | null | undefined, spec: { sources: string[]; useAi: boolean }, catalogReady: boolean) {
  const unavailable = { available: false, detail: 'Paid scans and AI review are unavailable until their server credit route is qualified. Choose a ready zero-cost source with AI off. Saved scans and manual review remain available.' };
  if (!usage || !catalog || !catalogReady) return unavailable;
  if (usage.billingMode === 'legacy_allowances') return { available: true, detail: 'Your legacy scan allowance applies.' };
  if (catalog.paidScanAvailable !== false || catalog.aiAnalysisAvailable !== false || spec.useAi || !spec.sources.length
    || !spec.sources.every(id => catalog.consent.sources?.includes(id) && catalog.sources.some(source => source.id === id && source.status === 'ready'))) return unavailable;
  return { available: true, detail: 'Server-qualified source collection only. No customer credits charged; AI review is off.' };
}
export function radarScanAvailable(usage: Usage | null | undefined, catalog: RadarCatalog | null | undefined, scan: Pick<RadarScan, 'sources' | 'useAi' | 'maximumUsdMicro' | 'customerCharge' | 'stale'>, catalogReady: boolean) {
  if (scan.stale || !radarAvailability(usage, catalog, scan, catalogReady).available) return false;
  return usage?.billingMode === 'legacy_allowances' || (scan.maximumUsdMicro === 0 && scan.customerCharge === 'none' && scan.useAi === false);
}
