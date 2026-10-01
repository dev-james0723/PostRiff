/**
 * Every public sentence about plans and pricing, for both catalogs (spec §13.1–13.2; PRD R-COM-04).
 *
 * `legacy` reproduces today's site word for word, so nothing a visitor reads changes until
 * NEXT_PUBLIC_PRICING_CATALOG=v2. `v2` sells Free and Creator only: outcomes first, credits explained once,
 * Creator pricing described as a beta that is still being validated (never "proven"), and no trial, writing
 * batches or legacy prices. Numbers come from the catalog module, which is held to the database's contract
 * fixture, so a price or credit change can only happen in one place. The public site is English (`lang=en`).
 */
import { PRICING_CATALOG, TRIAL, V2_CATALOG, catalogLimit, catalogPlan, countText, formatPrice, plans, usdText, type CatalogPlan, type Plan, type PricingCatalogId } from './plans';

export interface FaqItem {
  q: string;
  a: string;
}

export interface DocSectionCopy {
  heading: string;
  paragraphs: string[];
}

export interface MarketingCopy {
  catalog: PricingCatalogId;
  pricingMeta: { description: string };
  pricingHero: { eyebrow: string; title: string; accent: string; description: string };
  /** Under the plan cards; null when there is nothing to qualify. */
  pricingFootnote: string | null;
  pricingFaq: FaqItem[];
  landingPricing: { title: string; accent: string; description: string; compareLink: string };
  /** The plan question in the landing page's FAQ. */
  landingFaqItem: FaqItem;
  ctaBand: { description: string; primaryLabel: string; note: string };
  hero: { primaryLabel: string; note: string };
  /** The sign-up button in the site header, mobile menu and channel pages. */
  headerCta: string;
  /** The usage figure in the illustrative product frame. */
  previewStat: [string, string];
  terms: { title: string; paragraph: string };
  signUp: SignUpCopy;
  docs: { gettingStartedCreate: string; usageSummary: string; usageSections: DocSectionCopy[] };
}

/** What the sign-up form says; the page passes it to the form so this copy stays on the server. */
export interface SignUpCopy {
  metaTitle: string;
  metaDescription: string;
  subtitle: string;
  /** The sign-in page's link to sign-up ("New to Rafii? …"). */
  switchLabel: string;
  showPlanChooser: boolean;
  /** Legacy only: the trial plan picker (Studio / Studio Assist with the price after the trial). */
  chooser: { legend: string; options: { id: 'studio' | 'assist'; label: string; note: string; price: string | null }[]; note: string } | null;
  /** v2 only: what starting free means, in three short lines. */
  promise: string[] | null;
}

/* ---------- legacy: today's copy, unchanged ---------- */

const LEGACY_PRICING_FAQ: FaqItem[] = [
  { q: 'When am I billed?', a: 'Monthly, in advance, from the day you subscribe. The trial never converts automatically; you choose a plan yourself.' },
  { q: 'Can I cancel any time?', a: 'Yes, from the billing portal. Paid features run to the end of the period; drafts stay readable and exportable afterwards.' },
  { q: 'What does “introductory pricing” mean?', a: 'These are the prices for early customers. If they change before general availability, existing subscribers keep their price for at least a year.' },
  { q: 'Refunds?', a: 'See the Terms of Service. Nothing is charged during the trial, so you can evaluate Rafii fully before paying.' },
  { q: 'Taxes?', a: 'Shown at checkout where applicable, based on your billing address.' }
];

/** "$19/mo after trial" for a legacy trial plan, from the legacy catalog. */
function afterTrial(id: 'studio' | 'assist'): string | null {
  const priced = plans.find((p) => p.id === id);
  return priced ? `$${priced.priceCents / 100}/mo after trial` : null;
}

