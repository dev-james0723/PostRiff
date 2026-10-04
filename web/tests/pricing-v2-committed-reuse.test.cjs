const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const SRC = path.resolve(__dirname, '../src');
const BASE = process.env.TASK7_BASE_SOURCE_ROOT ?? SRC;
const read = (relative) => fs.readFileSync(path.join(SRC, relative), 'utf8');

// Actual candidate modules; pure presentation/auth/motion substitutes. No transport loaded.
function load(relative, overrides = {}, cache = new Map()) {
  const local = path.join(SRC, relative);
  const file = fs.existsSync(local) ? local : path.join(BASE, relative);
  if (cache.has(file)) return cache.get(file).exports;
  const mod = { exports: {} }; cache.set(file, mod);
  const compiled = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2023, jsx: ts.JsxEmit.ReactJSX }
  }).outputText;
  const localRequire = (name) => {
    if (name in overrides) return overrides[name];
    if (name.startsWith('@/') || name.startsWith('.')) {
      const stem = name.startsWith('@/') ? name.slice(2) : path.join(path.dirname(relative), name);
      for (const suffix of ['.ts', '.tsx', '/index.ts'])
        if (fs.existsSync(path.join(SRC, stem + suffix)) || fs.existsSync(path.join(BASE, stem + suffix))) return load(stem + suffix, overrides, cache);
      throw new Error('Missing local source ' + name);
    }
    return require(name);
  };
  new Function('require', 'module', 'exports', compiled)(localRequire, mod, mod.exports);
  return mod.exports;
}
const frame = ({ children }) => React.createElement('div', null, children);
const presentation = {
  'next/link': { default: ({ href, children }) => React.createElement('a', { href }, children) },
  '@/components/icons': { Icons: new Proxy({}, { get: () => () => null }) },
  '@/components/rafii': { Surface: frame, PageHeader: frame, StateMessage: frame },
  '@/components/ui/button': { buttonVariants: () => '' },
  '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') }
};

test('client checkout/status changes cannot acquire public purchase authority', () => {
  const model = load('config/plans.ts'); const [free, , creator] = model.v2PlanCards();
  for (const checkout of ['not_yet_available', 'available', 'legacy_flow']) {
    const action = model.v2CardAction({ ...creator, checkout }, '/auth/sign-up');
    assert.equal(action.label, 'Creator unavailable'); assert.equal(action.href, null);
    assert.match(action.note, /propos|validat/i); assert.match(action.note, /not available for purchase/i);
  }
  assert.equal(model.v2CardAction(free, '/auth/sign-up').href, '/auth/sign-up');
  const forged = { ...model.V2_CATALOG, plans: model.V2_CATALOG.plans.map((p) => ({ ...p, checkout: 'available' })) };
  assert.deepEqual(model.jsonLdOffers('v2', forged).map((x) => [x.name, x.price]), [['Free', '0.00']]);
  assert.doesNotMatch(JSON.stringify(model.jsonLdOffers('v2', forged)), /Creator|InStock|PreOrder|validFrom|availability/);
});

test('public selector always lists the four approved public packages with no forged identities', () => {
  const model = load('config/plans.ts');
  for (const value of [undefined, '', 'true', 'legacy']) assert.equal(model.pricingCatalogId(value), 'v2');
  assert.equal(model.pricingCatalogId('v2'), 'v2');
  assert.deepEqual(model.v2PlanCards().map((p) => [p.plan, p.priceCents]), [['free', 0], ['starter', 2900], ['creator', 5900], ['studio', 14900]]);
  assert.equal(model.catalogLimit(model.catalogPlan('creator'), 'monthlyCredits'), 3500);
  const injected = { ...model.V2_CATALOG, plans: [...model.V2_CATALOG.plans, ...['starter', 'studio', 'assist', 'trial'].map((p) => ({ ...model.catalogPlan('creator'), id: 'forged-legacy', plan: p }))] };
  assert.deepEqual(model.v2PlanCards(injected).map((p) => p.plan), ['free', 'starter', 'creator', 'studio']);
  assert.deepEqual(model.plans.map((p) => p.priceCents), [1900, 3900]);
});

