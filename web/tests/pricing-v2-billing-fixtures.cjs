const NOW = Date.UTC(2026, 8, 30, 12) / 1000;
const creator = (priceCents = 5900, overrides = {}) => ({
  id: 'creator-v1', plan: 'creator', version: 1, label: 'Creator', priceCents,
  defaultPriceCents: 5900, priceVariantId: `creator-${priceCents / 100}-v1`,
  catalogState: 'public', current: true, newCheckoutEnabled: false, checkoutAvailable: false,
  currency: 'usd', status: 'proposed', priceLabel: 'proposed',
  entitlements: { monthlyCredits: 3500, writingBatches: 0, mediaCredits: 0, members: 1, connectedAccounts: 6, storageMb: 1000 }, ...overrides
});
const balance = (overrides = {}) => ({ mode: 'credits', policy: 'synthetic-v2',
  availableMilliCredits: 4800000, heldMilliCredits: 200000, usedMilliCredits: 7200000,
  currentPeriodGrantMilliCredits: 3500000, currentPeriodExpiresAt: NOW + 86400,
  debtMilliCredits: 0, purchasedCredits: [{ available: 2000000, held: 0, expiresAt: null }],
  spendAvailable: false, spendUnavailableReason: 'policy_inactive', quoteType: 'spending_limit', textOnly: false, ...overrides
});
function usage(mode = 'managed_credits', overrides = {}) {
  const terms = creator();
  return { billingMode: mode, aiUsageExempt: false,
    entitlement: { planTermsId: terms.id, plan: 'creator', writingBatchesRemaining: 0, mediaCreditsRemaining: 0, connectedAccounts: 6, members: 1, storageMb: 1000, resetsAt: NOW + 86400, source: 'plan', version: 1 },
    subscription: { planTermsId: terms.id, provider: 'fixture', status: 'active', currentPeriodEnd: NOW + 86400, cancelAtPeriodEnd: false, graceUntil: null, plan: 'creator', label: 'Creator', priceCents: 4900, priceVariantId: 'creator-49-v1', currency: 'usd', priceStatus: 'active', termsVersion: 1, live: false },
    credits: mode === 'managed_credits' ? balance() : null,
    freePreview: mode === 'free_preview' ? { postDoctor: { remaining: 0, eligible: false, reason: 'used' }, genome: { remaining: 1, eligible: false, reason: 'funding_unavailable', maxPosts: 20 } } : null,
    budget: { windowKind: 'month', spentUsdMicro: 1200000, reservedUsdMicro: 300000, warnUsdMicro: 8000000, stopUsdMicro: 10000000, status: 'active' },
    overage: 'stop', ledger: [], planTerms: [terms], note: '', lifecycle: { status: 'active', draftsRetained: true },
    billing: { provider: 'fixture', checkoutAvailable: false, portalAvailable: false },
    membership: { userId: 'synthetic-owner', role: 'owner', permissions: ['read', 'edit', 'owner'] }, ...overrides
  };
}
function legacy(priceCents = 1900) {
  const terms = creator(priceCents, { id: 'legacy-v1', plan: priceCents === 1900 ? 'studio' : 'assist', label: priceCents === 1900 ? 'Studio' : 'Assist', priceVariantId: null, status: 'active', catalogState: 'legacy', entitlements: { writingBatches: 30, mediaCredits: 10, members: 1, connectedAccounts: 3, storageMb: 1000 } });
  const data = usage('legacy_allowances');
  return { ...data, entitlement: { ...data.entitlement, planTermsId: terms.id, plan: terms.plan, writingBatchesRemaining: 12, mediaCreditsRemaining: 4 }, subscription: { ...data.subscription, planTermsId: terms.id, plan: terms.plan, label: terms.label, priceCents, priceVariantId: null }, planTerms: [terms, creator()] };
}
module.exports = { NOW, creator, balance, usage, legacy };
