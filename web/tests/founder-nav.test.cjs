/**
 * Founder navigation (CONTRACTS §6, PRD §5.1): the Overview plus eight sections, hrefs that keep the data mode, the
 * phone tab bar, breadcrumbs without record ids, and the `/control/*` redirect map mirrored in next.config.ts.
 *
 *   node --test web/tests/founder-nav.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const ROOT = path.join(__dirname, '..');

function load(file) {
  const { outputText } = ts.transpileModule(fs.readFileSync(file, 'utf8'), { fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const nav = load(path.join(ROOT, 'src', 'config', 'founder-nav.ts'));
const sections = load(path.join(ROOT, 'src', 'features', 'founder', 'sections.ts'));

test('the Overview and the eight PRD sections exist, each with a route, icon, question and tabs', () => {
  assert.deepEqual([...nav.FOUNDER_SECTION_IDS], ['overview', 'customers', 'revenue', 'product', 'ai-cost', 'operations', 'support', 'settings', 'advanced']);
  for (const id of nav.FOUNDER_SECTION_IDS) {
    const section = nav.FOUNDER_SECTIONS[id];
    assert.equal(section.id, id);
    assert.equal(section.url, id === 'overview' ? '/founder' : `/founder/${id}`);
    assert.ok(section.title && section.icon && section.question, id);
    assert.ok(Array.isArray(section.tabs) && section.tabs.length > 0, id);
  }
  assert.equal(nav.FOUNDER_SECTIONS.revenue.title, 'Revenue & billing');
  assert.equal(nav.FOUNDER_SECTIONS['ai-cost'].title, 'AI & API cost');
});

test('every section appears in exactly one sidebar group, and the registry covers the routed ones', () => {
  const grouped = nav.FOUNDER_NAV_GROUPS.flatMap((group) => group.items);
  assert.deepEqual([...grouped].sort(), [...nav.FOUNDER_SECTION_IDS].sort());
  assert.deepEqual([...sections.FOUNDER_SECTIONS].sort(), nav.FOUNDER_SECTION_IDS.filter((id) => id !== 'overview').sort());
  for (const id of sections.FOUNDER_SECTIONS) assert.equal(typeof sections.SECTIONS[id], 'function', id);
});

test('routing helpers accept only real sections', () => {
  assert.ok(nav.isRoutedSectionId('ai-cost'));
  assert.ok(!nav.isRoutedSectionId('overview'));
  assert.ok(!nav.isRoutedSectionId('command'));
  assert.ok(!nav.isFounderSectionId('__proto__'));
  assert.equal(nav.sectionForPathname('/founder'), 'overview');
  assert.equal(nav.sectionForPathname('/founder/operations'), 'operations');
  assert.equal(nav.sectionForPathname('/founder/nowhere'), null);
  assert.ok(nav.isActiveFounderPath('/founder/customers', '/founder/customers'));
  assert.ok(!nav.isActiveFounderPath('/founder/customers', '/founder'));
});

test('founder links keep the Demo data mode and extra parameters; Live adds nothing', () => {
  assert.equal(nav.founderHref('customers'), '/founder/customers');
  assert.equal(nav.founderHref('customers', 'live'), '/founder/customers');
  assert.equal(nav.founderHref('customers', 'demo'), '/founder/customers?mode=demo');
  assert.equal(nav.founderHref('advanced', 'demo', { tab: 'data-health' }), '/founder/advanced?mode=demo&tab=data-health');
  assert.equal(nav.founderHref('overview', 'live', { record: 'customer-1', empty: '' }), '/founder?record=customer-1');
});

test('the phone tab bar is Overview, Customers, AI cost, Operations (Rafii is added by the bar)', () => {
  assert.deepEqual(nav.FOUNDER_TAB_BAR, ['overview', 'customers', 'ai-cost', 'operations']);
  assert.deepEqual(nav.FOUNDER_TAB_BAR.map((id) => nav.FOUNDER_SECTIONS[id].shortTitle), ['Overview', 'Customers', 'AI cost', 'Operations']);
});

test('breadcrumbs read Founder › Section and never a record id', () => {
  assert.deepEqual(nav.founderBreadcrumbs('/founder'), [{ title: 'Founder', link: '/founder' }]);
  assert.deepEqual(nav.founderBreadcrumbs('/founder/revenue'), [{ title: 'Founder', link: '/founder' }, { title: 'Revenue & billing', link: '/founder/revenue' }]);
  assert.deepEqual(nav.founderBreadcrumbs('/founder/customers?record=customer-1'), [{ title: 'Founder', link: '/founder' }, { title: 'Customers', link: '/founder/customers' }]);
});

test('the redirect map covers the preview routes and is mirrored verbatim in next.config.ts', () => {
  const bySource = Object.fromEntries(nav.FOUNDER_REDIRECTS.map((r) => [r.source, r.destination]));
  assert.equal(bySource['/control/command'], '/founder');
  assert.equal(bySource['/control/billing'], '/founder/revenue');
  assert.equal(bySource['/control/:section'], '/founder/:section');
  assert.equal(bySource['/control/connections'], '/founder/operations?tab=connections');
  assert.equal(bySource['/control/workspaces'], '/founder/customers?tab=workspaces');
  assert.equal(bySource['/founder/connections'], '/founder/operations?tab=connections');
  assert.equal(bySource['/founder/workspaces'], '/founder/customers?tab=workspaces');
  for (const r of nav.FOUNDER_REDIRECTS) assert.equal(r.permanent, false, r.source);
  // Specific sources come before the catch-all so `/control/billing` never lands on `/founder/billing`.
  const order = nav.FOUNDER_REDIRECTS.map((r) => r.source);
  assert.ok(order.indexOf('/control/billing') < order.indexOf('/control/:section'));
  assert.ok(order.indexOf('/control/connections') < order.indexOf('/control/:section'));

  const config = fs.readFileSync(path.join(ROOT, 'next.config.ts'), 'utf8');
  const block = config.slice(config.indexOf('const founderRedirects'), config.indexOf('];', config.indexOf('const founderRedirects')));
  const entries = [...block.matchAll(/\{\s*source:\s*'([^']+)',\s*destination:\s*'([^']+)',\s*permanent:\s*false\s*\}/g)].map((m) => ({ source: m[1], destination: m[2], permanent: false }));
  assert.deepEqual(entries, nav.FOUNDER_REDIRECTS, 'next.config.ts founderRedirects must equal FOUNDER_REDIRECTS, in order');
  assert.match(config, /async redirects\(\)\s*\{\s*return founderRedirects;/);
});
