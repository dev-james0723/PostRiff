const test = require('node:test');
const assert = require('node:assert/strict');
const path = require('node:path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { AppRouterContext } = require('next/dist/shared/lib/app-router-context.shared-runtime');
const { QueryClient, QueryClientProvider } = require('@tanstack/react-query');
const { createLoader, SRC } = require('./agent-ui-journeys/_load.cjs');
const { createHarness } = require('./agent-ui-client-harness.cjs');

const h = React.createElement;
const scene = { sceneId: 's1', purpose: 'Opening hook', direction: 'Bring the lamp into frame.', caption: '',
  durationMs: 1500, clipId: null, estimatedUsdMicro: 150000, estimatedMilliCredits: 15000 };
const provider = { available: true, model: 'fixture provider' };
const query = { videos: [], query: {} };
const workspaceApi = {};
const emptyPhotoHooks = {
  useSnapshot: () => ({ data: { revision: 1, state: { phase2: { assets: [] } } } }),
  useAct: () => ({ isPending: false, mutate: () => assert.fail('Unexpected permission change') })
};
const sandbox = createLoader({ stubs: {
  [path.join(SRC, 'lib/api/hooks')]: emptyPhotoHooks,
  [path.join(SRC, 'lib/auth/session')]: { useAuth: () => ({ user: { id: 'editor-1' } }) },
  [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ workspaceId: 'unit', api: workspaceApi }) },
  [path.join(SRC, 'features/creative-video/media')]: {
    useVideoLibrary: () => query,
    VideoSelect: () => null,
    PrivateVideo: ({ label }) => h('span', null, label)
  }
} });
const { ProjectEditor } = sandbox.load('src/features/creative-video/project-editor');
const { WorkspaceAccessProvider } = sandbox.load('src/lib/auth/access');

function editor({ permissions, revision = 2, pinned, generation, overlaySignals, measured, clip = {}, extraScenes = [], selectedSceneId, router = {}, onUpdate = () => {} }) {
  const reply = { provider, project: {
    id: 'demo', title: 'Lamp study', platform: 'Instagram', brief: 'Introduce the lamp', aspectRatio: '9:16',
    headRevision: 2, revision, referenceAssetId: 'ref',
    analysis: { width: 640, height: 360, durationMs: 1500, fps: 24, hasAudio: false, overlaySignals, measured,
      scenes: [{ startMs: 0, endMs: 1500, durationMs: 1500 }] },
    context: { brand: 'Sample studio', subject: 'Lamp', tone: '', audience: '', preferences: ['Show the product in use'], cloudAllowed: true, voiceRevision: 2 },
    scenes: [{ ...scene, generation, ...clip }, ...extraScenes], history: [{ revision: 2, sceneCount: 1 }, { revision: 1, sceneCount: 1 }], export: null
  } };
  return h(AppRouterContext.Provider, { value: router },
    h(WorkspaceAccessProvider, { value: { hasWorkspace: true, permissions, capabilities: [], role: 'editor', plan: 'studio' } },
      h(ProjectEditor, { initial: reply, pinnedRevision: pinned, selectedSceneId, onUpdate })));
}
const render = options => renderToStaticMarkup(editor(options));

test('viewers can read the saved plan and memory, while editors and approvers get their own controls', () => {
  const reader = render({ permissions: ['read'] });
  assert.match(reader, /Lamp study/);
  assert.match(reader, /Show the product in use/);
  assert.match(reader, /id="scene-direction"[^>]*disabled|disabled[^>]*id="scene-direction"/);
  assert.doesNotMatch(reader, /Render MP4|Generate this scene/);
  const editor = render({ permissions: ['read', 'edit'] });
  assert.match(editor, /Render MP4/);
  assert.doesNotMatch(editor, /Generate this scene/);
  const approver = render({ permissions: ['read', 'approve'] });
  assert.match(approver, /Generate this scene/);
  assert.doesNotMatch(approver, /Render MP4/);
  assert.match(approver, /AI intelligence/);
  assert.match(approver, /Getting a scene quote/);
  assert.match(approver, /aria-valuetext="Balanced"/);
});

