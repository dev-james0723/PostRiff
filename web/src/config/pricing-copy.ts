/**
 * Every public sentence about plans and pricing, for both catalogs (spec §13.1–13.2; PRD R-COM-04).
 *
 * All public selector values present Free and proposed Creator: outcomes first, credits explained once,
 * a beta price still being validated, and no trial, writing batches or legacy prices.
 * Numbers come from the committed catalog fixture. Neither copy nor a public selector activates
 * paid work. Rollback is unavailable/waitlist, never legacy new sales. The preview uses draft outcomes.
 */
import { PRICING_CATALOG, V2_CATALOG, catalogLimit, catalogPlan, countText, formatPrice, usdText, type CatalogPlan, type PricingCatalogId, type PublicCatalog } from './plans';

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
  /** A product outcome in the illustrative frame, never a quota or wallet balance. */
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

/* ---------- v2: Free and Creator ---------- */

function required(plan: CatalogPlan | undefined, name: string): CatalogPlan {
  // A catalog without the plan the copy describes must fail the build, never print a wrong price.
  if (!plan) throw new Error(`The v2 catalog has no ${name} plan.`);
  return plan;
}

const WORDS = ['no', 'one', 'two', 'three', 'four', 'five', 'six', 'seven', 'eight', 'nine', 'ten'];
const word = (value: number) => WORDS[value] ?? countText(value);

function v2Numbers(catalog: PublicCatalog) {
  const free = required(catalogPlan('free', catalog), 'Free');
  const creator = required(catalogPlan('creator', catalog), 'Creator');
  const first = free.firstValue ?? { postDoctorRuns: 1, genomeAnalyses: 1, genomeMaxPosts: 20 };
  const credits = catalogLimit(creator, 'monthlyCredits');
  return {
    free,
    creator,
    first,
    price: usdText(creator.priceCents),
    credits: credits === null ? null : countText(credits),
    perUsd: catalog.creditsPerUsd ?? 300,
    freeAccounts: catalogLimit(free, 'connectedAccounts') ?? 1
  };
}

/** The comparison table under the v2 cards: one column per plan for sale, in catalog order. */
export function v2CompareRows(catalog: PublicCatalog = V2_CATALOG): { label: string; values: string[] }[] {
  const columns = catalog.plans.filter((plan) => plan.plan === 'free' || plan.plan === 'creator');
  const limit = (plan: CatalogPlan, key: string) => {
    const value = catalogLimit(plan, key);
    if (value === null) return '—';
    return value > 1 ? `Up to ${countText(value)}` : countText(value);
  };
  const row = (label: string, value: (plan: CatalogPlan) => string) => ({ label, values: columns.map(value) });
  return [
    row('Managed AI credits', (plan) => {
      const credits = catalogLimit(plan, 'monthlyCredits');
      return credits === null ? 'Unavailable' : credits > 0 ? `${countText(credits)} / month` : 'None';
    }),
    row('Connected accounts', (plan) => limit(plan, 'connectedAccounts')),
    row('Brands', (plan) => limit(plan, 'brands')),
    row('Seats', (plan) => {
      const seats = catalogLimit(plan, 'members');
      return seats === null ? '—' : countText(seats);
    }),
    row('Credit rollover', (plan) => {
      const credits = catalogLimit(plan, 'monthlyCredits');
      return credits === null ? 'Unavailable' : credits > 0 ? 'None — credits reset each period' : '—';
    }),
    row('Overage behaviour', () => 'Stops — never charged silently'),
    row('Export everything', () => 'Always'),
    row('Account deletion', () => 'Self-service')
  ];
}