test('illustration uses draft outcomes under either selector, never a made-up quota/wallet', () => {
  const { marketingCopy } = load('config/pricing-copy.ts');
  for (const catalog of ['legacy', 'v2']) assert.deepEqual(marketingCopy(catalog).previewStat, ['Drafts ready', '3']);
  const source = read('components/marketing/landing/product-preview.tsx');
  assert.match(source, /figures are examples/); assert.match(source, /marketingCopy\(PRICING_CATALOG\)\.previewStat/);
});

test('v2 acquisition and beta copy stays Free/no-card/proposed across five entry surfaces', () => {
  const { marketingCopy } = load('config/pricing-copy.ts'); const v2 = marketingCopy('v2'), legacy = marketingCopy('legacy');
  assert.deepEqual([v2.headerCta, v2.hero.primaryLabel, v2.ctaBand.primaryLabel], ['Start free', 'Start free', 'Start free']);
  assert.equal(v2.signUp.showPlanChooser, false); assert.equal(v2.signUp.chooser, null);
  const sales = JSON.stringify({ ...v2, terms: undefined, docs: undefined });
  assert.doesNotMatch(sales, /14.day|free trial|after trial|writing batch|Studio Assist|\$(?:19|39)\b|paid beta/i);
  assert.match(v2.pricingFootnote, /proposed/i); assert.match(v2.pricingFootnote, /not available for purchase/i);
  assert.match(sales, /when available|eligib/i); assert.match(v2.ctaBand.note, /No card/i);
  assert.equal(legacy.signUp.showPlanChooser, false); assert.equal(legacy.headerCta, 'Start free');
  for (const relative of ['components/marketing/site-header.tsx', 'components/marketing/mobile-nav.tsx', 'components/marketing/landing/hero.tsx', 'components/marketing/cta-band.tsx', 'app/(marketing)/channels/[slug]/page.tsx']) {
    assert.match(read(relative), /siteConfig\.links\.signUp/, relative);
    assert.match(read(relative), /marketingCopy|signUpLabel|COPY|copy\./, relative);
  }
});

function authScene(intent, catalog, query = 'plan=creator&next=/invite/synthetic') {
  const writes = [], buttons = []; const { marketingCopy } = load('config/pricing-copy.ts');
  const overrides = { ...presentation,
    'next/navigation': { useRouter: () => ({ replace() {} }), useSearchParams: () => new URLSearchParams(query) },
    '@/lib/auth/session': { useAuth: () => ({ status: 'signed-out', mode: 'dev' }), devSignIn() {} },
    '@/lib/auth/passkeys': { passkeySignInEnabled: () => false }, '@/lib/auth/mfa': { passkeysSupported: () => false },
    '@/lib/workspace/provider': { selectedPlan: () => 'assist', rememberPlan: (value) => writes.push(value) },
    '@/components/ui/button': { Button: (props) => { buttons.push(props); return React.createElement('button', null, props.children); } },
    '@/components/ui/input': { Input: frame }, '@/components/ui/input-otp': { InputOTP: frame, InputOTPGroup: frame, InputOTPSlot: frame },
    '@/components/ui/label': { Label: frame }, '@/components/ui/radio-group': { RadioGroup: frame, RadioGroupItem: frame }
  };
  const { AuthForm } = load('components/auth/auth-form.tsx', overrides);
  const html = renderToStaticMarkup(React.createElement(AuthForm, { intent, signUp: marketingCopy(catalog).signUp }));
  return { writes, buttons, html };
}
test('v2 signup ignores paid/legacy URL choices and remembers only the Free transport hint', () => {
  for (const plan of ['creator', 'assist', 'studio', 'free']) {
    const scene = authScene('sign-up', 'v2', 'plan=' + plan);
    scene.buttons.find((p) => p.children === 'Enter dev workspace').onClick();
    assert.deepEqual(scene.writes, ['free']); assert.doesNotMatch(scene.html, /Trial plan|Studio Assist|after trial/);
  }
});
test('sign-in preserves subscriber plan hints; signup remains Free under legacy selector', () => {
  for (const catalog of ['legacy', 'v2']) {
    const scene = authScene('sign-in', catalog); scene.buttons.find((p) => p.children === 'Enter dev workspace').onClick();
    assert.deepEqual(scene.writes, []);
  }
  const signup = authScene('sign-up', 'legacy', 'next=/app');
  assert.doesNotMatch(signup.html, /Trial plan|Studio Assist/);
  signup.buttons.find((p) => p.children === 'Enter dev workspace').onClick();
  assert.deepEqual(signup.writes, ['free']);
});