test('opening an old revision and reading an uncertain provider operation cannot trigger another generation', () => {
  const permissions = ['read', 'approve', 'edit'];
  const old = render({ permissions, revision: 1, pinned: 1 });
  assert.match(old, /Viewing saved revision 1/);
  assert.match(old, /Open current project/);
  assert.doesNotMatch(old, /Render MP4|Generate this scene|Check generation/);
  const unknown = render({ permissions, generation: { state: 'unknown', actualUsdMicro: null } });
  assert.match(unknown, /needs reconciliation/);
  assert.doesNotMatch(unknown, /Generate this scene|Recorded cost/);
  for (const state of ['pending', 'submitting', 'unknown']) {
    const unresolved = render({ permissions, generation: { state } });
    assert.match(unresolved, /Check generation/);
    assert.doesNotMatch(unresolved, /Generate this scene|Prepare another take/);
    assert.doesNotMatch(render({ permissions: ['read', 'edit'], generation: { state } }), /Check generation/);
  }
});

test('a scene link restores the exact take and preserves the selection across saved revisions', () => {
  const second = { ...scene, sceneId: 's2', purpose: 'Product detail', generation: { state: 'unknown' } };
  const options = { permissions: ['read', 'edit', 'approve'], extraScenes: [second] };
  const linked = render({ ...options, selectedSceneId: 's2' });
  assert.match(linked, /id="scene-heading">Product detail</);
  assert.match(linked, /needs reconciliation/);
  assert.match(linked, /href="[^"]*scene=s2[^"]*"/);
  assert.doesNotMatch(linked, /Generate this scene/);
  const reopened = render(options);
  assert.match(reopened, /id="scene-heading">Product detail</);
  const pinned = render({ ...options, revision: 1, pinned: 1, selectedSceneId: 's2' });
  assert.match(pinned, /href="\/app\/creative\?project=demo&amp;scene=s2"/);
  assert.doesNotMatch(pinned, /Generate this scene|Check generation/);
  const missing = render({ ...options, selectedSceneId: 'missing' });
  assert.match(missing, /Choose a scene from the timeline/);
  assert.doesNotMatch(missing, /id="scene-heading"|Generate this scene|Check generation/);
});

test('selecting another scene replaces only the location and keeps unsaved edits in the timeline', () => {
  const calls = [];
  const second = { ...scene, sceneId: 's2', purpose: 'Product detail', direction: 'Show the switch.' };
  const options = { permissions: ['read', 'edit'], extraScenes: [second],
    router: { replace: (...args) => calls.push(args) } };
  const harness = createHarness(React, { shallow: type => type === WorkspaceAccessProvider || type === ProjectEditor,
    window: { addEventListener() {}, removeEventListener() {} } });
  const direction = () => harness.findElement(el => el.props.id === 'scene-direction');
  try {
    harness.render(editor({ ...options, selectedSceneId: 's1' }));
    harness.act(() => direction().props.onChange({ target: { value: 'Keep my new opening.' } }));
    const other = harness.findElement(el => el.props['aria-pressed'] === false);
    harness.act(() => other.props.onClick());
    assert.deepEqual(calls, [['/app/creative?project=demo&scene=s2', { scroll: false }]]);
    harness.render(editor({ ...options, selectedSceneId: 's2' }));
    assert.equal(direction().props.value, 'Show the switch.');
    harness.render(editor({ ...options, selectedSceneId: 's1' }));
    assert.equal(direction().props.value, 'Keep my new opening.');
  } finally { harness.cleanup(); }
});

test('an approver sees the recorded cause and editors can prepare a replacement take without approving spend', async () => {
  for (const [reason, explanation] of [
    ['provider_output_unusable', /footage that Rafii could not use/],
    ['authorization_changed', /authorization changed/],
    ['submission_reconciled_without_clip', /Billing reconciliation finished/]
  ]) {
    const html = render({ permissions: ['read', 'edit'], generation: { state: 'failed', reason } });
    assert.match(html, explanation);
    assert.match(html, /Prepare another take/);
    assert.doesNotMatch(html, /Generate this scene/);
  }
  const clip = { clipId: 'film-1', clipOrigin: 'generated' };
  assert.doesNotMatch(render({ permissions: ['read', 'approve'], clip }), /Prepare another take/);
  assert.doesNotMatch(render({ permissions: ['read', 'edit'], clip, pinned: 2 }), /Prepare another take/);
  const harness = createHarness(React, { shallow: type => type === WorkspaceAccessProvider || type === ProjectEditor,
    window: { addEventListener() {}, removeEventListener() {} } });
  const calls = [];
  const received = [];
  const tree = editor({ permissions: ['read', 'edit'], clip, onUpdate: reply => received.push(reply) });
  const original = tree.props.children.props.children.props.initial;
  const saved = { ...original, project: { ...original.project, headRevision: 3, revision: 3,
    scenes: original.project.scenes.map(shot => ({ ...shot, clipId: null, clipOrigin: null })) } };
  workspaceApi.creativeVideoEdit = async (...args) => {
    calls.push(args);
    return saved;
  };
  try {
    harness.render(tree);
    const prepare = () => harness.findElement(el => el.props.children === 'Prepare another take');
    assert.equal(prepare().props.disabled, false);
    const direction = () => harness.findElement(el => el.props.id === 'scene-direction');
    harness.act(() => direction().props.onChange({ target: { value: 'An unsaved change' } }));
    assert.equal(prepare().props.disabled, true);
    harness.act(() => direction().props.onChange({ target: { value: scene.direction } }));
    assert.equal(prepare().props.disabled, false);
    harness.act(() => prepare().props.onClick());
    await new Promise(resolve => setImmediate(resolve));
    assert.deepEqual(calls, [['unit', 'demo', { revision: 2, scenes: [{ sceneId: 's1', retake: true }] }]]);
    assert.deepEqual(received, [saved]);
    assert.equal(prepare(), null);
  } finally { harness.cleanup(); delete workspaceApi.creativeVideoEdit; }
});

