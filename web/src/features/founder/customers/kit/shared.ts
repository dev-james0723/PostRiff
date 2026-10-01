/**
 * The one import seam for the components web-shell builds under `features/founder/shared` (CONTRACTS §6). Pages
 * import from here so a renamed export on that side is a one-line fix. Contracts the pages rely on:
 *
 * - `ChartCard {title, subtitle, receiptId, definitionId, period, onAsk, dataState, asOf, coverage, data, children}`
 * - `EvidenceDrawer {open, onOpenChange, receiptId, record}` (controlled use)
 * - `MetricTile {id, label, value, unit, currency, delta, deltaPeriod, sparkline, dataState, coverage, href, receiptId, collectingSince, onAsk}`
 * - `DataStateChip {state, asOf}`
 */
export { ChartCard, DataStateChip, EvidenceDrawer, MetricTile } from '@/features/founder/shared';