function chromaticScene(reduce, hydrated, inView = false) {
  const effects = [], updates = []; let motion;
  const fakeReact = { ...React, useRef: () => ({ current: null }), useState: (value) => [typeof value === 'boolean' ? hydrated : value, (next) => updates.push(next)], useCallback: (fn) => fn, useEffect: (fn) => effects.push(fn) };
  function MotionSpan(props) { return React.createElement('span', { style: { ...props.initial, ...props.style } }, props.children); }
  const { ChromaticTextReveal } = load('components/motion/chromatic-text-reveal.tsx', { react: fakeReact, 'motion/react': { motion: { span: MotionSpan }, useReducedMotion: () => reduce, useInView: () => inView }, '@/lib/utils': presentation['@/lib/utils'] });
  const element = ChromaticTextReveal({ prefix: 'In your', words: ['voice', 'rhythm'], duration: 1.2, delay: 0.3, pauseDuration: 1.8 });
  function visit(node) { if (!node || typeof node !== 'object') return; if (node.type === MotionSpan) motion = node.props; React.Children.forEach(node.props?.children, visit); }
  visit(element); return { motion, html: renderToStaticMarkup(element), effects, updates };
}
test('Chromatic SSR and first reduced client frame stay deterministic until hydration', () => {
  const server = chromaticScene(false, false), client = chromaticScene(true, false);
  assert.equal(client.html, server.html); assert.deepEqual(client.motion.initial, server.motion.initial);
  assert.equal(client.motion.style['--chromatic-sweep'], '-14%'); assert.equal(client.motion.animate['--chromatic-sweep'], '-14%');
  client.effects.forEach((fn) => fn()); assert.ok(client.updates.includes(true));
});
test('reduced motion finishes after hydration without cycling; normal timing remains', () => {
  const reduced = chromaticScene(true, true);
  assert.equal(reduced.motion.animate['--chromatic-sweep'], '114%'); assert.equal(reduced.motion.animate.opacity, 1);
  assert.equal(reduced.motion.animate.filter, 'blur(0px)'); assert.deepEqual(reduced.motion.transition['--chromatic-sweep'], { duration: 0 });
  const calls = []; global.window = { setTimeout: (fn, delay) => { calls.push(delay); return 1; }, clearTimeout() {} };
  try { reduced.motion.onAnimationComplete(); assert.deepEqual(calls, []);
    const normal = chromaticScene(false, true, true); assert.equal(normal.motion.transition['--chromatic-sweep'].duration, 1.2);
    assert.equal(normal.motion.transition['--chromatic-sweep'].delay, 0.3); normal.motion.onAnimationComplete(); assert.deepEqual(calls, [1800]);
  } finally { delete global.window; }
});
// Matching-base byte preservation is checked without narrowing in ledger/public-type-invariance.test.cjs.