test('the blueprint distinguishes OCR observations, possible creative devices and unavailable recognition', () => {
  const overlaySignals = { state: 'partial', minimumWordConfidence: 60, frames: [{ sceneIndex: 0, timeMs: 375,
    wordCount: 4, meanConfidence: 92.5, medianWordHeightPct: 8.4, verticalRegion: 'upper', interpretiveClues: ['question'] }] };
  const html = render({ permissions: ['read'], overlaySignals });
  assert.match(html, /4 recognized words/);
  assert.match(html, /92.5\/100 average confidence/);
  assert.match(html, /upper third/);
  assert.match(html, /Possible creative device · question/);
  assert.match(html, /Some sampled frames could not be read/);
  const missing = render({ permissions: ['read'], overlaySignals: { state: 'unavailable', reason: 'english_data_unavailable', frames: [] } });
  assert.match(missing, /English recognition data is unavailable/);
  assert.doesNotMatch(render({ permissions: ['read'] }), /On-screen text/);
});

test('source trim and scene order save together without requesting generation', async () => {
  const second = { ...scene, sceneId: 's2', purpose: 'Product detail' };
  const tree = editor({ permissions: ['read', 'edit'], clip: { clipId: 'lamp' }, extraScenes: [second] });
  const original = tree.props.children.props.children.props.initial;
  const calls = [];
  workspaceApi.creativeVideoEdit = async (...args) => { calls.push(args); return original; };
  const harness = createHarness(React, { shallow: type => type === WorkspaceAccessProvider || type === ProjectEditor,
    window: { addEventListener() {}, removeEventListener() {} } });
  try {
    harness.render(tree);
    harness.act(() => harness.findElement(el => el.props.id === 'footage-start').props.onChange({ target: { value: '0.25' } }));
    harness.act(() => harness.findElement(el => el.props.children === 'Move later').props.onClick());
    harness.act(() => harness.findElement(el => Array.isArray(el.props.children) && el.props.children.includes('timeline')).props.onClick());
    await new Promise(resolve => setImmediate(resolve));
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0][2], { revision: 2, sceneOrder: ['s2', 's1'], scenes: [{
      sceneId: 's1', direction: scene.direction, caption: '', durationMs: 1500, trimStartMs: 250
    }] });
  } finally { harness.cleanup(); delete workspaceApi.creativeVideoEdit; }
  assert.doesNotMatch(render({ permissions: ['read'], extraScenes: [second] }), /Move later|Create platform versions/);
});

test('reference audio displays measured intervals, no audio and unavailable analysis independently', () => {
  const measured = { sampleIntervalMs: 125, sampledFrameCount: 12, audioRhythm: {
    state: 'measured', resolutionMs: 20, onsetMs: [125, 625, 1125], medianSpacingMs: 500
  } };
  const html = render({ permissions: ['read'], measured });
  assert.match(html, /3 detected volume rises/);
  assert.match(html, /Median interval between rises · 0.5 s/);
  assert.match(html, /0.125 s · 0.625 s · 1.125 s/);
  assert.doesNotMatch(render({ permissions: ['read'] }), /Show timing cues/);
});

test('performance readings distinguish missing measurements, true zero and the provider window', () => {
  const { PerformanceReadings } = sandbox.load('src/features/creative-video/performance');
  const metric = { name: 'views', value: 0, unit: 'count', availability: 'available', definitionVersion: 'v1',
    observedAt: 1730000000, periodStart: null, periodEnd: null, readOffset: '24h', source: 'youtube_analytics' };
  const html = renderToStaticMarkup(h(PerformanceReadings, { data: { state: 'linked', posts: [
    { jobId: 'job', provider: 'YouTube', providerPostId: 'exact-post', verifiedAt: 1730000000, metrics: [
      metric, { ...metric, name: 'saves', value: null, availability: 'unavailable' }
    ] }
  ] } }));
  assert.match(html, /0 count/);
  assert.match(html, /Unavailable/);
  assert.match(html, /exact-post/);
  assert.match(html, /YouTube Analytics/);
  assert.match(html, /Observation window unavailable/);
});

