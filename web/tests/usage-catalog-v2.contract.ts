/** Compile-only consumer contract. Negative checks must remain compiler errors. */
import type { Usage, CreditBalance, ModelCatalog, BillingMode, BootstrapPlan, FreePreview } from '../src/lib/api/types';
import type { WorkspacePlan } from '../src/types';

const modes: BillingMode[] = ['free_preview', 'managed_credits', 'legacy_allowances'];
const plans: WorkspacePlan[] = ['trial', 'free', 'creator', 'studio', 'assist'];
const bootstrap: BootstrapPlan[] = ['free', 'studio', 'assist'];
// @ts-expect-error A paid entitlement cannot be selected by bootstrap.
const paidBootstrap: BootstrapPlan = 'creator';
// @ts-expect-error Unknown billing modes are not nullable guessing.
const unknownMode: BillingMode = 'trial';

function read(value: Usage) {
  const balance: CreditBalance | null = value.credits;
  if (value.billingMode === 'free_preview') {
    const noWallet: null = value.credits;
    const preview: FreePreview = value.freePreview;
    return [noWallet, preview.postDoctor.remaining, preview.genome.eligible];
  }
  const noPreview: null = value.freePreview;
  return [balance?.currentPeriodGrantMilliCredits, balance?.currentPeriodExpiresAt,
    balance?.policy, balance?.lots, balance?.spendAvailable, noPreview];
}

function image(value: NonNullable<ModelCatalog['imageGeneration']>) {
  const creditEstimate: boolean = value.creditEstimateAvailable;
  return creditEstimate;
}
// @ts-expect-error Every image producer must declare qualification explicitly.
const missingImageQualification: NonNullable<ModelCatalog['imageGeneration']> = { available: true, model: null, provider: null, costClass: 'paid', independentOfWritingModel: true, detail: '' };
void [modes, plans, bootstrap, paidBootstrap, unknownMode, read, image, missingImageQualification];