test('credit FAQ never treats an unknown final cost as zero or released', () => {
  const faq = load('config/pricing-copy.ts').marketingCopy('v2').pricingFaq.find((item) => item.q === 'What are managed credits?').a;
  assert.match(faq, /300 credits equal US\$1/);
  assert.match(faq, /rounded once per task/);
  assert.match(faq, /unknown cost stays held until confirmed/i);
  assert.match(faq, /failed task uses no credits/);
  assert.match(faq, /unused credits don’t roll over/);
});

function renderScene(catalog) {
  // Load the actual selector, including functions whose defaults close over it.
  const previous = process.env.NEXT_PUBLIC_PRICING_CATALOG;
  let model;
  try {
    if (catalog === undefined) delete process.env.NEXT_PUBLIC_PRICING_CATALOG;
    else process.env.NEXT_PUBLIC_PRICING_CATALOG = catalog;
    model = load('config/plans.ts');
  } finally {
    if (previous === undefined) delete process.env.NEXT_PUBLIC_PRICING_CATALOG;
    else process.env.NEXT_PUBLIC_PRICING_CATALOG = previous;
  }
  const copy = load('config/pricing-copy.ts', { './plans': model });
  const heading = ({ title, accent, description, children, id }) => React.createElement('section', { id },
    React.createElement('h2', null, title, ' ', accent), React.createElement('p', null, description), children);
  const table = Object.fromEntries(['Table', 'TableBody', 'TableCell', 'TableHead', 'TableHeader', 'TableRow'].map((name, i) =>
    [name, ({ children, className }) => React.createElement(['table', 'tbody', 'td', 'th', 'thead', 'tr'][i], { className }, children)]));
  const channel = { slug: 'linkedin', name: 'LinkedIn', group: 'hosted', capability: 'assisted', description: 'Synthetic connector fixture',
    reviewStatus: 'Review pending', formats: ['Text'], capabilities: { identity: 'Assisted', publish: 'Assisted' } };
  const overrides = { ...presentation,
    '@/config/plans': model, '@/config/pricing-copy': copy,
    '@/config/channels': { channels: [channel], hostedChannels: [channel], localChannels: [], channelBySlug: (slug) => slug === channel.slug ? channel : undefined },
    'next/navigation': { notFound: () => { throw new Error('Synthetic channel not found'); } },
    '@/components/marketing/page-hero': { PageHero: heading },
    '@/components/marketing/section': { Section: heading, Container: frame },
    '@/components/marketing/capability-badge': { CapabilityBadge: () => null },
    '@/components/channel-icon': { ChannelIcon: () => null },
    '@/components/themes/theme-mode-toggle': { ThemeModeToggle: () => null },
    './wordmark': { Wordmark: () => null }, '@/components/ui/table': table,
    '@/components/ui/button': { buttonVariants: () => '', Button: ({ children }) => React.createElement('button', null, children) },
    '@/components/ui/sheet': Object.fromEntries(['Sheet', 'SheetContent', 'SheetDescription', 'SheetHeader', 'SheetTitle', 'SheetTrigger'].map((name) => [name, frame])),
    '@/components/motion/magnetic': { Magnetic: frame }, '@/components/motion/tilt-card': { TiltCard: frame },
    '@/components/motion/scroll-reveal': { ScrollReveal: frame }, '@/components/motion/marquee': { Marquee: frame },
    '@/components/motion/chromatic-text-reveal': { ChromaticTextReveal: ({ prefix, words }) => React.createElement('span', null, prefix, words[0]) },
    '@/components/ui/learn-more-chevron': { LearnMoreChevron: () => null },
    '@/components/motion/bouncy-accordion': { BouncyAccordion: ({ items }) => React.createElement('div', null,
      items.map((item) => React.createElement('details', { key: item.id, open: true }, React.createElement('summary', null, item.title), React.createElement('p', null, item.description)))) }
  };
  const cache = new Map();
  return { module: (relative) => load(relative, overrides, cache), markup: (Component, props) => renderToStaticMarkup(React.createElement(Component, props)) };
}