const uiFixture = (photoHooks = emptyPhotoHooks) => createLoader({ stubs: {
  [path.join(SRC, 'lib/api/hooks')]: photoHooks,
  [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ workspaceId: 'unit', api: workspaceApi }) },
  [path.join(SRC, 'features/library/asset-card')]: { useAssetImage: () => ({ data: null }) },
  [path.join(SRC, 'components/ui/button')]: { Button: ({ children, ...props }) => h('button', props, children) },
  [path.join(SRC, 'components/ui/input')]: { Input: props => h('input', props) },
  [path.join(SRC, 'components/ui/label')]: { Label: props => h('label', props) },
  [path.join(SRC, 'components/ui/native-select')]: { NativeSelect: props => h('select', props), NativeSelectOption: props => h('option', props) },
  [path.join(SRC, 'components/ui/slider')]: { Slider: ({ value, onValueChange, getAriaLabel, getAriaValueText }) =>
    h('input', { type: 'range', min: 0, max: 3, value: value[0], 'aria-label': getAriaLabel(), 'aria-valuetext': getAriaValueText('', value[0]), onChange: e => onValueChange([Number(e.target.value)]) }) },
  [path.join(SRC, 'components/ui/checkbox')]: { Checkbox: ({ checked, onCheckedChange, ...props }) =>
    h('button', { ...props, 'aria-pressed': checked, onClick: () => onCheckedChange(!checked) }) }
} });
const model = { id: 'fixture-model', label: 'Fixture model', provider: 'runway', available: true, aspectRatios: ['9:16'], resolutions: ['720p'], audioModes: ['silent'], mediaKind: 'generated' };
const local = { ...model, id: 'storyboard-v1', label: 'Motion card', provider: 'local', mediaKind: 'composed' };
function quoteReply(settings, id = 'q-one', extra = {}) {
  const estimate = settings.level === 'draft' ? 0 : settings.level === 'cinematic' ? 32000 : 15000;
  const choice = settings.level === 'draft' ? local : model;
  return { models: [model, local], quote: {
    id, eligible: true, expiresAt: Math.floor(Date.now() / 1000) + 60, estimatedMilliCredits: estimate,
    maximumMilliCredits: estimate, availableMilliCredits: 100000, remainingMilliCredits: 100000 - estimate, estimatedUsdMicro: estimate * 10,
    level: settings.level, mode: settings.mode, label: choice.label, provider: choice.provider, model: choice.id, mediaKind: choice.mediaKind,
    recommendation: 'A direction that matches these settings.', limitations: [], resolution: '720p', audio: 'silent', billedSeconds: 4,
    outputProfile: { width: 720, height: 1280, durationMs: 4000, hasAudio: false }, ...extra
  } };
}
const delay = (ms = 270) => new Promise(resolve => setTimeout(resolve, ms));
const quoteProps = { models: [model, local], aspect: '9:16', durationMs: 1500, hasReference: true, disabled: false };

test('a selected private photo requires fresh image consent and approval of the exact resulting quote', async () => {
  const veo = { ...model, id: 'veo-3.1-fast-generate-001', provider: 'vertex-veo' };
  const photo = { id: 'a'.repeat(32), hash: 'b'.repeat(64), mime: 'image/jpeg', processing: 'decoded', width: 720, height: 1280 };
  photo.storagePath = 'unit/media/' + photo.id + '-' + photo.hash + '.jpg';
  const state = { mediaEgress: { firstFrame: { processor: 'vertex-veo:' + veo.id, grantId: 'owner-grant' } },
    phase2: { assets: [photo, { ...photo, id: 'foreign', displayTitle: 'Foreign photo' }] } };
  const hooks = { ...emptyPhotoHooks, useSnapshot: () => ({ data: { revision: 12, state } }) };
  const { SceneQuote } = uiFixture(hooks).load('src/features/creative-video/scene-quote');
  const priced = [], sent = [];
  const harness = createHarness(React);
  try {
    harness.render(h(SceneQuote, { ...quoteProps, models: [veo], onQuote: async settings => {
      priced.push(settings); return quoteReply(settings, 'q-image-' + priced.length, { model: veo.id, provider: veo.provider });
    }, onGenerate: id => sent.push(id) }));
    await delay();
    harness.click(harness.find('button[id="generation-consent"]'));
    harness.type(harness.find('select[id="scene-first-frame"]'), photo.id);
    assert.doesNotMatch(harness.container.textContent, /Foreign photo/);
    assert.equal(harness.button('Generate this scene').disabled, true);
    await delay();
    assert.equal(priced.length, 1);
    harness.click(harness.find('button[id="first-frame-rights"]'));
    await delay();
    assert.deepEqual(priced.at(-1), { mode: 'auto', level: 'balanced', firstFrameAssetId: photo.id, firstFrameConsent: true });
    assert.equal(harness.button('Generate this scene').disabled, true);
    harness.click(harness.find('button[id="generation-consent"]'));
    harness.click(harness.button('Generate this scene'));
    assert.deepEqual(sent, ['q-image-2']);
    harness.type(harness.find('select[id="scene-first-frame"]'), '');
    assert.equal(harness.button('Generate this scene').disabled, true);
    await delay();
    assert.deepEqual(priced.at(-1), { mode: 'auto', level: 'balanced' });
  } finally { harness.cleanup(); }
});

