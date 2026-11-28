const test = require('node:test');
const assert = require('node:assert/strict');
const React = require('react');
const path = require('node:path');
const { createLoader, SRC } = require('./agent-ui-journeys/_load.cjs');
const { createHarness } = require('./agent-ui-client-harness.cjs');
const h = React.createElement;

function setup({ available = true, submit = async () => ({ conversationId: 'photo-chat' }) } = {}) {
  let owner = 'owner-1';
  const calls = [];
  const agent = { workspaceId: 'studio-a', status: { imageAvailable: available, canUseModel: true, manager: { available: true } },
    api: { async turn(workspaceId, request) { calls.push({ workspaceId, request }); return submit(); } } };
  const stubs = {
    'lib/auth/session': { useAuth: () => ({ user: { id: owner } }) },
    'lib/workspace/provider': { useWorkspaceApi: () => ({ workspaceId: agent.workspaceId }) },
    'lib/agent-runtime/use-agent': { useAgent: () => agent },
    'lib/api/hooks': { useSnapshot: () => ({ data: { state: { phase2: { assets: [{ id: 'brand-product', mime: 'image/png', processing: 'decoded' }] } } } }) },
    'components/application/asset-picker': { AssetPicker: ({ onValueChange, disabled }) =>
      h('button', { disabled, onClick: () => onValueChange('brand-product') }, 'Choose blue product') },
    'components/ui/button': { Button: ({ children, ...props }) => h('button', props, children) },
    'components/ui/textarea': { Textarea: props => h('textarea', props) },
    'components/ui/label': { Label: props => h('label', props) },
    'components/ui/checkbox': { Checkbox: ({ checked, disabled, onCheckedChange }) =>
      h('button', { disabled, 'aria-pressed': checked, onClick: () => onCheckedChange(!checked) }, 'Reference rights') }
  };
  const { CampaignPhoto } = createLoader({ stubs: Object.fromEntries(Object.entries(stubs).map(([k, v]) => [path.join(SRC, k), v])) })
    .load('src/features/creative-video/campaign-photo');
  const harness = createHarness(React, { shallow: type => type !== require('next/link').render });
  const scene = { sceneId: 'opening', purpose: 'Opening hook' };
  const project = { id: 'dial', revision: 3, title: 'Orbit dial launch', brief: 'A precise blue product.',
    platform: 'Instagram', aspectRatio: '9:16', scenes: [scene] };
  const render = () => harness.render(h(CampaignPhoto, { project, scene, disabled: false }));
  render();
  return { harness, calls, switchOwner() { owner = 'owner-2'; render(); } };
}

test('review and selecting a photo spend nothing; one confirmed turn carries only that reference', async () => {
  const { harness, calls } = setup();
  try {
    harness.click(harness.button('Prepare thumbnail'));
    harness.type(harness.find('textarea'), 'Show the blue dial against linen.');
    harness.click(harness.button('Choose blue product'));
    assert.equal(harness.button('Send to Image Studio').disabled, true);
    harness.click(harness.button('Reference rights'));
    assert.equal(calls.length, 0);
    harness.click(harness.button('Send to Image Studio'));
    await new Promise(resolve => setTimeout(resolve, 40));
    assert.equal(calls.length, 1);
    assert.deepEqual(calls[0].request.command, { name: 'image', args: 'Show the blue dial against linen.' });
    assert.deepEqual(calls[0].request.attachments, [{ assetId: 'brand-product', role: 'reference' }]);
    assert.equal(calls[0].workspaceId, 'studio-a');
    assert.equal(harness.findAll(node => node.type === 'button' && node.textContent === 'Send to Image Studio').length, 0);
  } finally { harness.cleanup(); }
});

test('unavailable image routes cannot submit; a change of account discards the review and attachment', () => {
  const { harness, calls, switchOwner } = setup({ available: false });
  try {
    harness.click(harness.button('Prepare product photo'));
    harness.type(harness.find('textarea'), 'Confidential draft');
    assert.equal(harness.button('Send to Image Studio').disabled, true);
    switchOwner();
    assert.ok(harness.button('Prepare product photo'));
    assert.equal(harness.findAll('textarea').length, 0);
    assert.equal(calls.length, 0);
  } finally { harness.cleanup(); }
});

test('an ambiguous send leaves a recovery message and no automatic retry', async () => {
  const { harness, calls } = setup({ submit: async () => { throw new TypeError('Disconnected'); } });
  try {
    harness.click(harness.button('Prepare product photo'));
    harness.click(harness.button('Send to Image Studio'));
    await new Promise(resolve => setTimeout(resolve, 30));
    assert.equal(calls.length, 1);
    assert.equal(harness.button('Send to Image Studio').disabled, true);
    assert.match(harness.container.textContent, /outcome is unknown/);
  } finally { harness.cleanup(); }
});
