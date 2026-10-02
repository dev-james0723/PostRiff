/* eslint-disable no-underscore-dangle -- Compile the actual source through Node Module's API. */
const { test } = require('node:test'); const assert = require('node:assert/strict');
const fs = require('node:fs'), path = require('node:path'), Module = require('node:module'), ts = require('typescript');
const React = require('react'), { renderToStaticMarkup } = require('react-dom/server');
function load(relative, mocks, expose = '') {
  const file = path.resolve(__dirname, '../src', relative), m = new Module(file); m.paths = module.paths;
  m.require = id => {
    if (Object.hasOwn(mocks, id)) return mocks[id];
    if (id.startsWith('./')) {
      for (const extension of ['.ts', '.tsx']) {
        const target = path.resolve(path.dirname(file), id + extension);
        if (fs.existsSync(target)) return load(path.relative(path.resolve(__dirname, '../src'), target), mocks);
      }
    }
    if (id === '@/features/agent/credit-limit') return load('features/agent/credit-limit.ts', mocks);
    return require(id);
  };
  m._compile(ts.transpileModule(fs.readFileSync(file, 'utf8') + expose, { compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, target: ts.ScriptTarget.ES2022 } }).outputText, file); return m.exports;
}
const plain = ({ children }) => React.createElement('div', {}, children);
const common = { '@/components/icons': { Icons: new Proxy({}, { get: () => () => null }) }, '@/components/rafii': { StateMessage: ({ title, description }) => React.createElement('p', {}, title, description), Surface: plain }, '@/components/ui/badge': { Badge: plain }, '@/components/ui/button': { Button: ({ children, disabled }) => React.createElement('button', { disabled }, children) }, '@/components/ui/skeleton': { Skeleton: plain } };
test('Writing now renders credits/Free availability without inheriting the shared legacy batch copy', () => {
  for (const mode of ['managed_credits', 'free_preview', 'legacy_allowances']) {
    const usage = { billingMode: mode, aiUsageExempt: false, entitlement: { writingBatchesRemaining: 0 } };
    const mocks = { ...common, '@/components/motion/text-scramble': { TextScramble: ({ text }) => React.createElement('span', {}, text) }, '@/lib/api/hooks': { useUsage: () => ({ data: usage }) }, '@/features/agent/use-model': { modelName: (_o, id) => id, shortLabel: (_o, id) => id }, '@/features/agent/work-surface-policy': load('features/agent/work-surface-policy.ts', {}), './catalog': { KIND_LABEL: { managed: 'Managed' }, routeKind: () => 'managed', costCopy: () => ({ line: 'Uses one writing batch from your plan per finished run.' }) } };
    const { WritingNow } = load('features/account/models/writing-now.tsx', mocks);
    const html = renderToStaticMarkup(React.createElement(WritingNow, { loading: false, error: false, onRetry: () => {}, options: [], agents: [], model: 'writer', option: { costClass: 'paid', qualified: true }, saved: null, picked: false }));
    if (mode === 'legacy_allowances') assert.match(html, /writing batch/);
    else { assert.doesNotMatch(html, /writing batch/); assert.match(html, mode === 'managed_credits' ? /approved maximum credits/ : /Free has no managed writing allowance/); }
  }
});
test('attachment read and retry both display MAX with 0.1-credit precision', () => {
  const hooks = { useMemory: () => ({ data: { media: { cloud: true, reconfirm: false } } }), useSnapshot: () => ({}), useAct: () => ({}), useInvalidate: () => () => {} };
  const mocks = { ...common, 'next/image': { default: plain }, sonner: { toast: {} }, '@/components/rafii/segmented-control': { SegmentedControl: plain }, '@/lib/api/hooks': hooks, '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api: {}, workspaceId: 'w' }) }, '@/features/library/asset-card': { useAssetImage: () => ({}) }, '@/lib/media/now-playing': { useNowPlaying: {} }, '@/features/memory/access-card': { MediaConsentConfirm: () => null }, './read-with-credit': load('features/agent/attachments/read-with-credit.ts', {}) };
  const { MediaOptions } = load('features/agent/attachments/media-options.tsx', mocks);
  for (const failed of [false, true]) {
    const html = renderToStaticMarkup(React.createElement(MediaOptions, { chip: { kind: 'image', id: 'a', role: 'reference', ...(failed ? { read: { status: 'failed' } } : {}) }, catalog: { notes: { available: true, photo: { typicalMilliCredits: 100, ceilingMilliCredits: 300 } } }, creditMode: true, fixtureWriter: false, isOwner: true, onRole: () => {}, onRead: () => {}, onRetry: () => {}, onRemove: () => {} }));
    assert.match(html, /About 0.1 credits/); assert.match(html, /approve MAX 0.3 credits/); assert.doesNotMatch(html, /about 1 credits/);
  }
});
test('authenticated Post Doctor shows real Free lifetime funding status and disables new paid I/O', () => {
  const availability = load('features/growth/availability.ts', {});
  const mocks = { ...common, '@tanstack/react-query': { useQueryClient: () => ({}) }, '@/components/ui/textarea': { Textarea: plain }, '@/lib/auth/access': { useWorkspaceAccess: () => ({ role: 'owner' }), checkAccess: () => true }, '@/lib/api/hooks': { useAct: () => ({}), useSnapshot: () => ({}), useUsage: () => ({ data: { billingMode: 'free_preview', freePreview: { postDoctor: { remaining: 1, eligible: false, reason: 'funding_unavailable' } } } }) }, '@/lib/workspace/provider': { useWorkspaceApi: () => ({ api: {}, workspaceId: 'w' }) }, './shared': { useGrowthCatalog: () => ({ data: { postDoctor: true, consented: true, checksPerDay: 10, rewritesPerDay: 1 } }), CheckResult: plain, GrowthConsent: plain }, './availability': availability };
  const { PostDoctorPanel } = load('features/growth/post-doctor-panel.tsx', mocks);
  const html = renderToStaticMarkup(React.createElement(PostDoctorPanel, { variant: { id: 'v', revision: 1 } }));
  assert.match(html, /1 lifetime Post Doctor check remaining/); assert.match(html, /Platform funding is unavailable/);
  assert.doesNotMatch(html, /10 checks|rewrite per day/); assert.match(html, /<button disabled="">Check draft/);
});
test('unqualified v2 Radar shows no legacy monitor allowance, but keeps manual pause available', () => {
  for (const mode of ['managed_credits', 'free_preview', 'legacy_allowances']) {
    const mocks = { ...common, 'next/link': plain, './radar.css': {}, '@tabler/icons-react': { IconArrowUpRight: plain, IconRadar: plain, IconArrowRight: plain }, '@tanstack/react-query': {}, '@/lib/workspace/provider': {}, '@/lib/auth/access': { useWorkspaceAccess: () => ({ role: 'owner' }) }, '@/lib/api/hooks': { useUsage: () => ({ data: { billingMode: mode } }) }, './availability': load('features/growth/availability.ts', {}), './shared': { useGrowthCatalog: () => ({}), GrowthConsent: plain }, './studio-parts': { useGrowthAction: () => ({ busy: false }) } };
    const { Permissions } = load('features/growth/radar.tsx', mocks, '\nexport { Permissions };');
    const html = renderToStaticMarkup(React.createElement(Permissions, { catalog: { consent: { sources: [], ai: false }, sources: [], monitor: { enabled: true, query: 'Saved topic', timezone: 'UTC' }, monitorMaximumUsdMicro: 10000 }, refresh: () => {} }));
    if (mode === 'legacy_allowances') assert.match(html, /Allowance: up to/);
    else { assert.doesNotMatch(html, /Allowance: up to|\$0\.01/); assert.match(html, /unavailable until/); }
    assert.match(html, /<button>Pause daily watch/);
  }
});