test('enabling the workspace photo permission requires an explicit owner confirmation naming Google Cloud Veo', () => {
  const calls = [], prompts = [];
  let confirmed = false;
  const { FirstFramePicker } = uiFixture({ ...emptyPhotoHooks,
    useAct: () => ({ mutate: payload => calls.push(payload) }) }).load('src/features/creative-video/first-frame');
  const harness = createHarness(React, { window: { confirm: text => { prompts.push(text); return confirmed; } } });
  try {
    harness.render(h(FirstFramePicker, { enabled: true, disabled: false, settings: { mode: 'auto', level: 'balanced' }, onChange() {} }));
    const allow = harness.button('Allow first frames for this workspace');
    harness.click(allow);
    assert.deepEqual(calls, []);
    confirmed = true; harness.click(allow);
    assert.match(prompts[1], /Google Cloud Veo 3\.1 Fast/);
    assert.deepEqual(calls, [{ revision: 1, action: 'media_egress', payload: { purpose: 'video_first_frame', cloud: true, confirmed: true } }]);
  } finally { harness.cleanup(); }
});

test('slider and credit edits price new settings, clear consent immediately and submit one reviewed quote', async () => {
  const { SceneQuote } = uiFixture().load('src/features/creative-video/scene-quote');
  const harness = createHarness(React);
  const priced = [], sent = [];
  try {
    harness.render(h(SceneQuote, { ...quoteProps, onQuote: async settings => { priced.push(settings); return quoteReply(settings, 'q-' + priced.length); }, onGenerate: id => sent.push(id) }));
    const generate = () => harness.button('Generate this scene');
    const confirm = () => harness.find('button[id="generation-consent"]');
    assert.equal(generate().disabled, true);
    await delay();
    assert.deepEqual(priced[0], { mode: 'auto', level: 'balanced' });
    assert.match(harness.container.textContent, /Estimated AI Credits15/);
    assert.match(harness.container.textContent, /Estimated balance after85 credits/);
    assert.equal(harness.find('a').getAttribute('href'), 'https://runwayml.com/');
    harness.click(confirm()); assert.equal(generate().disabled, false);
    harness.type(harness.find('input[type="range"]'), '3');
    assert.equal(generate().disabled, true);
    await delay();
    assert.equal(priced.at(-1).level, 'cinematic');
    assert.match(harness.container.textContent, /Estimated AI Credits32/);
    harness.click(confirm());
    harness.type(harness.find('input[id="generation-budget"]'), '32.125');
    assert.equal(generate().disabled, true);
    await delay();
    assert.equal(priced.at(-1).maxMilliCredits, 32125);
    harness.click(confirm()); harness.click(generate()); harness.click(generate());
    assert.deepEqual(sent, ['q-3']);
  } finally { harness.cleanup(); }
});

