/**
 * Lane E — the composite flow at the view level: Library selection → voice-aware draft → campaign link (applied) and
 * calendar proposal (prepared) in one conversation. Each step's view records the ordered selection the next turn
 * resolves (uiContext → ui_store.selection_context), and each write is exactly one guarded bridge request with the
 * ids picked in the step before. The server half (real handlers, real PostgreSQL) is
 * tests/phase2/postgres_agent_ui_journeys.py.
 *
 *   node --test web/tests/agent-ui-journeys/composite.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { REPO } = require('./_load.cjs');
const { makeEnvironment, bound, render, textOf } = require('./_harness.cjs');

const fixture = (name) => JSON.parse(fs.readFileSync(path.join(__dirname, 'fixtures', name), 'utf8'));
const J01 = fixture('J01-drafts.json');
const J02 = fixture('J02-calendar.json');
const J03 = fixture('J03-library.json');
const J05 = fixture('J05-campaigns.json');
const catalog = JSON.parse(fs.readFileSync(path.join(REPO, 'src/postriff_phase2/agent_runtime_v2/generated/journey-examples/journeys.json'), 'utf8'));

const toggles = (env) => env.buttons.filter((b) => b['aria-pressed'] !== undefined);
const actionButtons = (env) => env.buttons.filter((b) => b['aria-pressed'] === undefined);

test('the composite flow is indexed step by step with its examples', () => {
  const steps = catalog.composite.steps;
  assert.deepEqual(steps.map((s) => s.journey), ['J03', 'J01', 'J05', 'J05']);
  assert.equal(steps[2].outcome, 'applied');
  assert.equal(steps[3].outcome, 'prepared');
});

test('step 1 (J03): picking two Library items records them in picked order with their store types', () => {
  const env = makeEnvironment();
  const library = env.load('components/journeys/library');
  render(env, library.LibraryBrowser, { data: J03.library_search.normal, selected: bound('$selectedAssets') });
  toggles(env)[1].onClick();
  assert.deepEqual(env.selections.at(-1).items, [{ type: 'media', id: 'b'.repeat(32), title: 'Backstage City Hall' }]);
  const env2 = makeEnvironment({ store: { $selectedAssets: ['b'.repeat(32)] } });
  render(env2, env2.load('components/journeys/library').LibraryBrowser, { data: J03.library_search.normal, selected: bound('$selectedAssets') });
  toggles(env2)[0].onClick();
  assert.deepEqual(env2.selections.at(-1).items.map((i) => i.id), ['b'.repeat(32), 'a'.repeat(32)], 'the second pick comes second');
  assert.equal(env.requests.length + env2.requests.length, 0, 'selection never writes');
});

test('step 2 (J01): the new draft is picked; nothing is approved or scheduled by picking it', () => {
  const env = makeEnvironment();
  const drafts = env.load('components/journeys/drafts');
  const text = textOf(render(env, drafts.DraftList, { data: J01.drafts_list.normal, selected: bound('$selectedDrafts') }));
  toggles(env)[0].onClick();
  assert.deepEqual(env.sets.at(-1), ['$selectedDrafts', ['v_1']]);
  assert.equal(env.selections.at(-1).items[0].type, 'draft');
  assert.doesNotMatch(text, /Scheduled|Published/);
});

test('steps 3 and 4 (J05): link the picked draft (applied, verified) and prepare the Friday time (prepared, not applied)', () => {
  const env = makeEnvironment({ manifestActions: [...J05.actions, ...J02.actions], store: { $selectedDrafts: ['v_1'], $draft: 'v_1', $when: '2026-10-09T09:00', $zone: 'Asia/Hong_Kong' } });
  const campaigns = env.load('components/journeys/campaigns');
  const calendar = env.load('components/journeys/calendar');
  render(env, campaigns.CampaignLinkDrafts, { data: J05.campaign_detail.normal, actionId: 'campaign_link', drafts: bound('$selectedDrafts') }, { statementId: 'link' });
  render(env, calendar.RescheduleForm, { actionId: 'schedule_prepare', target: 'draft', targetId: bound('$draft'), when: bound('$when'), zone: bound('$zone') }, { statementId: 'form' });
  const [link, prepare] = actionButtons(env);
  link.onClick({ isTrusted: true });
  prepare.onClick({ isTrusted: true });
  assert.deepEqual(env.requests, [
    { actionId: 'campaign_link', controlId: 'link', inputs: { campaignId: 'c_51a7e', draftIds: ['v_1'] } },
    { actionId: 'schedule_prepare', controlId: 'form', inputs: { draftId: 'v_1', local: '2026-10-09T09:00', zone: 'Asia/Hong_Kong' } },
  ]);

  const result = (actionId, outcome, verified) => ({
    phase: 'done',
    request: { actionId, controlId: actionId === 'campaign_link' ? 'link' : 'form', inputs: {} },
    activation: null,
    result: { actionId, idempotencyKey: 'k'.repeat(20), outcome, verified, receiptRef: null, proposalRef: null, changedRefs: [], invalidationKeys: [], nextContext: {} },
    error: null,
  });
  const linked = makeEnvironment({ manifestActions: J05.actions, store: { $selectedDrafts: ['v_1'] } });
  linked.actionState = result('campaign_link', 'applied', true);
  const linkedText = textOf(render(linked, linked.load('components/journeys/campaigns').CampaignLinkDrafts, { data: J05.campaign_detail.normal, actionId: 'campaign_link', drafts: bound('$selectedDrafts') }, { statementId: 'link' }));
  assert.match(linkedText, /Done/);
  const unverified = makeEnvironment({ manifestActions: J05.actions, store: { $selectedDrafts: ['v_1'] } });
  unverified.actionState = result('campaign_link', 'applied', false);
  assert.match(textOf(render(unverified, unverified.load('components/journeys/campaigns').CampaignLinkDrafts, { data: J05.campaign_detail.normal, actionId: 'campaign_link', drafts: bound('$selectedDrafts') }, { statementId: 'link' })), /Not verified yet/, 'applied without a verifying re-read is not "Done"');
  const proposed = makeEnvironment({ manifestActions: J02.actions, store: { $draft: 'v_1', $when: '2026-10-09T09:00', $zone: 'Asia/Hong_Kong' } });
  proposed.actionState = result('schedule_prepare', 'prepared', false);
  const proposedText = textOf(render(proposed, proposed.load('components/journeys/calendar').RescheduleForm, { actionId: 'schedule_prepare', target: 'draft', targetId: bound('$draft'), when: bound('$when'), zone: bound('$zone') }, { statementId: 'form' }));
  assert.match(proposedText, /Prepared for review/);
  assert.doesNotMatch(proposedText, /\bDone\b/);
});