function legacyCopy(): MarketingCopy {
  return {
    catalog: 'legacy',
    pricingMeta: { description: 'Simple monthly plans. 14-day trial, no card. Allowances stop at the limit — never a surprise charge.' },
    pricingHero: {
      eyebrow: 'Pricing',
      title: 'Simple pricing.',
      accent: 'No surprises.',
      description: `Start with a ${TRIAL.days}-day trial — ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches, no card. Pick a plan when you are ready.`
    },
    pricingFootnote: plans.some((p) => p.status === 'proposed') ? 'Prices are shown in USD. Introductory pricing applies to early customers; see the FAQ below.' : null,
    pricingFaq: LEGACY_PRICING_FAQ,
    landingPricing: {
      title: 'Two plans.',
      accent: 'No surprises.',
      description: `${TRIAL.days}-day trial with ${TRIAL.connectedAccounts} connected accounts and ${TRIAL.writingBatches} writing batches. No card, no automatic conversion.`,
      compareLink: 'Compare plans in detail'
    },
    landingFaqItem: {
      q: 'How does the trial work?',
      a: `${TRIAL.days} days, ${TRIAL.connectedAccounts} connected accounts, ${TRIAL.writingBatches} writing batches, no card. It never converts into a paid plan by itself.`
    },
    ctaBand: {
      description: 'Start a 14-day trial with two connected accounts and ten writing batches. Export everything, any time.',
      primaryLabel: 'Start free trial',
      note: 'No credit card required during the trial.'
    },
    hero: { primaryLabel: 'Start free trial', note: 'No credit card · 14-day trial · Export everything, any time' },
    headerCta: 'Start free trial',
    previewStat: ['Writing batches', '61'],
    terms: {
      title: 'Trial, subscriptions and billing',
      paragraph: `New workspaces get a ${TRIAL.days}-day trial with ${TRIAL.connectedAccounts} connected accounts and ${TRIAL.writingBatches} writing batches. No payment method is required and the trial never converts into a paid plan automatically. Paid plans remain proposed until commercial approval and payment verification are complete. If enabled, they are billed monthly in advance through Stripe at the price shown when you subscribe. Plan allowances stop when they are used up; there is no automatic overage charge. You can cancel at any time from the billing portal; access to paid features continues until the end of the paid period, and your drafts stay readable and exportable afterwards. We may change prices with at least 30 days’ notice by email; a change applies from your next renewal. [Refund policy — to be confirmed by counsel.] Taxes are shown at checkout where applicable.`
    },
    signUp: {
      metaTitle: 'Start your free trial',
      metaDescription: 'Create a Rafii workspace. 14-day trial, no card required.',
      subtitle: '14-day free trial. No card needed.',
      switchLabel: 'Start a free trial',
      showPlanChooser: true,
      chooser: {
        legend: 'Trial plan',
        options: [
          { id: 'studio', label: 'Studio', note: 'Manual drafting and scheduling', price: afterTrial('studio') },
          { id: 'assist', label: 'Studio Assist', note: 'Adds AI writing batches', price: afterTrial('assist') }
        ],
        note: 'No charge during the trial. You’re only billed if you choose a paid plan.'
      },
      promise: null
    },
    docs: {
      gettingStartedCreate: 'Sign up with Google or an email code and choose a trial plan. A workspace is created for you; you are its owner.',
      usageSummary: 'Allowances, stop-lines and how plans work.',
      usageSections: [
        { heading: 'Allowances', paragraphs: ['Writing batches, media credits, connected accounts and storage are per plan. When an allowance is used up, the action stops and tells you; nothing is charged silently.'] },
        { heading: 'Trial', paragraphs: ['14 days, no card, no automatic conversion. You choose a plan yourself when you are ready.'] },
        {
          heading: 'Subscriptions',
          paragraphs: ['Proposed monthly billing through Stripe, available only when the plan and payment integration are activated. Payment method, plan changes, cancellation and invoices live in the billing portal (Account → Usage & plan → Manage billing).']
        }
      ]
    }
  };
}