test('late price responses and expired or unaffordable quotes cannot authorize footage', async () => {
  const { SceneQuote } = uiFixture().load('src/features/creative-video/scene-quote');
  const harness = createHarness(React);
  const requests = [];
  try {
    harness.render(h(SceneQuote, { ...quoteProps, onQuote: settings => new Promise(resolve => requests.push({ settings, resolve })), onGenerate: () => assert.fail() }));
    const confirm = () => harness.find('button[id="generation-consent"]');
    await delay();
    harness.click(harness.button('Cinematic'));
    await delay();
    requests[1].resolve(quoteReply(requests[1].settings, 'expired', { expiresAt: 1 }));
    await delay(10);
    requests[0].resolve(quoteReply(requests[0].settings, 'late'));
    await delay(10);
    assert.equal(confirm().disabled, true);
    assert.doesNotMatch(harness.container.textContent, /Estimated AI Credits15/);
    harness.click(harness.button('Refresh quote')); await delay();
    requests[2].resolve(quoteReply(requests[2].settings, null, { eligible: false, reason: 'Insufficient available credits.', availableMilliCredits: 1000 }));
    await delay(10);
    assert.match(harness.container.textContent, /Insufficient available credits/);
    assert.equal(confirm().disabled, true);
    harness.click(harness.button('Use a draft storyboard')); await delay();
    assert.deepEqual(requests[3].settings, { level: 'draft', mode: 'manual', model: 'storyboard-v1', audio: 'silent', resolution: '720p' });
    requests[3].resolve(quoteReply(requests[3].settings, 'local')); await delay(10);
    assert.ok(harness.button('Compose this scene'));
  } finally { harness.cleanup(); }
});

test('advanced settings send only explicit fields and a manual or budget strategy requires its selection', async () => {
  const { SceneQuote } = uiFixture().load('src/features/creative-video/scene-quote');
  const harness = createHarness(React);
  const requests = [];
  try {
    harness.render(h(SceneQuote, { ...quoteProps, onQuote: async settings => { requests.push(settings); return quoteReply(settings, 'q-' + requests.length); }, onGenerate() {} }));
    const select = (id, value) => harness.type(harness.find('select[id="' + id + '"]'), value);
    select('scene-routing', 'manual'); await delay();
    assert.equal(requests.length, 0);
    select('generation-model', model.id);
    select('scene-resolution', '1080p');
    select('direction-productFidelity', 'high');
    select('scene-audio', 'generated');
    select('scene-reliability', 'strict'); await delay();
    assert.deepEqual(requests[0], { level: 'balanced', mode: 'manual', model: model.id, resolution: '1080p', productFidelity: 'high', audio: 'generated', reliability: 'strict' });
    select('scene-routing', 'budget'); await delay();
    assert.equal(requests.length, 1);
    harness.type(harness.find('input[id="generation-budget"]'), '17.1234'); await delay();
    assert.equal(requests.length, 1);
    harness.type(harness.find('input[id="generation-budget"]'), '17.123'); await delay();
    assert.equal(requests.at(-1).maxMilliCredits, 17123);
    assert.equal(requests.at(-1).model, undefined);
  } finally { harness.cleanup(); }
});

test('an unavailable cloud route offers an explicit free storyboard and never sends a generation automatically', async () => {
  const { SceneQuote } = uiFixture().load('src/features/creative-video/scene-quote');
  const harness = createHarness(React);
  const requests = [], approved = [];
  try {
    harness.render(h(SceneQuote, { ...quoteProps, models: [{ ...model, available: false }, local],
      onQuote: async settings => {
        requests.push(settings);
        if (settings.level !== 'draft') throw Object.assign(new Error('No configured cloud model.'), { code: 'creative_video_no_model' });
        return quoteReply(settings, 'offline');
      }, onGenerate: id => approved.push(id) }));
    await delay();
    assert.match(harness.container.textContent, /No configured cloud model/);
    assert.deepEqual(approved, []);
    harness.click(harness.button('Use a draft storyboard')); await delay();
    assert.equal(requests.at(-1).model, 'storyboard-v1');
    assert.deepEqual(approved, []);
    harness.click(harness.find('button[id="generation-consent"]')); harness.click(harness.button('Compose this scene'));
    assert.deepEqual(approved, ['offline']);
  } finally { harness.cleanup(); }
});

test('an editor is limited to zero provider cost and zero credits on a composed take', async () => {
  const { SceneQuote } = uiFixture().load('src/features/creative-video/scene-quote');
  const harness = createHarness(React);
  const received = [];
  try {
    harness.render(h(SceneQuote, { ...quoteProps, localOnly: true, onQuote: async settings => {
      assert.equal(settings.model, 'storyboard-v1');
      return quoteReply(settings, 'unexpected', { mediaKind: 'generated', estimatedUsdMicro: 2000 });
    }, onGenerate: id => received.push(id) }));
    await delay();
    assert.equal(harness.find('button[id="generation-consent"]').disabled, true);
    harness.click(harness.button('Compose this scene'));
    assert.deepEqual(received, []);
    assert.equal(harness.find('select[id="generation-model"]'), null);
  } finally { harness.cleanup(); }
});