test('rendered header/menu, hero, CTA and channel all route selected v2 acquisition to Free', async () => {
  const scene = renderScene('v2');
  const entry = [
    scene.markup(scene.module('components/marketing/site-header.tsx').SiteHeader),
    scene.markup(scene.module('components/marketing/landing/hero.tsx').Hero),
    scene.markup(scene.module('components/marketing/cta-band.tsx').CtaBand),
    renderToStaticMarkup(await scene.module('app/(marketing)/channels/[slug]/page.tsx').default({ params: Promise.resolve({ slug: 'linkedin' }) }))
  ];
  for (const html of entry) {
    assert.match(html, /href="\/auth\/sign-up"[^>]*>Start free<\/a>/);
    assert.doesNotMatch(html, /14.day|free trial|\$(?:19|39)\b|plan=(?:studio|assist|creator)/i);
  }
  assert.equal((entry[0].match(/href="\/auth\/sign-up"[^>]*>Start free<\/a>/g) ?? []).length, 2, 'desktop header and synthetic menu use the same Free path');
  assert.match(entry[0], /href="\/auth\/sign-in"/);
});

test('rendered pricing and landing cards show all four approved plans; JSON-LD only Free', () => {
  const scene = renderScene('v2');
  const pricing = scene.markup(scene.module('app/(marketing)/pricing/page.tsx').default);
  const landing = scene.markup(scene.module('components/marketing/landing/sections.tsx').PricingSummary);
  for (const html of [pricing, landing]) {
    assert.equal((html.match(/<h3\b/g) ?? []).length, 4);
    assert.match(html, /Free/); assert.match(html, /Creator/); assert.match(html, /\$59/);
    assert.match(html, /Starter/); assert.match(html, /\$29/); assert.match(html, /1,000/);
    assert.match(html, /Studio/); assert.match(html, /\$149/); assert.match(html, /8,000/); assert.match(html, /3,500 managed AI credits/);
    assert.match(html, /not available for purchase/); assert.match(html, /when available/);
    assert.doesNotMatch(html, /14.day|free trial|\$(?:19|39)\b|Studio Assist|writing batch|Get Creator/i);
    assert.doesNotMatch(html, /sign-up\?(?:plan|next)=/);
  }
  const json = scene.module('components/marketing/json-ld.tsx').JsonLd().props.dangerouslySetInnerHTML.__html;
  assert.deepEqual(JSON.parse(json)[1].offers.map((offer) => [offer.name, offer.price]), [['Free', '0.00']]);
  assert.doesNotMatch(json, /Creator|InStock|PreOrder|availability|validFrom/);
});

test('rendered explicit legacy rollback keeps Free and unavailable Creator, with truthful outcome preview', async () => {
  const scene = renderScene('legacy');
  const html = scene.markup(scene.module('app/(marketing)/pricing/page.tsx').default);
  assert.match(html, /Free/); assert.match(html, /\$59/); assert.match(html, /Creator unavailable/);
  assert.doesNotMatch(html, /Studio Assist|\$(?:19|39)\b|14.day trial/);
  const header = scene.markup(scene.module('components/marketing/site-header.tsx').SiteHeader);
  assert.match(header, /href="\/auth\/sign-up"[^>]*>Start free<\/a>/);
  const json = scene.module('components/marketing/json-ld.tsx').JsonLd().props.dangerouslySetInnerHTML.__html;
  assert.deepEqual(JSON.parse(json)[1].offers.map((offer) => [offer.name, offer.price]), [['Free', '0.00']]);
  for (const selector of ['legacy', 'v2']) {
    const own = renderScene(selector);
    const preview = own.markup(own.module('components/marketing/landing/product-preview.tsx').ProductPreview);
    assert.match(preview, /Drafts ready<\/p><p[^>]*>3<\/p>/); assert.match(preview, /figures are examples/);
    assert.doesNotMatch(preview, /Writing batches|Credits left|2,140/);
  }
});

