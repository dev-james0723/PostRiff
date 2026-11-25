"use strict";
/** Desktop-only acceptance continuation. Real UI/API/SQL, named synthetic account, future jobs with zero publication attempts. */
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { execFileSync } = require('node:child_process');
const { readFileSync } = require('node:fs');
const { resolve } = require('node:path');

async function learningAndReview({ page, api, action, snapshot, base, ws, connected, checkpoint, shot, hydrated, out, prefix }) {
  const auth = await api('GET', '/api/auth/config');
  assert.equal(auth.provider, 'dev');
  assert.equal(auth.execution, 'dev-synthetic', 'Only the declared local provider fixture may run this continuation');
  const waitRun = async initial => {
    let run = initial;
    const end = Date.now() + 30000;
    while (['queued', 'running'].includes(run.status) && Date.now() < end) {
      await new Promise(done => setTimeout(done, 100));
      run = await api('GET', ws + '/ideas/runs/' + initial.runId + '/events');
    }
    assert.equal(run.status, 'completed');
    assert.equal(run.model, 'deterministic-preview');
    assert.equal(run.usage.modelRequests, 0);
    return run;
  };
  const actionResponse = name => page.waitForResponse(response => response.request().method() === 'POST' &&
    response.url().endsWith('/actions') && response.request().postDataJSON()?.action === name);

  // F4: a current-revision fixture draft bound to the explicitly granted local Threads identity.
  const text = 'Synthetic review exercise: practise one small passage and keep one short note.';
  await action('idea', { idea: text });
  const seed = await api('POST', ws + '/ideas/quick-start', {
    expectedRevision: (await snapshot()).revision, text, ownContent: true, confirmUse: true,
    destinations: [{ platform: 'Threads', channelId: connected.connectionId, language: 'en' }],
    model: 'deterministic-preview', reasoning: 'quick', voiceMode: 'neutral', timeZone: 'UTC'
  }, 201);
  const completed = await waitRun(seed);
  await api('POST', ws + '/ideas/runs/' + seed.runId + '/apply', {
    expectedRevision: (await snapshot()).revision, artifactHash: completed.artifactHash
  });
  let state = (await snapshot()).state;
  let draft = state.variants.find(item => item.channelId === connected.connectionId && item.briefRevision === state.brief.revision);
  assert.ok(draft, 'Current factual brief has an exact-account draft');
  assert.equal(draft.voiceRevision, state.speaker.activeRevision, 'Scheduling uses the current approved voice revision');
  assert.equal(state.phase2.jobs.length, 0);
  const futureLocal = new Date(Date.now() + 24 * 60 * 60 * 1000).toISOString().slice(0, 16);
  const prepare = async () => {
    await page.goto(base + '/app/queue?view=drafts');
    const card = page.locator('[data-card-key="draft:' + draft.id + '"]');
    const schedule = card.getByRole('button', { name: 'Schedule…', exact: true });
    await hydrated(schedule); await schedule.click();
    const dialog = page.getByRole('dialog', { name: 'Schedule a draft', exact: true });
    assert.equal(await dialog.getByLabel('Account', { exact: true }).isDisabled(), true);
    await dialog.getByLabel('Publish at', { exact: true }).fill(futureLocal);
    await dialog.getByRole('checkbox', { name: /^I have the rights to publish this text/ }).check();
    const warning = dialog.getByRole('checkbox', { name: /^I acknowledge:/ });
    if (await warning.count()) await warning.check();
    const prepared = actionResponse('p2_review');
    void prepared.catch(() => {});
    await dialog.getByRole('button', { name: 'Prepare review', exact: true }).click();
    const response = await prepared; assert.equal(response.status(), 200, await response.text());
    await dialog.waitFor({ state: 'hidden' });
    state = (await snapshot()).state;
    draft = state.variants.find(item => item.id === draft.id);
    const review = state.phase2.reviews.find(item => item.status === 'needs_review' && item.manifest.variantId === draft.id);
    assert.ok(review);
    // The real OAuth handler marks verified channels live_provider even with injected DevProvider.
    // Preserve that hosted-path metadata; auth config above independently identifies this local fixture.
    assert.equal(review.manifest.schema, 'postriff.approval.v1');
    assert.equal(review.manifest.capability.source, 'live_provider');
    assert.equal(review.manifest.execution, 'hosted-live');
    assert.equal(review.manifest.workspaceId, ws.split('/').at(-1));
    assert.equal(review.manifest.channelId, connected.connectionId);
    assert.equal(review.manifest.account, connected.account);
    assert.equal(review.manifest.contentRevision, draft.revision);
    assert.equal(review.manifest.payload.text, draft.text);
    assert.equal(review.manifest.timing.local, futureLocal);
    assert.ok(Date.parse(review.manifest.timing.utc) > Date.now() + 6 * 60 * 60 * 1000, 'Never queue a due fixture post');
    assert.equal(state.phase2.jobs.length, 0);
    await page.goto(base + '/app/queue');
    await hydrated(page.getByRole('button', { name: 'Approve & schedule', exact: true }));
    return review;
  };
  const stale = await prepare();
  await shot('review-exact-manifest');
  checkpoint('Desktop real Schedule dialog freezes exact current text/revision/account/future time into the real hosted-path pending review under verified dev-synthetic runtime, with no publishing job');
  // A real concurrent edit invalidates the old visible review. No HTTP payload is mocked.
  const editedText = 'Synthetic revised review exercise. Keep one short practice note and review it tomorrow.';
  await action('variant_edit', { variantId: draft.id, variantRevision: draft.revision, text: editedText });
  const refused = actionResponse('p2_approve'); void refused.catch(() => {});
  await page.getByRole('button', { name: 'Approve & schedule', exact: true }).click();
  assert.equal((await refused).status(), 409, 'A stale visible approval must fail closed');
  state = (await snapshot()).state;
  assert.equal(state.phase2.reviews.find(item => item.id === stale.id).status, 'stale');
  assert.equal(state.phase2.jobs.length, 0);
  await page.reload();
  await page.getByRole('heading', { name: 'Queue', exact: true, level: 1 }).waitFor();
  await hydrated(page.getByRole('button', { name: 'Schedule a draft', exact: true }));
  assert.equal(await page.getByRole('button', { name: 'Approve & schedule', exact: true }).count(), 0);
  checkpoint('Desktop stale visible approval receives real HTTP 409 after a concurrent draft edit; reload removes actionable approval and no job is created');

  const fresh = await prepare();
  assert.equal(fresh.manifest.payload.text, editedText);
  assert.notEqual(fresh.digest, stale.digest);
  const approvedResponse = actionResponse('p2_approve'); void approvedResponse.catch(() => {});
  await page.getByRole('button', { name: 'Approve & schedule', exact: true }).click();
  const approved = await approvedResponse; assert.equal(approved.status(), 200, await approved.text());
  state = (await snapshot()).state;
  assert.equal(state.phase2.reviews.find(item => item.id === fresh.id).status, 'approved');
  assert.equal(state.phase2.jobs.length, 1);
  const job = state.phase2.jobs[0];
  assert.equal(job.approvalDigest, fresh.digest);
  assert.deepEqual(job.manifest, fresh.manifest);
  assert.equal(job.state, 'scheduled'); // The approval command's event() advances the new job immediately.
  assert.equal(job.attempts.length, 0);
  assert.ok(job.nextAt > Date.now() / 1000 + 6 * 60 * 60);
  assert.ok(!job.url && !job.providerConfirmed && !job.verification, 'No verified publication exists');
  await page.reload();
  await page.getByRole('button', { name: 'Open details for the Threads post', exact: true }).waitFor();
  const persisted = (await snapshot()).state.phase2.jobs.find(item => item.id === job.id);
  assert.equal(persisted.approvalDigest, fresh.digest);
  assert.equal(persisted.attempts.length, 0);
  await shot('queue-approved-future');
  checkpoint('Desktop explicit Approve & schedule persists one exact-digest future synthetic queue job across reload; zero publication attempts and no publication receipt');

  await page.goto(base + '/app/account/privacy');
  const exportButton = page.getByRole('button', { name: 'Export drafts', exact: true });
  await hydrated(exportButton);
  const downloadEvent = page.waitForEvent('download'); void downloadEvent.catch(() => {});
  const exportReceipt = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/data-requests'));
  void exportReceipt.catch(() => {});
  await exportButton.click();
  const receiptResponse = await exportReceipt; assert.ok(receiptResponse.ok(), await receiptResponse.text());
  const receipt = await receiptResponse.json();
  assert.equal(receipt.kind, 'export'); assert.equal(receipt.status, 'completed');
  assert.match(receipt.receipt.sha256, /^[a-f0-9]{64}$/);
  const download = await downloadEvent; assert.equal(await download.failure(), null);
  const zipPath = resolve(out, prefix + '-draft-export-desktop.zip');
  await download.saveAs(zipPath);
  const bytes = readFileSync(zipPath); assert.equal(bytes.subarray(0, 2).toString(), 'PK');
  const digest = createHash('sha256').update(bytes).digest('hex');
  const exportSection = page.getByRole('region', { name: 'Export', exact: true });
  await exportSection.getByRole('button', { name: 'Copy the fingerprint', exact: true }).waitFor();
  assert.equal((await exportSection.locator('code').innerText()).replace(/\s/g, ''), digest);
  const entries = execFileSync('/usr/bin/unzip', ['-Z1', zipPath], { encoding: 'utf8', maxBuffer: 1024 * 1024 }).trim().split('\n');
  assert.ok(entries.includes('phase2/workspace.json') && entries.includes('README.txt'));
  assert.ok(!entries.some(name => /(^|\/)(?:\.env|credentials?|secrets?|access[-_]?tokens?|refresh[-_]?tokens?)(?:\.|\/|$)/i.test(name)));
  const exported = JSON.parse(execFileSync('/usr/bin/unzip', ['-p', zipPath, 'phase2/workspace.json'], { encoding: 'utf8', maxBuffer: 10 * 1024 * 1024 }));
  const exportedDraft = exported.variants.find(item => item.id === draft.id);
  assert.equal(exportedDraft.text, editedText); assert.equal(exportedDraft.revision, draft.revision);
  assert.equal(exported.phase2.reviews.find(item => item.id === fresh.id).digest, fresh.digest);
  const assertNoSecrets = value => {
    if (!value || typeof value !== 'object') return;
    for (const [key, child] of Object.entries(value)) {
      assert.ok(!/^(?:access_?token|refresh_?token|private_?key|client_?secret|password)$/i.test(key), 'Export omits credential keys: ' + key);
      assertNoSecrets(child);
    }
  };
  assertNoSecrets(exported);
  const requests = await api('GET', ws + '/data-requests');
  assert.ok(requests.requests.some(item => item.requestId === receipt.requestId && item.kind === 'export' && item.status === 'completed'));
  await shot('privacy-draft-export');
  checkpoint('Desktop privacy Export drafts downloads real ZIP with exact revised draft/approval, matches browser SHA-256 fingerprint, records completed data request, and excludes credential artifacts');

  // L1: only an empty conversation is seeded. All standing-instruction/one-off decisions use the real composer.
  const openXConversation = async title => {
    const created = await api('POST', ws + '/ideas/conversations', { title }, 201);
    await page.goto(base + '/app/agent/' + created.conversationId);
    const message = page.getByLabel('Message', { exact: true }); await hydrated(message);
    const delivery = page.locator('button[aria-label^="Delivery."]');
    await delivery.click();
    const planner = page.getByRole('dialog');
    await planner.getByRole('heading', { name: 'Publish to', exact: true }).waitFor();
    if (await planner.getByRole('button', { name: 'Remove X from delivery', exact: true }).count() === 0) {
      await planner.getByRole('button', { name: 'Add channel', exact: true }).click();
      await planner.getByRole('region', { name: 'Available channels', exact: true }).getByRole('button', { name: 'X Draft only', exact: true }).click();
    }
    const removalNames = await planner.getByRole('button', { name: /^Remove .+ from delivery$/ })
      .evaluateAll(elements => elements.map(element => element.getAttribute('aria-label')));
    for (const name of removalNames) {
      if (name !== 'Remove X from delivery') await planner.getByRole('button', { name, exact: true }).click();
    }
    await planner.getByRole('button', { name: 'Apply delivery', exact: true }).click();
    await planner.waitFor({ state: 'hidden' });
    const voice = page.getByRole('button', { name: /^(Writing like me|Neutral override)/ });
    assert.equal(await voice.isEnabled(), true, 'The manually approved fixture profile is usable by the local fixture writer');
    if (await voice.getAttribute('aria-pressed') !== 'true') await voice.click();
    assert.equal(await voice.getAttribute('aria-pressed'), 'true');
    return { conversationId: created.conversationId, message };
  };
  const send = async (conversation, text) => {
    const responseEvent = page.waitForResponse(response => response.request().method() === 'POST' &&
      response.url().endsWith('/ideas/conversations/' + conversation.conversationId + '/turns'));
    void responseEvent.catch(() => {});
    await conversation.message.fill(text);
    await page.getByRole('button', { name: 'Send', exact: true }).click();
    const response = await responseEvent; assert.ok(response.ok(), await response.text());
    const input = response.request().postDataJSON();
    assert.equal(input.model, 'deterministic-preview'); assert.equal(input.voiceMode, 'personalized');
    assert.deepEqual(input.destinations.map(item => item.platform), ['X']);
    return response.json();
  };
  const before = await api('GET', ws + '/memory');
  const standing = await openXConversation('Synthetic standing preference acceptance');
  const pending = await send(standing, 'Remember no hashtags on x');
  assert.equal(pending.status, 'memory'); assert.equal(pending.runId, null);
  assert.equal(pending.usage.modelRequests, 0); assert.equal(pending.usage.costUsd, 0);
  assert.equal(pending.memoryProposal.scope.platform, 'X');
  const proposal = page.locator('[data-proposal="' + pending.memoryProposal.id + '"]');
  await proposal.getByRole('button', { name: 'Remember this', exact: true }).waitFor();
  assert.equal(await proposal.getByRole('button', { name: 'Only for this post', exact: true }).count(), 0, 'Unbound chat preferences have no fake post-only target');
  const pendingMemory = await api('GET', ws + '/memory');
  assert.equal(pendingMemory.learning.revision, before.learning.revision);
  assert.deepEqual(pendingMemory.learning.items, before.learning.items);
  assert.equal(pendingMemory.files.find(item => item.name === 'VOICE.md').body, before.files.find(item => item.name === 'VOICE.md').body);
  await shot('learning-pending');
  checkpoint('Desktop real chat standing instruction creates an X-scoped pending proposal without run, model call, cost, active preference or VOICE.md mutation');
  const decision = page.waitForResponse(response => response.request().method() === 'POST' && response.url().endsWith('/memory/proposals/' + pending.memoryProposal.id + '/decide'));
  void decision.catch(() => {});
  await proposal.getByRole('button', { name: 'Remember this', exact: true }).click();
  const decided = await decision; assert.ok(decided.ok(), await decided.text());
  await proposal.getByText('Remembered. Applies to new drafts.', { exact: true }).waitFor();
  await page.goto(base + '/app/workspace/memory');
  const memory = await api('GET', ws + '/memory');
  const accepted = memory.learning.items.find(item => item.status === 'active' && item.scope.platform === 'X' && item.ruleKey === pending.memoryProposal.ruleKey);
  assert.ok(accepted); assert.equal(accepted.statement, pending.memoryProposal.statement);
  assert.ok(memory.learning.revision > before.learning.revision);
  assert.ok(memory.files.find(item => item.name === 'VOICE.md').body.includes(accepted.statement));
  const memoryRow = page.locator('li').filter({ has: page.getByText(accepted.statement, { exact: true }) });
  await memoryRow.getByRole('button', { name: 'Pause', exact: true }).waitFor();
  await page.reload(); await memoryRow.getByRole('button', { name: 'Pause', exact: true }).waitFor();
  await shot('learning-remembered');
  await page.screenshot({ path: resolve(out, prefix + '-learning-review.jpg'), type: 'jpeg', quality: 45 });
  checkpoint('Desktop explicit Remember this persists an active X preference and canonical VOICE.md; the real Memory page reload shows the accepted wording and pause control');
  const baseline = await api('GET', ws + '/memory/proposals');
  const once = await openXConversation('Synthetic one-off preference and memory reuse');
  const oneOff = await waitRun(await send(once, 'For this draft, no emoji on X. Write a short note about a synthetic five-minute practice habit.'));
  assert.ok(oneOff.usage.memoryBindings.used.includes(accepted.id), 'Fresh personalized fixture request actually binds the accepted item');
  const after = await api('GET', ws + '/memory/proposals');
  assert.equal(after.learning.revision, baseline.learning.revision);
  assert.deepEqual(after.learning.items, baseline.learning.items);
  assert.deepEqual(after.versions, baseline.versions);
  assert.deepEqual(after.pending, baseline.pending);
  assert.equal(await page.locator('[data-proposal]').count(), 0, 'This one-off instruction cannot offer a Remember card');
  await shot('learning-one-off-fresh-request');
  checkpoint('Desktop fresh personalized X conversation binds the accepted hashtag preference; one-off no-emoji drafting completes locally without a new preference/version/proposal or Remember card; no voice-quality claim');
}
module.exports = { learningAndReview };