/** Today's comparison table: one column per legacy plan. */
export function legacyCompareRows(): { label: string; values: string[] }[] {
  const rows: { label: string; value: (plan: Plan) => string }[] = [
    { label: 'Connected accounts', value: (p) => String(p.limits.connectedAccounts) },
    { label: 'AI writing batches / month', value: (p) => (p.limits.writingBatches === 'none' ? 'Not included' : String(p.limits.writingBatches)) },
    { label: 'Media credits / month', value: (p) => String(p.limits.mediaCredits) },
    { label: 'Storage', value: (p) => `${p.limits.storageMb / 1000} GB` },
    { label: 'Members', value: (p) => String(p.limits.members) },
    { label: 'Overage behaviour', value: () => 'Stops — never charged silently' },
    { label: 'Export everything', value: () => 'Always' },
    { label: 'Account deletion', value: () => 'Self-service' }
  ];
  return rows.map((row) => ({ label: row.label, values: plans.map((plan) => row.value(plan)) }));
}

/** Today's trial card beside the two legacy plans. */
export const LEGACY_TRIAL_CARD = {
  eyebrow: 'Before you pay',
  title: 'Trial',
  priceSuffix: `/ ${TRIAL.days} days`,
  items: [`${TRIAL.connectedAccounts} connected accounts`, `${TRIAL.writingBatches} AI writing batches`, `${TRIAL.mediaCredits} media credit`, `${TRIAL.storageMb} MB storage`, 'No card. No automatic conversion.'],
  action: 'Start free'
} as const;

/* ---------- v2: Free and Creator ---------- */

function required(plan: CatalogPlan | undefined, name: string): CatalogPlan {
  // A catalog without the plan the copy describes must fail the build, never print a wrong price.
  if (!plan) throw new Error(`The v2 catalog has no ${name} plan.`);
  return plan;
}

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const word = (value: number) => WORDS[value] ?? countText(value);

function v2Numbers() {
  const free = required(catalogPlan('free'), 'Free');
  const creator = required(catalogPlan('creator'), 'Creator');
  const first = free.firstValue ?? { postDoctorRuns: 1, genomeAnalyses: 1, genomeMaxPosts: 20 };
  return {
    free,
    creator,
    first,
    price: usdText(creator.priceCents),
    credits: countText(catalogLimit(creator, 'monthlyCredits') ?? 0),
    perUsd: V2_CATALOG.creditsPerUsd ?? 300,
    freeAccounts: catalogLimit(free, 'connectedAccounts') ?? 1
  };
}

/** The comparison table under the v2 cards: one column per plan for sale, in catalog order. */
export function v2CompareRows(): { label: string; values: string[] }[] {
  const columns = V2_CATALOG.plans.filter((plan) => plan.plan === 'free' || plan.plan === 'creator');
  const limit = (plan: CatalogPlan, key: string) => {
    const value = catalogLimit(plan, key);
    if (value === null) return '—';
    return value > 1 ? `Up to ${countText(value)}` : countText(value);
  };
  const row = (label: string, value: (plan: CatalogPlan) => string) => ({ label, values: columns.map(value) });
  return [
    row('Managed AI credits', (plan) => {
      const credits = catalogLimit(plan, 'monthlyCredits');
      return credits ? `${countText(credits)} / month` : 'None';
    }),
    row('Connected accounts', (plan) => limit(plan, 'connectedAccounts')),
    row('Brands', (plan) => limit(plan, 'brands')),
    row('Seats', (plan) => {
      const seats = catalogLimit(plan, 'members');
      return seats === null ? '—' : countText(seats);
    }),
    row('Credit rollover', (plan) => (catalogLimit(plan, 'monthlyCredits') ? 'None — credits reset each period' : '—')),
    row('Overage behaviour', () => 'Stops — never charged silently'),
    row('Export everything', () => 'Always'),
    row('Account deletion', () => 'Self-service')
  ];
}

