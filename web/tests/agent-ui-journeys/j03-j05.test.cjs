/**
 * Lane E — J03 Universal Library, J04 Brand Brain / Learn My Voice, J05 Campaign planning: normal / empty / denied /
 * partial / failure states against lane D-shaped fixtures, and the guarded writes of each journey.
 *
 *   node --test web/tests/agent-ui-journeys/j03-j05.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { makeEnvironment, bound, render, textOf } = require('./_harness.cjs');

const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const J03 = fixture('J03-library.json');
const J04 = fixture('J04-voice.json');
const J05 = fixture('J05-campaigns.json');

function setup(options = {}) {
  const env = makeEnvironment(options);
  return {
    env,
    library: env.load('components/journeys/library'),
    voice: env.load('components/journeys/voice'),
    campaigns: env.load('components/journeys/campaigns'),
    tasks: env.load('components/journeys/tasks'),
  };
}
const toggles = (env) => env.buttons.filter((b) => b['aria-pressed'] !== undefined);
const actionButtons = (env) => env.buttons.filter((b) => b['aria-pressed'] === undefined);

// --- J03 -----------------------------------------------------------------------------------------------------------------
test('J03 normal: Library rows with kind, size, source/processing state and an in-app link to more; no signed URLs', () => {
  const { env, library } = setup();
  const html = render(env, library.LibraryBrowser, { data: J03.library_search.normal, selected: bound('$selectedAssets') });
  const text = textOf(html);
  assert.match(text, /Autumn recital programme\.pdf/);
  assert.match(text, /Backstage City Hall/);
  assert.match(text, /470\.8 KB/);
  assert.match(text, /Already a source/);
  assert.match(text, /Processing/);
  assert.match(text, /Pick up to 4/);
  assert.match(html, /href="\/app\/library"/, 'more results open in the Library itself');
  assert.doesNotMatch(html, /https?:\/\/[^"]*(token|signature|X-Amz)/i, 'no signed storage URL reaches the view');
  assert.doesNotMatch(html, /\/api\/workspaces\/[^"]+"/, 'preview routes are fetched by the preview component, never put in markup');
});

test('J03 selection: up to 4 picked items in order, recorded with their store type; picking never writes', () => {
  const { env, library } = setup({ store: { $selectedAssets: ['c'.repeat(32)] } });
  render(env, library.LibraryBrowser, { data: J03.library_search.normal, selected: bound('$selectedAssets') });
  toggles(env)[1].onClick();
  assert.deepEqual(env.sets.at(-1), ['$selectedAssets', ['c'.repeat(32), 'b'.repeat(32)]]);
  const recorded = env.selections.at(-1);
  assert.deepEqual(recorded.items.map((i) => i.type), ['library_file', 'media']);
  assert.equal(recorded.visible.length, 3);
  assert.equal(env.requests.length, 0);
  const full = setup({ store: { $selectedAssets: ['a', 'b', 'c', 'd'].map((x) => x.repeat(32)) } });
  render(full.env, full.library.LibraryBrowser, { data: J03.library_search.normal, selected: bound('$selectedAssets') });
  assert.equal(toggles(full.env).filter((t) => t.disabled).length, 0, 'all shown rows are already picked, so none is blocked');
});

test('J03 empty and denied are their own states', () => {
  const a = setup();
  assert.match(textOf(render(a.env, a.library.LibraryBrowser, { data: J03.library_search.empty })), /Nothing here yet/);
  const b = setup();
  assert.match(textOf(render(b.env, b.library.LibraryBrowser, { data: J03.library_search.denied })), /don’t have access/);
});

test('J03 item: bounded excerpt and passages; "Use as source" imports a needs-review source through the bridge', () => {
  const { env, library } = setup({ manifestActions: J03.actions });
  const text = textOf(render(env, library.LibraryAssetCard, { data: J03.library_item.normal, actionId: 'library_use_as_source' }));
  assert.match(text, /Programme: Chopin Ballade/);
  assert.match(text, /6 indexed passages/);
  assert.match(text, /needs your review/);
  actionButtons(env)[0].onClick({ isTrusted: true });
  assert.deepEqual(env.requests, [{ actionId: 'library_use_as_source', controlId: 's1', inputs: { assetId: 'a'.repeat(32) } }]);
});

test('J03 lineage names the stored field of each link; a selection check explains what cannot be used yet', () => {
  const a = setup();
  const lineage = textOf(render(a.env, a.library.LibraryLineage, { data: J03.library_lineage.normal }));
  assert.match(lineage, /imported as · source/);
  assert.match(lineage, /pr_library_assets\.source_id/);
  const b = setup();
  const check = textOf(render(b.env, b.library.LibrarySelectionCheck, { data: J03.library_selection.partial }));
  assert.match(check, /1 attachment/);
  assert.match(check, /1 source/);
  assert.match(check, /Use it as a source first/);
  assert.match(check, /doesn’t send or publish/);
});

// --- J04 -----------------------------------------------------------------------------------------------------------------
test('J04 samples: exact grants and the reason each excluded sample is not used', () => {
  const { env, voice } = setup();
  const text = textOf(render(env, voice.VoiceSourcePicker, { data: J04.voice_sources.normal, selected: bound('$selectedSamples') }));
  assert.match(text, /Allowed for: analysis · local-rules/);
  assert.match(text, /Not allowed for any use yet/);
  assert.match(text, /Not selected/);
  assert.match(text, /Revoked/);
  assert.match(text, /only when active, selected and granted/);
  const revokedToggle = toggles(env)[2];
  assert.equal(revokedToggle.disabled, true, 'a revoked sample cannot be picked');
});

test('J04 profile: in effect vs proposed, evidence levels, what approving affects, never "trained"', () => {
  const { env, voice } = setup({ manifestActions: J04.actions });
  const text = textOf(render(env, voice.VoiceProfileReview, { data: J04.voice_profile_state.normal, actionId: 'voice_profile_approve' }));
  assert.match(text, /In effect/);
  assert.match(text, /Proposed/);
  assert.match(text, /Supported/);
  assert.match(text, /Limited evidence/);
  assert.match(text, /marks 4 drafts for review/);
  assert.match(text, /No model was trained/);
  assert.doesNotMatch(text.replace('No model was trained', ''), /\btrained\b/i);
  actionButtons(env)[0].onClick({ isTrusted: true });
  assert.deepEqual(env.requests[0].inputs, { proposalKey: '0123456789abcdef01234567' }, 'approval is bound to the proposal shown');
  const empty = setup({ manifestActions: J04.actions });
  assert.match(textOf(render(empty.env, empty.voice.VoiceProfileReview, { data: J04.voice_profile_state.empty, actionId: 'voice_profile_approve' })), /Nothing here yet/);
  assert.equal(actionButtons(empty.env).length, 0);
});

test('J04 local analysis needs picked samples and sends exactly them', () => {
  const none = setup({ manifestActions: J04.actions });
  const t = textOf(render(none.env, none.voice.VoiceAnalyzeLocal, { actionId: 'voice_profile_analyze_local', samples: bound('$selectedSamples') }));
  assert.match(t, /no AI model and no cost/);
  assert.match(t, /Pick the samples/);
  assert.equal(actionButtons(none.env)[0].disabled, true);
  const some = setup({ manifestActions: J04.actions, store: { $selectedSamples: ['vs_1'] } });
  render(some.env, some.voice.VoiceAnalyzeLocal, { actionId: 'voice_profile_analyze_local', samples: bound('$selectedSamples') });
  actionButtons(some.env)[0].onClick({ isTrusted: true });
  assert.deepEqual(some.env.requests[0], { actionId: 'voice_profile_analyze_local', controlId: 's1', inputs: { sourceIds: ['vs_1'] } });
});

test('J04 preferences: learned vs waiting; Remember and Dismiss are two native-labelled decisions of one action', () => {
  const { env, voice } = setup({ manifestActions: J04.actions });
  const text = textOf(render(env, voice.VoicePreferenceList, { data: J04.voice_preferences.normal, actionId: 'preference_decide' }));
  assert.match(text, /Use 'recital' rather than 'concert'/);
  assert.match(text, /You changed it three times/);
  assert.match(text, /No exclamation marks/);
  const [remember, dismiss] = actionButtons(env);
  assert.match(textOf(String(remember.children)), /Remember/);
  dismiss.onClick({ isTrusted: true });
  assert.deepEqual(env.requests[0].inputs, { proposalId: '11111111-2222-4333-8444-555555555555', decision: 'dismiss' });
});

test('J04 consent per layer, learning status derived (a real 0 is 0), unavailable learning says so', () => {
  const a = setup();
  const consent = textOf(render(a.env, a.voice.VoiceConsentPanel, { data: J04.voice_consent.normal }));
  assert.match(consent, /Cloud memory Off/);
  assert.match(consent, /Web research On/);
  assert.match(consent, /1 of 3 allowed for analysis/);
  assert.match(consent, /Only an owner can change these/);
  const b = setup();
  const status = textOf(render(b.env, b.voice.VoiceLearningStatus, { data: J04.voice_learning_status.partial }));
  assert.match(status, /Only part of this could be read/);
  assert.match(status, /Edits waiting to be read 0/);
  assert.match(status, /does not record when preference extraction last ran/);
  const c = setup();
  const off = textOf(render(c.env, c.voice.VoiceLearningStatus, { data: J04.voice_learning_status.unavailable }));
  assert.match(off, /can’t be shown right now/);
  assert.match(off, /Learning records aren't available here/);
});

test('J04 pasted sample needs the explicit confirmation before it can be kept', () => {
  const { env, voice } = setup({ manifestActions: J04.actions, store: { pasted: 'A long enough paragraph of my own writing.' } });
  const html = render(env, voice.VoiceSampleImport, { actionId: 'voice_samples_import', name: 'pasted' });
  assert.match(textOf(html), /This is my own writing/);
  assert.equal(actionButtons(env)[0].disabled, true, 'unchecked confirmation keeps the action disabled');
});

// --- J05 -----------------------------------------------------------------------------------------------------------------
test('J05 plan: goal, audience, missing details, automations, derived gaps and progress each with their rule', () => {
  const { env, campaigns } = setup();
  const text = textOf(render(env, campaigns.CampaignPlan, { data: J05.campaign_detail.normal }));
  assert.match(text, /Fill the 12 October recital/);
  assert.match(text, /Still missing ticket link/);
  assert.match(text, /Weekly practice tips/);
  assert.match(text, /LinkedIn \(connected platforms none of this campaign/);
  assert.match(text, /2 drafts \(1 need review\)/);
  assert.match(text, /a campaign has no completion state of its own/);
  assert.match(text, /doesn’t record dependencies/);
});

test('J05 items and timeline: gone items flagged; planned runs and posts by day with the zone', () => {
  const a = setup();
  const items = textOf(render(a.env, a.campaigns.CampaignItems, { data: J05.campaign_items.normal }));
  assert.match(items, /No longer in the workspace/);
  assert.match(items, /Some linked items are no longer/);
  const b = setup();
  const timeline = textOf(render(b.env, b.campaigns.CampaignTimeline, { data: J05.campaign_timeline.normal }));
  assert.match(timeline, /Planned run/);
  assert.match(timeline, /Asia\/Hong_Kong/);
  assert.match(timeline, /dependencies between campaign items are not recorded/);
});

test('J05 link picked drafts: organisation only, exact campaign and drafts; nothing without drafts', () => {
  const none = setup({ manifestActions: J05.actions });
  const t = textOf(render(none.env, none.campaigns.CampaignLinkDrafts, { data: J05.campaign_detail.normal, actionId: 'campaign_link', drafts: bound('$selectedDrafts') }));
  assert.match(t, /Pick drafts first/);
  assert.equal(actionButtons(none.env)[0].disabled, true);
  const picked = setup({ manifestActions: J05.actions });
  render(picked.env, picked.campaigns.CampaignLinkDrafts, { data: J05.campaign_detail.normal, actionId: 'campaign_link', drafts: ['v_1'] });
  actionButtons(picked.env)[0].onClick({ isTrusted: true });
  assert.deepEqual(picked.env.requests[0], { actionId: 'campaign_link', controlId: 's1', inputs: { campaignId: 'c_51a7e', draftIds: ['v_1'] } });
});

test('J05 brief create and edit: inputs exactly as typed; an edit carries the version it started from', () => {
  const create = setup({ manifestActions: J05.actions, store: { briefGoal: 'Masterclass in December', briefAudience: 'Advanced students' } });
  render(create.env, create.campaigns.CampaignBriefForm, { actionId: 'campaign_create', name: 'brief' });
  actionButtons(create.env)[0].onClick({ isTrusted: true });
  assert.deepEqual(create.env.requests[0].inputs, { goal: 'Masterclass in December', audience: 'Advanced students' });
  const edit = setup({ manifestActions: J05.actions, store: { editGoal: 'Fill the recital hall', editVersion: 3 } });
  const text = textOf(render(edit.env, edit.campaigns.CampaignBriefEditor, { data: J05.campaign_detail.normal, actionId: 'campaign_update', name: 'edit' }));
  assert.match(text, /may be out of date/, 'the campaign moved to version 4 after editing began');
  actionButtons(edit.env)[0].onClick({ isTrusted: true });
  assert.equal(edit.env.requests[0].inputs.expectedVersion, 3, 'the server refuses a stale version instead of overwriting');
});

test('J05 task progress: real step states, open steps named with their reason; empty says no task', () => {
  const a = setup();
  const text = textOf(render(a.env, a.tasks.TaskProgress, { data: J05.task_progress.normal }));
  assert.match(text, /2 of 3 steps done/);
  assert.match(text, /Needs you/);
  assert.match(text, /Waiting for you to apply the proposal/);
  assert.match(text, /Checked by Rafii/);
  const b = setup();
  assert.match(textOf(render(b.env, b.tasks.TaskProgress, { data: J05.task_progress.empty })), /Nothing here yet/);
});