function v2Copy(catalog: PublicCatalog): MarketingCopy {
  const { creator, first, price, credits, perUsd, freeAccounts } = v2Numbers(catalog);
  const creditDescription = credits === null ? 'a managed credit allowance that is currently unavailable' : `${credits} managed credits`;
  const creditSummary = credits === null ? 'Managed credit allowance unavailable.' : `${credits} managed AI credits every month for the work Rafii runs for you, like drafting and rewriting in your voice.`;
  const creatorAccounts = catalogLimit(creator, 'connectedAccounts');
  const creatorBrands = catalogLimit(creator, 'brands');
  const firstLook = `one Post Doctor check and one analysis of up to ${countText(first.genomeMaxPosts)} recent posts, when available for eligible workspaces`;
  return {
    catalog: 'v2',
    pricingMeta: { description: `Start free, no card. Proposed Creator is ${price} a month with ${creditDescription} and is not available for purchase. Paid work stops at your limit — never a surprise charge.` },
    pricingHero: {
      eyebrow: 'Pricing',
      title: 'Start free.',
      accent: 'Upgrade when it’s worth it.',
      description: `Start free with no card. Preview Rafii on your own writing with ${firstLook}. Proposed Creator would add managed AI work every month.`
    },
    pricingFootnote: 'Prices are shown in USD. Creator is proposed; its beta price is still being validated and it is not available for purchase.',
    pricingFaq: [
      {
        q: 'What can I do on Free?',
        a: `Save your sources and drafts, edit, approve and export them, and see Rafii work on your own writing: ${firstLook}, on us. Free has no monthly AI credits, so it never charges you.`
      },
      {
        q: 'What does Creator add?',
        a: `${creditSummary}${creatorAccounts && creatorBrands ? ` Up to ${countText(creatorAccounts)} connected accounts and ${countText(creatorBrands)} brands.` : ''} Each task shows its credit limit before it runs.`
      },
      {
        q: 'What are managed credits?',
        a: `Credits pay for the AI and data work Rafii runs for you on Creator: ${perUsd} credits equal US$1 of a task’s verified model and tool cost, rounded once per task. You see each task’s credit limit before it runs; Rafii holds it, charges what the task used and returns the rest, and a failed task uses no credits. Unknown cost stays held until confirmed. When credits run out, paid work stops and nothing is charged silently. Credits reset each billing period; unused credits don’t roll over.`
      },
      {
        q: 'Is the Creator price final?',
        a: 'Creator is proposed, its beta price is still being validated, and it is not available for purchase. If paid subscriptions are enabled later, the price shown at checkout is the price you pay, with at least 30 days’ notice by email before a renewal price changes.'
      },
      { q: 'When am I billed?', a: 'If paid subscriptions are enabled, monthly in advance from the day you subscribe to Creator. Free never asks for a card and never converts automatically.' },
      { q: 'Can I cancel any time?', a: 'Yes, from the billing portal. Creator runs to the end of the paid period; then the workspace returns to Free, and your drafts stay readable and exportable.' },
      { q: 'I subscribed before Creator. What changes?', a: 'Nothing, unless you choose to. Earlier plans keep their price and what they include, and Usage & plan keeps showing them.' },
      { q: 'Refunds?', a: 'See the Terms of Service. Free never charges you, so you can see Rafii work before paying.' },
      { q: 'Taxes?', a: 'Shown at checkout where applicable, based on your billing address.' }
    ],
    landingPricing: {
      title: 'Start free.',
      accent: 'No surprises.',
      description: `Start free with no card. Proposed Creator is ${price} a month with ${creditDescription} and is not available for purchase. Paid work stops at your limit.`,
      compareLink: 'Compare plans in detail'
    },
    landingFaqItem: {
      q: 'What does Free include?',
      a: `${firstLook.charAt(0).toUpperCase()}${firstLook.slice(1)}, on us, with ${word(freeAccounts)} connected account${freeAccounts === 1 ? '' : 's'} and no card. Drafts, edits and exports stay available, and Free never charges you.`
    },
    ctaBand: {
      description: `Start free with ${word(freeAccounts)} connected account${freeAccounts === 1 ? '' : 's'} — no card. Draft, edit and export your work, any time.`,
      primaryLabel: 'Start free',
      note: 'No card required. No automatic paid conversion.'
    },
    hero: { primaryLabel: 'Start free', note: 'No credit card · Free to start · Export everything, any time' },
    headerCta: 'Start free',
    previewStat: ['Drafts ready', '3'],
    terms: {
      title: 'Free plan, subscriptions and billing',
      paragraph: `New workspaces start on Free. No payment method is required; Free includes ${firstLook} and has no monthly managed credits. Creator is a proposed monthly subscription with ${creditDescription}${credits === null ? '' : ' per billing period'}. Credits pay for the AI and data work Rafii runs for you: ${perUsd} credits correspond to US$1 of the verified cost of a task, rounded once per task, and a task’s credit limit is shown and held before it runs. Credits expire at the end of each billing period and do not roll over. Paid plans remain proposed until commercial approval and payment verification are complete. If enabled, they are billed monthly in advance through Stripe at the price shown when you subscribe. Paid work stops when credits are used up; there is no automatic overage charge. You can cancel at any time from the billing portal; access to paid features continues until the end of the paid period, after which the workspace returns to Free and your drafts stay readable and exportable. Workspaces that subscribed under an earlier plan keep that plan and its price until they change it, and a trial that is already running continues until it ends. We may change prices with at least 30 days’ notice by email; a change applies from your next renewal. [Refund policy — to be confirmed by counsel.] Taxes are shown at checkout where applicable.`
    },
    signUp: {
      metaTitle: 'Start free',
      metaDescription: 'Create a Rafii workspace. Free to start, no card required.',
      subtitle: 'Start free. No card needed.',
      switchLabel: 'Start free',
      showPlanChooser: false,
      chooser: null,
      promise: ['Save, edit and export your own writing.', 'Connect your account when you’re ready.', 'No card required. No automatic paid conversion.']
    },
    docs: {
      gettingStartedCreate: 'Sign up with Google or an email code. A workspace is created for you on Free; you are its owner.',
      usageSummary: 'Free, managed credits, limits and how plans work.',
      usageSections: [
        { heading: 'Free', paragraphs: [`Free has no monthly managed credits and never charges you. It includes ${firstLook}, plus saving, editing, approving and exporting your work.`] },
        {
          heading: 'Managed credits',
          paragraphs: [
            `Creator has ${creditDescription}${credits === null ? '' : ' each billing period'}. ${perUsd} credits equal US$1 of the verified model and tool cost of a task, rounded once per task.`,
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
export function marketingCopy(catalog: PricingCatalogId = PRICING_CATALOG, projection: PublicCatalog = V2_CATALOG): MarketingCopy {
  void catalog;
  return v2Copy(projection);
}

/** "$59 / month", "$0": a card's price line. */
export function cardPrice(plan: { priceCents: number; currency: string; interval: 'month' | null }): string {
  return plan.interval ? `${formatPrice(plan)} / ${plan.interval}` : formatPrice(plan);
}