test('editable completed takes support explicit editorial acceptance without authorizing another take', () => {
  const clip = { clipId: 'clip', clipOrigin: 'composed' };
  const completed = render({ permissions: ['read', 'edit'], generation: { state: 'completed', accepted: null }, clip });
  assert.match(completed, /Composed storyboard/);
  assert.match(completed, /Accept take/);
  assert.match(completed, /Needs revision/);
  assert.doesNotMatch(render({ permissions: ['read'], generation: { state: 'completed', accepted: true }, clip }), /Accept take/);
  assert.doesNotMatch(render({ permissions: ['read', 'edit'], generation: { state: 'completed' }, clip, pinned: 2 }), /Accept take/);
});

test('project planning combines the reviewed scene strategies with a whole-project ceiling and never generates', async () => {
  const calls = [];
  const { ProjectPlan } = createLoader({ stubs: {
    [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ workspaceId: 'unit', api }) },
    [path.join(SRC, 'components/ui/input')]: { Input: props => h('input', props) },
    [path.join(SRC, 'components/ui/native-select')]: { NativeSelect: props => h('select', props), NativeSelectOption: props => h('option', props) },
    [path.join(SRC, 'components/ui/label')]: { Label: props => h('label', props) },
    [path.join(SRC, 'components/ui/button')]: { Button: props => h('button', props) }
  } }).load('src/features/creative-video/project-plan');
  const api = { creativeVideoPlan: async (...args) => { calls.push(args); return { totalMilliCredits: 12500, unpricedScenes: 0,
    scenes: [{ sceneId: 's1', label: 'Existing footage', estimatedMilliCredits: 0 }, { sceneId: 's2', label: 'Quoted camera route', estimatedMilliCredits: 12500 }] }; } };
  const overrides = { s2: { mode: 'manual', model: 'fixture-model', level: 'professional' } };
  const harness = createHarness(React);
  try {
    harness.render(h(ProjectPlan, { id: 'project', revision: 5, scenes: [scene, { ...scene, sceneId: 's2', purpose: 'Hero product' }],
      localOnly: false, overrides, disabled: false, onScene() {} }));
    assert.equal(calls.length, 0);
    harness.act(() => harness.find('details').props.onToggle({ currentTarget: { open: true } }));
    harness.type(harness.find('input[id="plan-budget"]'), '20.125');
    await delay();
    assert.deepEqual(calls, [['unit', 'project', { revision: 5, settings: { mode: 'hybrid', level: 'balanced', maxMilliCredits: 20125 }, sceneSettings: overrides }]]);
    assert.match(harness.container.textContent, /12.5 estimated AI Credits/);
    assert.match(harness.container.textContent, /Existing footage · 0 credits/);
    assert.match(harness.container.textContent, /Hero product/);
    harness.type(harness.find('select[id="plan-mode"]'), 'budget');
    await delay();
    assert.equal(calls[1][2].sceneSettings, undefined);
    assert.equal(calls[1][2].settings.mode, 'budget');
  } finally { harness.cleanup(); }
});

test('founder video monitoring shows measured costs, unknown acceptance and capability-scoped model controls', () => {
  const data = { models: [{ id: 'route-card', label: 'Motion card', provider: 'local', paused: false, available: true, pricingVersion: 'fixture-v1' }],
    rows: [{ model: 'route-card', provider: 'local', plan: 'studio', usageClass: 'internal', jobs: 8, completed: 6, failed: 1, pendingReconciliations: 1,
      estimatedUsdMicro: 500000, actualUsdMicro: null, reservedMilliCredits: 12000, consumedMilliCredits: 1000,
      averageLatencySeconds: 14, accepted: null, technicalSuccessRate: 6 / 7, costPerAcceptedUsdMicro: null }], dataState: 'measured' };
  function view(mode, manage) {
    const key = ['founder', mode, 'local', 'creative-video-usage'];
    const client = new QueryClient();
    client.setQueryData(key, data);
    const { CreativeVideoCost } = createLoader({ stubs: {
      [path.join(SRC, 'features/founder/customers/kit/api')]: {
        useFounderScope: () => ({ mode, ready: true, key: () => key }), useCapability: () => manage, failureOf: () => ({})
      }
    } }).load('src/features/founder/ai-cost/creative-video-cost');
    const result = renderToStaticMarkup(h(QueryClientProvider, { client }, h(CreativeVideoCost)));
    client.clear();
    return result;
  }
  const measured = view('live', true);
  assert.match(measured, /Motion card/); assert.match(measured, /fixture-v1/); assert.match(measured, /85.7%/);
  assert.match(measured, /Unmeasured/); assert.match(measured, /Recorded provider cost/); assert.match(measured, /Excludes unconfirmed charges/);
  assert.match(measured, />internal</i); assert.match(measured, /Review pausing Motion card/);
  const control = html => html.match(/<button[^>]*aria-label="Review pausing Motion card"[^>]*>/)?.[0];
  const disabled = /\s(?:disabled=""|aria-disabled="true")/;
  assert.doesNotMatch(control(measured), disabled);
  assert.match(control(view('live', false)), disabled);
  assert.match(control(view('demo', true)), disabled);
});