test('authority: default and explicit legacy public selectors always present Free and Creator', () => {
  for (const selector of [undefined, '', 'legacy', 'v2', 'false', 'off', 'typo']) {
    const model = load('config/plans.ts');
    assert.equal(model.pricingCatalogId(selector), 'v2');
    const copy = load('config/pricing-copy.ts').marketingCopy(selector);
    assert.equal(copy.catalog, 'v2'); assert.equal(copy.signUp.showPlanChooser, false);
    assert.equal(copy.headerCta, 'Start free');
    assert.doesNotMatch(JSON.stringify({ ...copy, terms: undefined, docs: undefined }), /14.day|free trial|writing batch|Studio Assist|\$(?:19|39)\b/i);
  }
});
test('authority: runtime flags OFF or ON alone never restore legacy public sales or authorize Creator', () => {
  for (const flag of ['0', '1']) for (const selector of ['legacy', 'v2', undefined]) {
    process.env.POSTRIFF_PRICING_V2_ENABLED = flag;
    const scene = renderScene(selector);
    const html = scene.markup(scene.module('app/(marketing)/pricing/page.tsx').default);
    assert.match(html, /Free/); assert.match(html, /Creator/); assert.match(html, /\$59/);
    assert.match(html, /Starter/); assert.match(html, /\$29/); assert.match(html, /1,000/);
    assert.match(html, /Studio/); assert.match(html, /\$149/); assert.match(html, /8,000/); assert.match(html, /3,500/);
    assert.doesNotMatch(html, /Studio Assist|\$(?:19|39)\b|14.day|free trial|Get Creator/i);
    assert.match(html, /Creator unavailable/);
    assert.match(html, /<button[^>]*disabled/);
  }
  process.env.POSTRIFF_PRICING_V2_ENABLED = '0';
});
test('authority: Creator waits for explicit qualified catalog checkout; a status string alone is insufficient', () => {
  const model = load('config/plans.ts'); const [, , creator] = model.v2PlanCards();
  for (const qualified of [undefined, false]) {
    const action = model.v2CardAction({ ...creator, checkout: 'available', checkoutAvailable: qualified }, '/auth/sign-up');
    assert.equal(action.label, 'Creator unavailable'); assert.equal(action.href, null);
  }
  const enabled = model.v2CardAction({ ...creator, checkout: 'available', checkoutAvailable: true }, '/auth/sign-up');
  assert.equal(enabled.label, 'Get Creator'); assert.equal(enabled.href, '/auth/sign-up?next=%2Fapp%2Faccount%2Fbilling%23plans');
  const inconsistent = model.v2CardAction({ ...creator, checkout: 'not_yet_available', checkoutAvailable: true }, '/auth/sign-up');
  assert.equal(inconsistent.href, null);
});
test('authority: JSON-LD never reintroduces a legacy paid offer; qualified Creator is explicit', () => {
  const model = load('config/plans.ts');
  for (const selector of ['legacy', 'v2', undefined]) assert.deepEqual(model.jsonLdOffers(selector).map((p) => [p.name, p.price]), [['Free', '0.00']]);
  const qualified = { ...model.V2_CATALOG, plans: model.V2_CATALOG.plans.map((p) => p.plan === 'creator' ? { ...p, checkout: 'available', checkoutAvailable: true } : p) };
  assert.deepEqual(model.jsonLdOffers('v2', qualified).map((p) => [p.name, p.price]), [['Free', '0.00'], ['Creator', '59.00']]);
});
test('authority: direct legacy public card rendering cannot create an old-price trial CTA', () => {
  const scene = renderScene('legacy'); const cards = scene.module('components/marketing/plan-card.tsx');
  const model = load('config/plans.ts');
  for (const plan of model.plans) assert.equal(scene.markup(cards.PlanCard, { plan }), '');
});

