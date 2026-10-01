/**
 * Catalog ids whose `currency_policy` is `native_currency_separate` (generated from src/rafii_control/pack/catalogs; the
 * node test `tests/founder-metric-policy.test.cjs` fails when the catalog and this list disagree).
 */
export const NATIVE_CURRENCY_METRIC_IDS: readonly string[] = [
  'ai_actual_cost',
  'ai_failed_cost',
  'cac',
  'cash_collected',
  'collections',
  'contribution',
  'cost_per_useful',
  'cost_vs_cash',
  'decision_recovered_cash',
  'delinquent_mrr',
  'dispute_net',
  'mrr',
  'mrr_churn',
  'mrr_contraction',
  'mrr_expansion',
  'mrr_forecast',
  'mrr_movements',
  'mrr_new',
  'mrr_reactivation',
  'net_collections',
  'refunds',
  'refunds_disputes',
];