test('a brief-only brand video can start square; adding a reference requires its own permission', async () => {
  const asset = { id: 'allowed-reference', duration: 13 };
  const requests = [], opened = [];
  const api = { creativeVideoList: async () => ({ projects: [], provider: {} }), creativeVideoCreate: async (_workspace, body) => {
    requests.push(body); return { project: { id: 'saved' }, provider: {} };
  } };
  const ui = createLoader({ stubs: {
    [path.join(SRC, 'lib/auth/session')]: { useAuth: () => ({ user: { id: 'member' } }) },
    [path.join(SRC, 'lib/workspace/provider')]: { useWorkspaceApi: () => ({ workspaceId: 'unit', api }) },
    [path.join(SRC, 'lib/auth/access')]: { useWorkspaceAccess: () => ({}), checkAccess: () => true },
    [path.join(SRC, 'components/layout/page-container')]: { __esModule: true, default: ({ children }) => h('main', null, children) },
    [path.join(SRC, 'components/rafii')]: { Surface: ({ children }) => h('section', null, children), StateMessage: ({ title }) => h('p', null, title), CollectionRow: () => null },
    [path.join(SRC, 'components/ui/button')]: { Button: props => h('button', props), buttonVariants: () => '' },
    [path.join(SRC, 'components/ui/input')]: { Input: props => h('input', props) },
    [path.join(SRC, 'components/ui/textarea')]: { Textarea: props => h('textarea', props) },
    [path.join(SRC, 'components/ui/label')]: { Label: props => h('label', props) },
    [path.join(SRC, 'components/ui/native-select')]: { NativeSelect: props => h('select', props), NativeSelectOption: props => h('option', props) },
    [path.join(SRC, 'components/ui/checkbox')]: { Checkbox: ({ checked, onCheckedChange, ...props }) => h('button', { ...props, type: 'button', onClick: () => onCheckedChange(!checked) }) },
    [path.join(SRC, 'features/creative-video/media')]: {
      useVideoLibrary: () => ({ videos: [asset], query: {}, brand: 'Warm Light', product: 'Reading lamp' }), PrivateVideo: () => null,
      VideoSelect: props => h('select', { ...props, onChange: e => props.onChange(e.target.value) }, h('option', { value: '' }, 'No reference'), h('option', { value: asset.id }, 'Library video'))
    }
  } });
  const { CreativeStudio } = ui.load('src/features/creative-video/studio');
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  client.setQueryData(['creative-video-projects', 'unit'], { projects: [], provider: {} });
  const harness = createHarness(React, { shallow: type => type !== require('next/link').render });
  try {
    harness.render(h(QueryClientProvider, { client }, h(AppRouterContext.Provider, { value: { push: url => opened.push(url) } }, h(CreativeStudio, { projectId: '', referenceId: '' }))));
    assert.match(harness.container.textContent, /Warm Light · Reading lamp/);
    harness.type(harness.find('input[id="video-title"]'), 'Launch film');
    harness.type(harness.find('textarea[id="video-brief"]'), 'Introduce the lamp to night readers.');
    harness.type(harness.find('select[id="video-aspect"]'), '1:1');
    assert.equal(harness.button('Create blueprint').disabled, false);
    harness.click(harness.button('Create blueprint')); await delay(0);
    assert.equal(requests[0].referenceAssetId, null); assert.equal(requests[0].rightsConfirmed, false);
    assert.equal(requests[0].aspectRatio, '1:1'); assert.equal(opened[0], '/app/creative?project=saved');
    harness.type(harness.find('select[id="reference-video"]'), asset.id);
    assert.equal(harness.button('Analyze and create blueprint').disabled, true);
    harness.click(harness.find('button[id="reference-rights"]'));
    harness.click(harness.button('Analyze and create blueprint')); await delay(0);
    assert.equal(requests[1].referenceAssetId, asset.id); assert.equal(requests[1].rightsConfirmed, true);
    assert.notEqual(requests[0].requestId, requests[1].requestId);
  } finally { harness.cleanup(); client.clear(); }
});