test('quantity: malformed or unknown paid monthly credits never become zero or an entitlement fallback', () => {
  const model = load('config/plans.ts'); const copy = load('config/pricing-copy.ts');
  const scene = renderScene('v2'); const { V2PlanCardView } = scene.module('components/marketing/plan-card.tsx');
  for (const monthlyCredits of [null, undefined, true, false, '3500', -1, {}, 1.5, Number.MAX_SAFE_INTEGER + 1, NaN, Infinity]) {
    const catalog = { ...model.V2_CATALOG, plans: model.V2_CATALOG.plans.map((plan) => plan.plan === 'creator'
      ? { ...plan, monthlyCredits, checkout: 'available', checkoutAvailable: true } : plan) };
    const creator = model.catalogPlan('creator', catalog);
    assert.equal(model.catalogLimit(creator, 'monthlyCredits'), null, String(monthlyCredits));
    const card = model.v2PlanCards(catalog).find((plan) => plan.plan === 'creator');
    assert.ok(card.highlights.includes('Managed credit allowance unavailable'));
    assert.doesNotMatch(JSON.stringify(card.highlights), /3,500|\b0 managed|NaN|Infinity|\[object Object\]/);
    assert.equal(model.v2CardAction(card, '/auth/sign-up').href, null);
    assert.equal(copy.v2CompareRows(catalog).find((row) => row.label === 'Managed AI credits').values[2], 'Unavailable');
    assert.deepEqual(model.jsonLdOffers('v2', catalog).map((offer) => offer.name), ['Free']);
    const html = scene.markup(V2PlanCardView, { card });
    assert.match(html, /Managed credit allowance unavailable/);
    assert.match(html, /<button[^>]*disabled[^>]*>Creator unavailable<\/button>/);
    assert.doesNotMatch(html, /Get Creator|3,500|\b0 managed|NaN|Infinity|\[object Object\]/);
    const words = copy.marketingCopy('v2', catalog);
    assert.match(words.pricingFaq.find((item) => item.q === 'What does Creator add?').a, /Managed credit allowance unavailable/);
    for (const text of [words.pricingMeta.description, words.landingPricing.description, words.terms.paragraph, ...words.docs.usageSections.find((item) => item.heading === 'Managed credits').paragraphs]) {
      assert.match(text, /allowance.*unavailable|unknown cost/i);
      assert.doesNotMatch(text, /3,500|\b0 managed|(?:null|undefined|NaN|Infinity) managed|\[object Object\]/);
    }
  }
});
test('quantity: normal seeded Free0 and Creator3500 remain unchanged', () => {
  const model = load('config/plans.ts');
  assert.equal(model.catalogLimit(model.catalogPlan('free'), 'monthlyCredits'), 0);
  assert.equal(model.catalogLimit(model.catalogPlan('creator'), 'monthlyCredits'), 3500);
  assert.ok(model.v2PlanCards().find(p => p.id === 'creator-v1').highlights.includes('3,500 managed AI credits every month'));
});


test('help: actual getting-started document begins on Free without a new trial', () => {
  const docs = load('content/docs.ts').DOCS;
  const intro = docs.find((doc) => doc.slug === 'getting-started').sections[0].paragraphs.join(' ');
  assert.match(intro, /on Free/);
  assert.doesNotMatch(intro, /choose a trial|14.day|\$(?:19|39)\b/i);
});

test('help: actual billing document explains MAX and held unknown cost with truthful earlier plans', () => {
  const doc = load('content/docs.ts').DOCS.find((item) => item.slug === 'usage-and-billing');
  const current = doc.sections.filter((item) => item.heading !== 'Earlier plans');
  const copy = JSON.stringify(current);
  assert.match(copy, /3,500 managed credits/);
  assert.match(copy, /300 credits equal US\$1/);
  assert.match(copy, /credit limit/); assert.match(copy, /unknown cost stays held/);
  assert.doesNotMatch(copy, /Writing batches|media credits|14 days/);
  assert.match(JSON.stringify(doc.sections.find((item) => item.heading === 'Earlier plans')), /keep their plan.*trial.*ends.*Free/i);
});