function v2Copy(): MarketingCopy {
  const { creator, first, price, credits, perUsd, freeAccounts } = v2Numbers();
  const creatorAccounts = catalogLimit(creator, 'connectedAccounts');
  const creatorBrands = catalogLimit(creator, 'brands');
  const firstLook = `one Post Doctor check and one analysis of up to ${countText(first.genomeMaxPosts)} recent posts`;
  return {
    catalog: 'v2',
    pricingMeta: { description: `Start free, no card. Creator is ${price} a month with ${credits} managed credits. Paid work stops at your limit — never a surprise charge.` },
    pricingHero: {
      eyebrow: 'Pricing',
      title: 'Start free.',
      accent: 'Upgrade when it’s worth it.',
      description: `Free shows Rafii working on your own writing — ${firstLook} — with no card. Creator adds managed AI work every month once Rafii is part of your routine.`
    },
    pricingFootnote: `Prices are shown in USD. Creator is in a paid beta and its price is still being validated; the price shown at checkout is the price you pay.`,
    pricingFaq: [
      {
        q: 'What can I do on Free?',
        a: `Save your sources and drafts, edit, approve and export them, and see Rafii work on your own writing: ${firstLook}, on us. Free has no monthly AI credits, so it never charges you.`
      },
      {
        q: 'What does Creator add?',
        a: `${credits} managed AI credits every month for the work Rafii runs for you, like drafting and rewriting in your voice${creatorAccounts && creatorBrands ? `, with up to ${countText(creatorAccounts)} connected accounts and ${countText(creatorBrands)} brands` : ''}. Each task shows its credit limit before it runs.`
      },
      {
        q: 'What are managed credits?',
        a: `Credits pay for the AI and data work Rafii runs for you on Creator: ${perUsd} credits equal US$1 of a task’s verified model and tool cost, rounded once per task. You see each task’s credit limit before it runs; Rafii holds it, charges what the task used and returns the rest, and a failed task uses no credits. When credits run out, paid work stops and nothing is charged silently. Credits reset each billing period; unused credits don’t roll over.`
      },
      {
        q: 'Is the Creator price final?',
        a: 'Creator is in a paid beta and its price is still being validated. The price shown at checkout is the price you pay, and it won’t change at renewal without at least 30 days’ notice by email.'
      },
      { q: 'When am I billed?', a: 'Monthly, in advance, from the day you subscribe to Creator. Free never asks for a card.' },
      { q: 'Can I cancel any time?', a: 'Yes, from the billing portal. Creator runs to the end of the paid period; then the workspace returns to Free, and your drafts stay readable and exportable.' },
      { q: 'I subscribed before Creator. What changes?', a: 'Nothing, unless you choose to. Earlier plans keep their price and what they include, and Usage & plan keeps showing them.' },
      { q: 'Refunds?', a: 'See the Terms of Service. Free never charges you, so you can see Rafii work before paying.' },
      { q: 'Taxes?', a: 'Shown at checkout where applicable, based on your billing address.' }
    ],
    landingPricing: {
      title: 'Start free.',
      accent: 'No surprises.',
      description: `Free shows Rafii working on your own writing, with no card. Creator is ${price} a month with ${credits} managed credits, and paid work always stops at your limit.`,
      compareLink: 'Compare plans in detail'
    },
    landingFaqItem: {
      q: 'What does Free include?',
      a: `${firstLook.charAt(0).toUpperCase()}${firstLook.slice(1)}, on us, with ${word(freeAccounts)} connected account${freeAccounts === 1 ? '' : 's'} and no card. Drafts, edits and exports stay available, and Free never charges you.`
    },
    ctaBand: {
      description: `Start free with ${word(freeAccounts)} connected account${freeAccounts === 1 ? '' : 's'} — no card. Choose Creator when you want Rafii working every week. Export everything, any time.`,
      primaryLabel: 'Start free',
      note: 'No credit card required.'
    },
    hero: { primaryLabel: 'Start free', note: 'No credit card · Free to start · Export everything, any time' },
    headerCta: 'Start free',
    previewStat: ['Credits left', '2,140'],
    terms: {
      title: 'Free plan, subscriptions and billing',
      paragraph: `New workspaces start on Free. No payment method is required; Free includes ${firstLook} and has no monthly managed credits. Creator is a monthly subscription that includes ${credits} managed credits per billing period. Credits pay for the AI and data work Rafii runs for you: ${perUsd} credits correspond to US$1 of the verified cost of a task, rounded once per task, and a task’s credit limit is shown and held before it runs. Credits expire at the end of each billing period and do not roll over. Paid plans remain proposed until commercial approval and payment verification are complete. If enabled, they are billed monthly in advance through Stripe at the price shown when you subscribe. Paid work stops when credits are used up; there is no automatic overage charge. You can cancel at any time from the billing portal; access to paid features continues until the end of the paid period, after which the workspace returns to Free and your drafts stay readable and exportable. Workspaces that subscribed under an earlier plan keep that plan and its price until they change it, and a trial that is already running continues until it ends. We may change prices with at least 30 days’ notice by email; a change applies from your next renewal. [Refund policy — to be confirmed by counsel.] Taxes are shown at checkout where applicable.`
    },
    signUp: {
      metaTitle: 'Start free',
      metaDescription: 'Create a Rafii workspace. Free to start, no card required.',
      subtitle: 'Start free. No card needed.',
      switchLabel: 'Start free',
      showPlanChooser: false,
      chooser: null,
      promise: ['See Rafii work on your own writing first.', 'Connect your accounts when you’re ready.', 'Choose Creator when ongoing managed AI work is worth it.']
    },
    docs: {
      gettingStartedCreate: 'Sign up with Google or an email code. A workspace is created for you on Free; you are its owner.',
      usageSummary: 'Free, managed credits, limits and how plans work.',
      usageSections: [
        { heading: 'Free', paragraphs: [`Free has no monthly managed credits and never charges you. It includes ${firstLook}, plus saving, editing, approving and exporting your work.`] },
        {
          heading: 'Managed credits',
          paragraphs: [
            `Creator includes ${credits} managed credits each billing period. ${perUsd} credits equal US$1 of the verified model and tool cost of a task, rounded once per task.`,
            'Before a task runs you see its credit limit. Rafii holds that amount, charges what the task used and returns the rest. A failed task uses no credits, and an unknown cost stays held until it is confirmed rather than counted as zero.'
          ]
        },
        { heading: 'Limits', paragraphs: ['When credits run out, paid work stops and tells you; nothing is charged silently. Credits reset each billing period and unused credits don’t roll over. Connected accounts, brands and seats are per plan.'] },
        { heading: 'Earlier plans', paragraphs: ['Workspaces that subscribed before Creator keep their plan, what it includes and its price; Usage & plan shows them. A trial that is already running continues until it ends, then the workspace moves to Free.'] },
        {
          heading: 'Subscriptions',
          paragraphs: ['Proposed monthly billing through Stripe, available only when the plan and payment integration are activated. Payment method, cancellation and invoices live in the billing portal (Account → Usage & plan → Manage plan).']
        }
      ]
    }
  };
}

/** The copy for one catalog; the site renders `marketingCopy()` (the build's NEXT_PUBLIC_PRICING_CATALOG). */
export function marketingCopy(catalog: PricingCatalogId = PRICING_CATALOG): MarketingCopy {
  return catalog === 'v2' ? v2Copy() : legacyCopy();
}

/** "$59 / month", "$0": a card's price line. */
export function cardPrice(plan: { priceCents: number; currency: string; interval: 'month' | null }): string {
  return plan.interval ? `${formatPrice(plan)} / ${plan.interval}` : formatPrice(plan);
}
