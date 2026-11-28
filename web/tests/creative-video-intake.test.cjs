const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const React = require('react');
const { AppRouterContext } = require('next/dist/shared/lib/app-router-context.shared-runtime');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
const { createLoader, SRC } = require('./agent-ui-journeys/_load.cjs');
const { createHarness } = require('./agent-ui-client-harness.cjs');
const h = React.createElement;
const settle = () => new Promise(resolve => setImmediate(resolve));
const link = 'https://www.youtube.com/shorts/abcDEFG1234';

function setup(overrides = {}) {
  const api = { creativeVideoList: async () => ({ projects: [], provider: {} }), ...overrides };
  const modules = {
    'features/creative-video/project-editor': { ProjectEditor: () => null },
    'features/library/use-library': { useLibrary: () => { throw Error('Unscoped Library access'); } },
    'lib/workspace/provider': { useWorkspaceApi: () => ({ workspaceId: 'studio', api }) },
    'lib/auth/access': { useWorkspaceAccess: () => ({}), checkAccess: () => true },
    'lib/auth/session': { useAuth: () => ({ user: { id: 'editor' } }) },
    'components/layout/page-container': { __esModule: true, default: ({ children }) => h('main', null, children) },
    'components/rafii': { Surface: ({ children }) => h('section', null, children), StateMessage: ({ title }) => h('p', null, title) },
    'components/ui/button': { Button: props => h('button', props), buttonVariants: () => '' },
    'components/ui/input': { Input: props => h('input', props) },
    'components/ui/textarea': { Textarea: props => h('textarea', props) },
    'components/ui/label': { Label: props => h('label', props) },
    'components/ui/native-select': { NativeSelect: props => h('select', props), NativeSelectOption: props => h('option', props) },
    'components/ui/checkbox': { Checkbox: ({ checked, onCheckedChange, ...props }) =>
      h('button', { ...props, type: 'button', 'aria-pressed': checked, onClick: () => onCheckedChange(!checked) }) }
  };
  const stubs = Object.fromEntries(Object.entries(modules).map(([key, value]) => [path.join(SRC, key), value]));
  const media = createLoader({ stubs }).load('src/features/creative-video/media');
  stubs[path.join(SRC, 'features/creative-video/media')] = { ...media, PrivateVideo: () => null,
    useVideoLibrary: () => ({ videos: [], query: {}, brand: 'Studio', product: 'Ceramics' }) };
  const loader = createLoader({ stubs });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['creative-video-projects', 'studio'], { projects: [], provider: {} });
  const harness = createHarness(React, { shallow: type => type !== require('next/link').render });
  const opened = [];
  return { harness, opened,
    renderIntake() {
      const { CreativeStudio } = loader.load('src/features/creative-video/studio');
      harness.render(h(QueryClientProvider, { client }, h(AppRouterContext.Provider, { value: { push: url => opened.push(url) } },
        h(CreativeStudio, { projectId: '', referenceId: '' }))));
      harness.type(harness.find('input[id="video-title"]'), 'Studio mug');
      harness.type(harness.find('textarea[id="video-brief"]'), 'Show the glaze in daylight.');
      harness.type(harness.find('input[id="reference-link"]'), link);
    },
    renderVariants() {
      const { ProjectVariants } = loader.load('src/features/creative-video/project-variants');
      harness.render(h(ProjectVariants, { projectId: 'source', revision: 2, disabled: false }));
    },
    cleanup() { harness.cleanup(); client.clear(); }
  };
}

test('a verified video outside the first Library page still requires rights and opens the project made from the same link', async () => {
  const creates = [], lookups = [];
  const app = setup({ creativeReferenceLink: async (...args) => { lookups.push(args); return { assetId: 'older-video', durationSeconds: 42 }; },
    creativeVideoCreate: async (_w, body) => { creates.push(body); return { project: { id: 'project' }, provider: {} }; } });
  const u = app.harness;
  try {
    app.renderIntake(); u.click(u.button('Find in workspace')); await settle();
    assert.deepEqual(lookups, [['studio', link]]);
    assert.ok(u.find('option[value="older-video"]'));
    assert.equal(u.button('Analyze and create blueprint').disabled, true);
    u.click(u.find('button[id="reference-rights"]')); u.click(u.button('Analyze and create blueprint')); await settle();
    assert.equal(creates.length, 1); assert.equal(creates[0].referenceAssetId, 'older-video');
    assert.equal(creates[0].referenceLink, link); assert.equal(creates[0].rightsConfirmed, true);
    assert.deepEqual(app.opened, ['/app/creative?project=project']);
  } finally { app.cleanup(); }
});

test('a stale publication can be checked again at the same URL; a refused match cannot be reused', async () => {
  let checks = 0;
  const app = setup({ creativeReferenceLink: async () => {
    if (++checks === 1) return { assetId: 'old-video', durationSeconds: 32 };
    throw Error('No verified public post');
  }, creativeVideoCreate: async () => { throw Error('The linked Library video changed. Resolve the link again.'); } });
  const u = app.harness;
  try {
    app.renderIntake(); u.click(u.button('Find in workspace')); await settle();
    u.click(u.find('button[id="reference-rights"]')); u.click(u.button('Analyze and create blueprint')); await settle();
    const recheck = u.findAll('button').find(b => /find in workspace|check link again|recheck|check again/i.test(b.textContent));
    assert.ok(recheck && !recheck.disabled, 'Can recheck the same URL');
    u.click(recheck); await settle();
    assert.equal(checks, 2); assert.equal(u.findAll('option[value="old-video"]').length, 0);
    assert.equal(u.button('Create blueprint').disabled, true); assert.deepEqual(app.opened, []);
  } finally { app.cleanup(); }
});

test('a retry after a dropped batch response reuses the exact reviewed request key and targets', async () => {
  const calls = [];
  const app = setup({ creativeVideoVariants: async (...args) => {
    calls.push(args); if (calls.length === 1) throw Error('Interrupted response');
    return { projects: [{ id: 'ig1', platform: 'Instagram', aspectRatio: '1:1' }, { id: 'yt1', platform: 'YouTube', aspectRatio: '16:9' }] };
  } });
  const u = app.harness;
  try {
    app.renderVariants();
    u.type(u.find('select[id="variant-Instagram"]'), '1:1'); u.type(u.find('select[id="variant-YouTube"]'), '16:9');
    assert.equal(u.button('Create editable versions').disabled, true); u.click(u.find('button[id="variant-rights"]'));
    u.click(u.button('Create editable versions')); await settle();
    assert.match(u.container.textContent, /Interrupted response/); u.click(u.button('Create editable versions')); await settle();
    assert.equal(calls.length, 2); assert.deepEqual(calls[0], calls[1]);
    assert.deepEqual(calls[0].slice(0, 2), ['studio', 'source']); assert.equal(calls[0][2].revision, 2);
    assert.deepEqual(calls[0][2].targets, [{ platform: 'Instagram', aspectRatio: '1:1' }, { platform: 'YouTube', aspectRatio: '16:9' }]);
    assert.ok(u.button('Create editable versions').disabled); assert.equal(u.findAll('ul[aria-label="Saved versions"]').length, 1);
  } finally { app.cleanup(); }
});
