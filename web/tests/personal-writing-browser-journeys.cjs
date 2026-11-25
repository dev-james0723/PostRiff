'use strict';
/** Real local handlers and disposable SQL; fixture drafts/providers only. No campaign activation or live send; desktop approval covers only a future synthetic job. */
const assert = require('node:assert/strict');
const { resolve } = require('node:path');
const { readFileSync } = require('node:fs');

async function personalWritingJourneys({ page, api, action, snapshot, base, ws, engineName, width, record, out, prefix, hydrated }) {
  const shot = name => page.screenshot({ path: resolve(out, prefix + '-' + name + '-' + engineName + '-' + width + '.png'), fullPage: true });
  const checkpoint = check => record({ engine: engineName, width, check, realProviderE2E: false, personalVoiceAcceptance: false });

  // S1: this opt-in belongs only to the local candidate process, never a production flag change.
  if (process.env.RAFII_CREATION_ALL_PLATFORMS_ENABLED === '1') {
    const registry = JSON.parse(readFileSync(resolve(__dirname, '../../skills/rafii-registry.json'), 'utf8'));
    const expected = [...new Set(registry.capabilities.filter(item => item.id.startsWith('postriff-channel-')).flatMap(item => item.platforms))].sort();
    assert.equal(expected.length, 33, 'Reconcile the installed platform inventory before changing acceptance');
    const catalog = await api('GET', '/api/ideas/models');
    assert.deepEqual([...catalog.creation.draftable].sort(), expected);
    await page.goto(base + '/app');
    const picker = page.getByRole('button', { name: 'Choose channels, 0 accounts selected', exact: true });
    await hydrated(picker); await picker.click();
    const platforms = page.getByRole('dialog', { name: /Where should it/ });
    assert.equal(await platforms.getByRole('checkbox').count(), 33);
    for (const platform of expected) {
      assert.equal(await platforms.getByRole('checkbox').filter({ has: page.getByText(platform, { exact: true }) }).count(), 1, platform + ' is reachable');
    }
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
    await shot('platforms-all33');
    await page.keyboard.press('Escape'); await platforms.waitFor({ state: 'hidden' });
    checkpoint('Task-local all-platform rollout exposes the exact 33 installed channel skills through the real models API and Home Platforms-only dialog; no publication support is implied');
  }

  // F5: save and edit a two-platform plan through the actual builder, without activating it.
  const title = 'Synthetic practice plan ' + engineName + ' ' + width;
  await page.goto(base + '/app/automations');
  const create = page.getByRole('button', { name: 'New automation', exact: true }).first();
  await hydrated(create); await create.click();
  const builder = page.getByRole('dialog', { name: /automation/i }).first();
  await builder.getByLabel('Name', { exact: true }).fill(title);
  await builder.getByLabel('What should each draft be about?', { exact: true }).fill('Synthetic practice reflections');
  await builder.getByLabel('Who is it for?', { exact: true }).fill('Synthetic beginner musicians');
  await builder.getByRole('tab', { name: /Where/ }).click();
  const where = builder.getByRole('tabpanel', { name: 'Where', exact: true });
  await where.getByRole('button', { name: 'LinkedIn', exact: true }).click();
  await where.getByRole('button', { name: 'Threads', exact: true }).click();
  await builder.getByRole('tab', { name: /Review/ }).click();
  await builder.getByLabel('Writer', { exact: true }).selectOption('deterministic-preview');
  await builder.getByLabel('Cost limit per run (USD)', { exact: true }).fill('0');
  await builder.getByRole('button', { name: 'Save as draft', exact: true }).click();
  await builder.waitFor({ state: 'hidden' });
  const card = page.locator('article').filter({ has: page.getByRole('heading', { name: title, exact: true }) });
  await card.waitFor();
  await page.reload();
  await hydrated(card.getByRole('button', { name: 'Edit', exact: true }));
  await card.getByRole('button', { name: 'Edit', exact: true }).click();
  const editPlan = page.getByRole('dialog', { name: /automation/i }).first();
  assert.equal(await editPlan.getByLabel('What should each draft be about?', { exact: true }).inputValue(), 'Synthetic practice reflections');
  await editPlan.getByLabel('What should each draft be about?', { exact: true }).fill('Synthetic practice reflections reviewed');
  await editPlan.getByRole('tab', { name: /Review/ }).click();
  await editPlan.getByRole('button', { name: 'Save as draft', exact: true }).click();
  await editPlan.waitFor({ state: 'hidden' });
  let current = (await snapshot()).state;
  const task = current.raffi.campaignPlanning.recurringTasks.find(item => item.name === title);
  assert.ok(task, 'UI saved an actual recurring-plan row');
  assert.equal(task.status, 'draft', 'Saving a plan cannot activate it');
  assert.equal(task.route, 'deterministic-preview');
  assert.equal(task.maxCostUsdMicro, 0);
  assert.deepEqual(task.destinations.map(item => item.platform).sort(), ['LinkedIn', 'Threads']);
  const campaign = current.raffi.campaignPlanning.campaigns.find(item => item.id === task.campaignId);
  assert.equal(campaign.goal, 'Synthetic practice reflections reviewed');
  assert.ok(campaign.version >= 2);
  assert.equal(current.phase2.jobs.length, 0);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await shot('campaign-draft');
  checkpoint('Two-platform campaign plan saved, reloaded and edited through the real UI/API; remains draft with zero cost limit and no published/scheduled job');

  // F6 prerequisites use actual existing APIs. The supported deterministic writer supplies explicitly synthetic seed data.
  const brief = 'Synthetic workshop planning: explain one small practice habit. No dates or achievements supplied.';
  await action('idea', { idea: brief });
  const generated = await api('POST', ws + '/ideas/quick-start', {
    expectedRevision: (await snapshot()).revision, text: brief, ownContent: true, confirmUse: true,
    destinations: [{ platform: 'LinkedIn', language: 'en' }], model: 'deterministic-preview',
    reasoning: 'quick', voiceMode: 'neutral', timeZone: 'UTC'
  }, 201);
  let ready = generated;
  const readyDeadline = Date.now() + 30000;
  while (['queued', 'running'].includes(ready.status) && Date.now() < readyDeadline) {
    await new Promise(done => setTimeout(done, 100));
    ready = await api('GET', ws + '/ideas/runs/' + generated.runId + '/events');
  }
  assert.equal(ready.status, 'completed', 'Supported deterministic writer completed the seed draft');
  assert.ok(ready.artifactHash);
  await api('POST', ws + '/ideas/runs/' + generated.runId + '/apply', {
    expectedRevision: (await snapshot()).revision, artifactHash: ready.artifactHash
  });
  const started = await api('POST', ws + '/channels/threads/oauth/start', { capability: 'publish' }, 201);
  assert.equal(new URL(started.authorizeUrl).origin, base, 'Only the fixture consent origin is permitted');
  const connected = await api('POST', ws + '/channels/threads/oauth/complete', {
    state: new URL(started.authorizeUrl).searchParams.get('state'), code: 'browser-publish-scope-fixture'
  });
  assert.equal(connected.connected, true);
  assert.equal(connected.capabilities.publish.level, 'Direct', 'The named local fixture reports an explicit synthetic grant');
  await action('raffi_suggestion_refresh');
  current = (await snapshot()).state;
  const fixtureChannel = current.phase2.channels.find(item => item.id === connected.connectionId);
  assert.ok(fixtureChannel?.configured && fixtureChannel.identityVerified && fixtureChannel.capabilityVerified &&
    !fixtureChannel.revoked && fixtureChannel.expiresAt > Date.now() / 1000, 'Actual readiness checks accept only the declared synthetic grant');
  assert.ok(current.variants.some(item => item.briefRevision === current.brief.revision), 'Applied draft belongs to the current factual brief');
  const suggestion = current.raffi.suggestions.find(item => item.kind === 'missing_variant' && item.evidence[0]?.id === connected.connectionId);
  assert.ok(suggestion, 'Actual suggestion engine found the uncovered synthetic account');
  const before = { variants: current.variants.length, runs: current.runs.length, jobs: current.phase2.jobs.length };
  const writes = [];
  const observe = request => {
    if (request.method() === 'POST' && new URL(request.url()).origin === base) {
      let body; try { body = request.postDataJSON(); } catch {}
      writes.push({ path: new URL(request.url()).pathname, action: body?.action });
    }
  };
  page.on('request', observe);
  try {
    await page.goto(base + '/app');
    const message = page.getByLabel('Message', { exact: true });
    await hydrated(message);
    await page.getByRole('button', { name: 'Review: ' + suggestion.reason, exact: true }).click();
    await page.waitForURL(url => url.pathname === '/app' && url.searchParams.get('suggestion') === suggestion.id);
    const review = page.locator('[aria-label="Suggested draft"]');
    await review.getByText(brief, { exact: true }).waitFor();
    await review.getByText('Draft for Threads · ' + connected.account, { exact: true }).waitFor();
    const load = review.getByRole('button', { name: 'Use suggested brief and account', exact: true });
    assert.equal(await message.inputValue(), '', 'Reviewing a suggestion does not overwrite the composer');
    await message.fill('A separate unfinished synthetic idea.');
    assert.equal(await load.isDisabled(), true);
    assert.equal(await message.inputValue(), 'A separate unfinished synthetic idea.');
    await review.getByText(/Your unfinished idea is kept/).waitFor();
    await shot('suggestion-protected');
    await message.fill('');
    // Delay only delivery of a real, unmodified accept response. The authenticated handler still runs.
    let releaseResponse;
    const deliveryGate = new Promise(done => { releaseResponse = done; });
    let responseReady, responseFailed;
    const backendReady = new Promise((done, failed) => { responseReady = done; responseFailed = failed; });
    let captured = false;
    const holdAcceptance = async route => {
      const request = route.request();
      if (captured || request.method() !== 'POST' || new URL(request.url()).origin !== base ||
          request.postDataJSON()?.action !== 'raffi_suggestion_accept') return route.fallback();
      captured = true;
      try {
        const response = await route.fetch();
        responseReady(response.status());
        await deliveryGate;
        await route.fulfill({ response });
      } catch (error) {
        responseFailed(error);
        throw error;
      }
    };
    await page.route('**/actions', holdAcceptance);
    let waitTimer;
    try {
      await load.click();
      const status = await Promise.race([backendReady, new Promise((_, reject) => {
        waitTimer = setTimeout(() => reject(new Error('Real suggestion acceptance did not reach the held-response checkpoint')), 30000);
      })]);
      clearTimeout(waitTimer);
      assert.equal(status, 200);
      const otherId = 'synthetic-unavailable-suggestion';
      await page.evaluate(id => history.pushState(null, '', '/app?new=1&suggestion=' + id), otherId);
      await review.getByText(/This suggestion is no longer available here/).waitFor();
      releaseResponse();
      await page.getByText('Your idea changed while this suggestion was loading. It has been kept.', { exact: true }).waitFor();
      assert.equal(new URL(page.url()).searchParams.get('suggestion'), otherId);
      assert.equal(await message.inputValue(), '');
      checkpoint('A delayed real server acceptance cannot overwrite a newer same-workspace suggestion URL or composer state; the changed input is explicitly kept');
    } finally {
      clearTimeout(waitTimer);
      releaseResponse();
      await page.unroute('**/actions', holdAcceptance);
    }
    await page.goto(base + '/app?new=1&suggestion=' + encodeURIComponent(suggestion.id));
    await review.getByText(brief, { exact: true }).waitFor();
    await hydrated(load);
    const accepted = page.waitForResponse(response => response.request().method() === 'POST' &&
      response.url().endsWith('/actions') && response.request().postDataJSON()?.action === 'raffi_suggestion_accept');
    await load.focus(); await page.keyboard.press('Enter');
    const saved = await accepted; assert.ok(saved.ok(), await saved.text());
    await page.waitForURL(url => !url.searchParams.has('suggestion'));
    await page.waitForFunction(text => document.querySelector('textarea[aria-label="Message"]')?.value === text, brief);
    await page.getByRole('button', { name: 'Choose channels, 1 account selected', exact: true }).waitFor();
    const chosen = await page.evaluate(workspaceId => JSON.parse(sessionStorage.getItem('rafii.destinations.' + workspaceId)), ws.split('/').at(-1));
    assert.deepEqual(chosen.selected, [connected.connectionId]);
    assert.deepEqual(chosen.platformOnly, []);
    current = (await snapshot()).state;
    assert.deepEqual({ variants: current.variants.length, runs: current.runs.length, jobs: current.phase2.jobs.length }, before);
    const acceptedItem = current.raffi.suggestions.find(item => item.id === suggestion.id);
    assert.equal(acceptedItem.actionRef.targetId, connected.connectionId);
    assert.equal(acceptedItem.actionRef.targetRevision, current.brief.revision);
    assert.equal(acceptedItem.actionRef.authority, 'open_for_review');
    await shot('suggestion-loaded');
    checkpoint('Suggestions Review preserves exact brief/account into an opaque-ID review card; protects unfinished text; keyboard-confirmed load revalidates server evidence without generation or publishing');

    // A fresh URL cannot reactivate a suggestion whose factual brief changed.
    await action('idea', { idea: brief + ' The brief has now changed.' });
    await page.goto(base + '/app?new=1&suggestion=' + encodeURIComponent(suggestion.id));
    await page.locator('[aria-label="Suggested draft"]').getByText(/This suggestion is no longer available here/).waitFor();
    assert.equal(await page.getByRole('button', { name: 'Use suggested brief and account', exact: true }).count(), 0);
    assert.equal(await message.inputValue(), '');
    assert.deepEqual(writes.filter(item => /\/ideas\/quick-start$|\/turns$|\/publish$|\/approve$/.test(item.path) ||
      ['generate', 'adapt', 'p2_approve', 'raffi_run_commit'].includes(item.action)), []);
    checkpoint('Stale suggestion URL refuses changed brief and cannot load or silently start a model/publishing action');
  } finally {
    page.off('request', observe);
  }

  // F4 bounded evidence: a real Queue edit changes only the exact saved draft revision.
  current = (await snapshot()).state;
  const variant = current.variants[0];
  const beforeReview = { reviews: current.phase2.reviews, jobs: current.phase2.jobs };
  await page.goto(base + '/app/queue?view=drafts');
  const draft = page.locator('[data-card-kind="draft"][data-card-key="draft:' + variant.id + '"]');
  await hydrated(draft.getByRole('button', { name: 'Edit', exact: true }));
  await draft.getByRole('button', { name: 'Edit', exact: true }).click();
  const editDraft = page.getByRole('dialog', { name: /^Edit draft/ });
  const replacement = 'Synthetic review edit. Practise one small passage and keep a short note.';
  await editDraft.getByLabel('Draft text', { exact: true }).fill(replacement);
  await editDraft.getByRole('button', { name: 'Save draft', exact: true }).click();
  await editDraft.waitFor({ state: 'hidden' });
  await page.reload(); await draft.waitFor();
  current = (await snapshot()).state;
  const revised = current.variants.find(item => item.id === variant.id);
  assert.equal(revised.text, replacement);
  assert.equal(revised.revision, variant.revision + 1);
  assert.equal(revised.needsReview, true);
  assert.deepEqual({ reviews: current.phase2.reviews, jobs: current.phase2.jobs }, beforeReview);
  assert.equal(await page.evaluate(() => document.documentElement.scrollWidth > innerWidth), false);
  await shot('queue-draft-edited');
  checkpoint('Real Queue draft edit survives reload, increments exact revision and requires review; does not create an approval, schedule or publish job');
  if (engineName === 'chromium' && width === 1440) {
    await require('./personal-writing-learning-review.cjs').learningAndReview({
      page, api, action, snapshot, base, ws, connected, checkpoint, shot, hydrated, out, prefix
    });
  }
}
module.exports = { personalWritingJourneys };
