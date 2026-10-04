/** Tier C: real loopback Next -> Python -> PostgreSQL. No API response interception.
 * Identity, observations, destination and saved Lab draft fixtures are explicitly synthetic.
 * Lab diagnostics, linkage, edits, revisions and conflicts use the real service and database.
 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { randomUUID } = require('node:crypto');
const { chromium } = require('playwright');
const { z } = require('zod');
const t = require('./trend-contract.cjs').loadTypes();
const base = process.env.TREND_WEB_URL;
assert.ok(base && new URL(base).hostname === '127.0.0.1', 'Explicit loopback web origin required');
const out = process.env.TREND_EVIDENCE_DIR;
assert.ok(out && process.env.TREND_LIVE_SEED, 'Explicit isolated seed/evidence paths required');
const seed = JSON.parse(fs.readFileSync(process.env.TREND_LIVE_SEED, 'utf8'));
assert.equal(seed.execution, 'real_api_postgresql_synthetic_identity_and_seed');
const results = [],
  traffic = [];
const pass = (name, detail) => {
  results.push({ name, pass: true, detail });
  process.stdout.write('PASS ' + name + '\n');
};
async function checkLab({ page, row, root, api, headers, other }) {
  const ws = `/api/workspaces/${row.workspace_id}`;
  const endpoint = root + '/opportunity-lab/runs';
  const snapshot = async () => {
    const response = await api('GET', ws);
    assert.equal(response.status(), 200, await response.text());
    return response.json();
  };
  const variant = (saved) => saved.state.variants.find((v) => v.id === row.draft_id);
  const parseRun = async (response) => {
    assert.equal(response.status(), 200, await response.text());
    assert.match(response.headers()['cache-control'], /no-store/);
    return t.envelopeSchema(t.labRunSchema).parse(await response.json()).data;
  };
  const request = {
    draft_id: row.draft_id,
    draft_revision: 1,
    opportunity_id: row.opportunity_id,
    opportunity_revision: 1,
    target_platform: 'Bluesky',
    idempotency_key: randomUUID()
  };
  for (const [name, body, custom, status] of [
    ['missing token', request, { 'X-PostRiff-Request': 'founder-alpha' }, 401],
    [
      'foreign tenant',
      request,
      { ...headers, Authorization: 'Bearer dev:' + other.principal },
      404
    ],
    ['invented draft', { ...request, draft_id: randomUUID() }, headers, 404],
    ['stale draft revision', { ...request, draft_revision: 99 }, headers, 409]
  ]) {
    const response = await api('POST', endpoint, body, custom);
    assert.equal(response.status(), status, name + ': ' + (await response.text()));
    assert.match(response.headers()['cache-control'], /no-store/);
    assert.ok(!(await response.text()).includes(row.original_text));
  }
  pass(`${row.width} real Lab rejects unauthorized, unlinked and stale review inputs`);
  const before = await snapshot();
  assert.equal(variant(before).revision, 1);
  assert.equal(variant(before).text, row.original_text);
  const opResponse = await api('GET', root + '/opportunities/' + row.opportunity_id);
  assert.equal(opResponse.status(), 200);
  const op = t.envelopeSchema(t.opportunitySchema).parse(await opResponse.json()).data;
  assert.equal(op.draft_id, row.draft_id);
  assert.equal(op.source_id, row.source_id);
  assert.equal(op.context_revision, op.context_digest);
  assert.equal(variant(before).trendLineage[0].context_digest, op.context_digest);
  await page.goto(base + '/app/queue?view=drafts');
  await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
  const editor = page.getByRole('dialog');
  const lab = editor.getByRole('region', { name: 'Opportunity Lab' });
  await lab.getByRole('heading', { name: 'Opportunity Lab', exact: true }).waitFor();
  const text = editor.getByRole('textbox', { name: 'Draft text' });
  assert.equal(await text.inputValue(), row.original_text);
  assert.equal(traffic.filter((r) => r.path === endpoint && r.method === 'POST').length, 0);
  pass(
    `${row.width} server resolves accepted source and current saved draft into Lab without automatic evaluation`
  );
  const review = async (revision) => {
    const pending = page.waitForResponse(
      (r) => r.url().endsWith(endpoint) && r.request().method() === 'POST'
    );
    await lab.getByRole('button', { name: 'Review this draft', exact: true }).click();
    const response = await pending;
    const run = await parseRun(response);
    const submitted = response.request().postDataJSON();
    assert.deepEqual(
      Object.keys(submitted).toSorted(),
      Object.keys(request).toSorted(),
      'Only canonical frozen IDs and revisions'
    );
    assert.equal(submitted.draft_revision, revision);
    assert.equal(submitted.draft_id, row.draft_id);
    assert.equal(run.state, 'completed');
    assert.equal(run.draft_revision, revision);
    assert.equal(run.opportunity_id, row.opportunity_id);
    assert.equal(run.opportunity_revision, 1);
    assert.equal(run.context_revision, op.context_digest);
    assert.equal(run.trust_receipt_id, row.receipt_id);
    const finding = run.diagnostics.find((d) => d.suggested_edit);
    assert.ok(finding && !finding.requires_user_fact);
    assert.equal(finding.dimension, 'originality');
    assert.equal(finding.suggested_edit.before, row.repeated_phrase);
    assert.equal(finding.suggested_edit.after, '');
    await lab.getByText(`Review ready for saved version ${revision}.`, { exact: true }).waitFor();
    return { run, submitted, finding };
  };
  const first = await review(1);
  assert.deepEqual(
    variant(await snapshot()),
    variant(before),
    'Review must not mutate the saved draft'
  );
  const replay = await parseRun(await api('POST', endpoint, first.submitted));
  assert.equal(replay.id, first.run.id, 'Exact idempotent run replay');
  const foreignRun = await api('GET', endpoint + '/' + first.run.id, undefined, {
    ...headers,
    Authorization: 'Bearer dev:' + other.principal
  });
  assert.equal(foreignRun.status(), 404);
  pass(
    `${row.width} real durable Lab review freezes current inputs, returns exact diagnostic and replays one run`
  );
  await lab.getByText('Original wording', { exact: true }).click();
  await lab.getByText(row.repeated_phrase, { exact: true }).waitFor();
  await lab
    .locator('.trend-diagnostic')
    .filter({ hasText: first.finding.claim })
    .getByText('Evidence and comparison', { exact: true })
    .click();
  await lab.getByText('Comparison: ' + first.finding.comparison_frame, { exact: true }).waitFor();
  await page.addScriptTag({ path: require.resolve('axe-core/axe.min.js') });
  const violations = await page.evaluate(async () =>
    (
      await window.axe.run(document.querySelector('[role="dialog"]'), {
        resultTypes: ['violations']
      })
    ).violations
      .filter((v) => ['serious', 'critical'].includes(v.impact))
      .map((v) => ({ id: v.id, impact: v.impact }))
  );
  assert.deepEqual(violations, []);
  assert.ok(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1));
  await lab.getByRole('button', { name: 'Apply this edit' }).scrollIntoViewIfNeeded();
  await page.screenshot({
    path: path.join(out, `real-lab-review-${row.width}.png`),
    fullPage: false
  });
  pass(`${row.width} real Lab evidence and selective action are accessible in the existing editor`);
  await text.fill('Demo data: Unsaved change after review.');
  await lab.getByText('This check is stale', { exact: true }).waitFor();
  assert.equal(await lab.getByRole('button', { name: 'Apply this edit' }).count(), 0);
  assert.ok(await lab.getByRole('button', { name: 'Review this draft', exact: true }).isDisabled());
  assert.deepEqual(variant(await snapshot()), variant(before));
  await text.fill(row.original_text);
  await lab.getByRole('button', { name: 'Apply this edit' }).waitFor();
  pass(`${row.width} unsaved text invalidates a real Lab result without mutating the saved draft`);
  const receiptCheck = page.waitForResponse(
    (r) => r.url().endsWith(`/receipts/${row.receipt_id}`) && r.status() === 200
  );
  const opportunitiesCheck = page.waitForResponse(
    (r) => r.url().endsWith(root + '/opportunities') && r.status() === 200
  );
  const applyResponse = page.waitForResponse(
    (r) =>
      r.url().endsWith(ws + '/actions') && r.request().postDataJSON()?.action === 'variant_edit'
  );
  await lab.getByRole('button', { name: 'Apply this edit' }).click();
  await Promise.all([receiptCheck, opportunitiesCheck]);
  const applied = await applyResponse;
  assert.equal(applied.status(), 200, await applied.text());
  const submittedEdit = applied.request().postDataJSON();
  assert.deepEqual(Object.keys(submittedEdit).toSorted(), [
    'action',
    'expectedRevision',
    'payload'
  ]);
  assert.deepEqual(Object.keys(submittedEdit.payload).toSorted(), [
    'text',
    'variantId',
    'variantRevision'
  ]);
  assert.equal(submittedEdit.payload.variantRevision, 1);
  assert.equal(submittedEdit.payload.variantId, row.draft_id);
  const saved = await snapshot();
  const expectedText = row.original_text.replace(row.repeated_phrase, '').trim();
  assert.equal(variant(saved).text, expectedText);
  assert.equal(variant(saved).revision, 2);
  assert.equal(variant(saved).needsReview, true);
  assert.deepEqual(variant(saved).trendLineage, variant(before).trendLineage);
  assert.deepEqual(saved.state.phase2.jobs, before.state.phase2.jobs);
  assert.deepEqual(saved.state.phase2.reviews, before.state.phase2.reviews);
  await lab.getByText('This check is stale', { exact: true }).waitFor();
  assert.equal(
    await text.inputValue(),
    variant(saved).text,
    'Editor must use canonical server-returned text immediately'
  );
  assert.equal(
    await lab
      .getByText('Save your draft changes before checking. Any previous result is stale.', {
        exact: true
      })
      .count(),
    0,
    'No spurious dirty state after canonical save'
  );
  assert.ok(
    await lab.getByRole('button', { name: 'Review this draft', exact: true }).isEnabled(),
    'Saved canonical revision is immediately ready for another review'
  );
  assert.equal((await parseRun(await api('GET', endpoint + '/' + first.run.id))).state, 'stale');
  await page.screenshot({
    path: path.join(out, `real-lab-applied-${row.width}.png`),
    fullPage: false
  });
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
  assert.equal(await text.inputValue(), expectedText);
  pass(
    `${row.width} Lab selectively saves via existing variant_edit, rechecks evidence, preserves lineage and persists revision 2 after reload`
  );
  // Deterministic real concurrency: an independent authenticated client edits the
  // saved draft after review but before the stale browser applies its suggestion.
  await page.keyboard.press('Escape');
  const restore = await api('POST', ws + '/actions', {
    expectedRevision: (await snapshot()).revision,
    action: 'variant_edit',
    payload: { variantId: row.draft_id, variantRevision: 2, text: row.original_text }
  });
  assert.equal(restore.status(), 200, await restore.text());
  await page.reload();
  await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
  const second = await review(3);
  const concurrentText =
    'Demo data: Concurrent saved revision must survive the old Lab suggestion.';
  const concurrent = await api('POST', ws + '/actions', {
    expectedRevision: (await snapshot()).revision,
    action: 'variant_edit',
    payload: { variantId: row.draft_id, variantRevision: 3, text: concurrentText }
  });
  assert.equal(concurrent.status(), 200, await concurrent.text());
  assert.equal(
    await text.inputValue(),
    row.original_text,
    'Browser still holds the reviewed revision'
  );
  const refused = page.waitForResponse(
    (r) =>
      r.url().endsWith(ws + '/actions') && r.request().postDataJSON()?.action === 'variant_edit'
  );
  await lab.getByRole('button', { name: 'Apply this edit' }).click();
  assert.equal((await refused).status(), 409);
  await lab
    .getByText('This revision changed. Reload before continuing.', { exact: true })
    .waitFor();
  await lab
    .getByText('This revision changed. Reload before continuing.', { exact: true })
    .scrollIntoViewIfNeeded();
  const afterRace = await snapshot();
  assert.equal(variant(afterRace).text, concurrentText);
  assert.equal(variant(afterRace).revision, 4);
  assert.equal(variant(afterRace).needsReview, true);
  assert.deepEqual(variant(afterRace).trendLineage, variant(before).trendLineage);
  // Also pass a fresh workspace revision with the old variant revision, proving
  // the draft guard itself (not only the outer snapshot revision) rejects it.
  const staleVariant = await api('POST', ws + '/actions', {
    expectedRevision: afterRace.revision,
    action: 'variant_edit',
    payload: { variantId: row.draft_id, variantRevision: 3, text: expectedText }
  });
  assert.equal(staleVariant.status(), 409);
  assert.deepEqual(variant(await snapshot()), variant(afterRace));
  assert.equal((await parseRun(await api('GET', endpoint + '/' + second.run.id))).state, 'stale');
  await page.screenshot({
    path: path.join(out, `real-lab-stale-race-${row.width}.png`),
    fullPage: false
  });
  await page.keyboard.press('Escape');
  await page.reload();
  await page.getByRole('button', { name: 'Edit', exact: true }).first().click();
  assert.equal(await text.inputValue(), concurrentText);
  pass(
    `${row.width} real concurrent variant_edit makes the old Lab apply fail 409 without overwriting revision 4, including after reload`
  );
}
async function checkDismiss({ page, row, root, api, headers, other }) {
  const listing = await api('GET', root + '/opportunities');
  assert.equal(listing.status(), 200);
  const listed = t.opportunitiesResponseSchema.parse(await listing.json());
  assert.equal(typeof listed.exposure_token, 'string');
  const seen = page.waitForResponse(
    (r) => r.url().endsWith(root + '/exposures') && r.status() === 200
  );
  await page.goto(base + '/app/trends');
  const card = page.getByRole('region', { name: 'Original contribution' });
  await card.waitFor();
  await card.scrollIntoViewIfNeeded();
  const exposed = await seen;
  assert.match(exposed.headers()['cache-control'], /no-store/);
  const exposure = t.envelopeSchema(t.exposureSchema).parse(await exposed.json()).data;
  const submitted = t.exposureInputSchema.parse(exposed.request().postDataJSON());
  assert.deepEqual(submitted.eligible_candidates, [
    { opportunity_id: row.opportunity_id, revision: 1 }
  ]);
  assert.equal(exposure.event_id, submitted.event_id);
  assert.equal(exposure.measurement, 'client_reported_view');
  assert.equal(exposure.opportunity_id, row.opportunity_id);
  const replay = await api('POST', root + '/exposures', submitted);
  assert.equal(replay.status(), 200);
  const repeated = t.envelopeSchema(t.exposureSchema).parse(await replay.json()).data;
  assert.equal(repeated.exposure_id, exposure.exposure_id);
  assert.equal(repeated.existing, true);
  pass(
    `${row.width} real visible exposure validates signed returned-page subset and replays one event`
  );
  for (const [name, body, custom, expected] of [
    [
      'foreign actor',
      submitted,
      { ...headers, Authorization: 'Bearer dev:' + other.principal },
      404
    ],
    [
      'tampered page subset',
      {
        ...submitted,
        event_id: randomUUID(),
        eligible_candidates: [{ opportunity_id: randomUUID(), revision: 1 }]
      },
      headers,
      400
    ],
    [
      'client text',
      { ...submitted, event_id: randomUUID(), text: 'forbidden generic telemetry' },
      headers,
      400
    ]
  ]) {
    const response = await api('POST', root + '/exposures', body, custom);
    assert.equal(response.status(), expected, name + ': ' + (await response.text()));
    assert.match(response.headers()['cache-control'], /no-store/);
  }
  const denied = await api('POST', root + '/opportunities/' + row.opportunity_id + '/dismiss', {
    revision: 2,
    idempotency_key: randomUUID(),
    exposure_id: exposure.exposure_id
  });
  assert.equal(denied.status(), 409);
  pass(
    `${row.width} real exposure and dismissal reject foreign actor, invented candidates, text and stale revision`
  );
  const dismissed = page.waitForResponse((r) =>
    r.url().endsWith('/opportunities/' + row.opportunity_id + '/dismiss')
  );
  await card.getByRole('button', { name: 'Not relevant', exact: true }).focus();
  await page.keyboard.press('Enter');
  const response = await dismissed;
  assert.equal(response.status(), 200, await response.text());
  const result = t.envelopeSchema(t.dismissedOpportunitySchema).parse(await response.json()).data;
  assert.equal(result.state, 'dismissed');
  assert.equal(result.revision, 1);
  assert.equal(result.exposure_id, exposure.exposure_id);
  const decision = response.request().postDataJSON();
  assert.deepEqual(Object.keys(decision).toSorted(), [
    'exposure_id',
    'idempotency_key',
    'revision'
  ]);
  const status = page.getByText(
    'Marked not relevant. The conversation and its evidence remain available.',
    { exact: true }
  );
  await status.waitFor();
  assert.ok(await status.evaluate((el) => document.activeElement === el));
  await page.getByRole('heading', { name: row.title, exact: true }).waitFor();
  await page.getByRole('button', { name: 'Why should I trust this?' }).waitFor();
  await page.screenshot({ path: path.join(out, `real-dismiss-${row.width}.png`), fullPage: false });
  const again = await api(
    'POST',
    root + '/opportunities/' + row.opportunity_id + '/dismiss',
    decision
  );
  assert.equal(again.status(), 200);
  assert.equal(
    t.envelopeSchema(t.dismissedOpportunitySchema).parse(await again.json()).data.existing,
    true
  );
  await page.reload();
  await status.waitFor();
  const current = await api('GET', root + '/opportunities/' + row.opportunity_id);
  assert.equal(
    t.envelopeSchema(t.opportunitySchema).parse(await current.json()).data.state,
    'dismissed'
  );
  const workspace = await api('GET', `/api/workspaces/${row.workspace_id}`);
  const saved = await workspace.json();
  assert.deepEqual(saved.state.sources, []);
  assert.deepEqual(saved.state.variants, []);
  const refused = await api('POST', root + '/opportunities/' + row.opportunity_id + '/accept', {
    revision: 1,
    angle_id: 'synthetic-angle',
    channel_id: row.channel_id,
    goal: 'Synthetic dismissed attempt',
    idempotency_key: randomUUID(),
    exposure_id: exposure.exposure_id
  });
  assert.equal(refused.status(), 409);
  pass(
    `${row.width} real keyboard dismissal links exposure, persists after reload and creates no source or draft`
  );
}
async function checkLearning({ page, row, root, api, headers, other }) {
  const ws = `/api/workspaces/${row.workspace_id}`;
  const endpoint = root + '/learning/metric-choices';
  const snapshot = async () => { const r=await api('GET',ws);assert.equal(r.status(),200);return r.json(); };
  const read = async () => {
    const r=await api('GET',ws+'/coworker/performance');assert.equal(r.status(),200,await r.text());
    assert.match(r.headers()['cache-control']||'',/no-store/);
    return t.trendLearningSchema.parse((await r.json()).trend_learning);
  };
  const before = await snapshot();
  const statusResponse = await api('GET', ws + '/coworker/status');
  assert.equal(statusResponse.status(), 200);
  const beta = t.trendBetaStatusSchema.parse((await statusResponse.json()).trend_beta);
  assert.equal(beta.state, 'stored_radar');
  assert.equal(beta.radar_available, true);
  assert.equal(beta.acquisition, 'none');
  assert.equal(beta.follower_conversion, 'unavailable');
  assert.equal(beta.metric_reads_enabled, row.metric_reads_enabled === true);
  pass(`${row.width} actual workspace Beta status reports stored-only sources and unavailable follower conversion`);
  const descriptor = await read();
  assert.equal(descriptor.choice_options.length,1);
  fs.writeFileSync(path.join(out,`real-performance-initial-${row.width}.json`),JSON.stringify(descriptor,null,2));
  const option=descriptor.choice_options[0];
  assert.equal(option.provider,'threads');assert.equal(option.source_id,row.source_id);assert.equal(option.channel_id,row.channel_id);
  assert.deepEqual(option.metrics,['views','likes','replies','reposts','quotes','shares']);
  assert.equal(option.objectives.includes('follower_conversion'), false);
  assert.equal(option.saved_choice,null);assert.equal(descriptor.denominator.exposures,1);assert.equal(descriptor.denominator.accepted,1);
  assert.deepEqual(descriptor.outcome_states,{});assert.equal(descriptor.exposures[0].publication_coverage,'not_published');
  assert.equal(descriptor.causal,false);assert.equal(descriptor.durable_strategy,false);
  await read();assert.equal((await snapshot()).revision,before.revision);
  pass(`${row.width} actual Performance descriptor and server-native choice options; repeated GET has no writes`);
  const input={selection_digest:option.selection_digest,channel_id:option.channel_id,provider:option.provider,metric:'replies',definition_version:option.definition_version,window:'24h',objective:'conversation',denominator_metric:'views'};
  for(const [name,custom,body,status] of [
    ['missing token',{'X-PostRiff-Request':'founder-alpha'},input,401],
    ['invalid token',{...headers,Authorization:'Bearer invalid-test-token'},input,401],
    ['foreign tenant',{...headers,Authorization:'Bearer dev:'+other.principal},input,404],
    ['unknown selection',headers,{...input,selection_digest:'unknown-selection'},400],
    ['wrong provider',headers,{...input,provider:'instagram'},400],
    ['unknown definition',headers,{...input,definition_version:'unknown-definition'},400],
    ['unknown native metric',headers,{...input,metric:'viral_probability'},400],
    ['null metric',headers,{...input,metric:null},400],
    ['null denominator',headers,{...input,denominator_metric:null},400],
    ['same denominator',headers,{...input,denominator_metric:'replies'},400],
    ['free goal',headers,{...input,goal:'infer an objective'},400],
    ['unknown scope',headers,{...input,scope:'global'},400]
  ]) {
    const r=await api('POST',endpoint,body,custom);
    assert.equal(r.status(),status,`${name}: ${await r.text()}`);assert.match(r.headers()['cache-control']||'',/no-store/);
  }
  assert.equal((await snapshot()).revision,before.revision);
  pass(`${row.width} actual token/tenant/current-option/null/unknown-field refusals cause no write`);
  await page.goto(base+'/app/workspace/personalization');
  const panel=page.locator('[data-trend-learning]');await panel.waitFor();
  assert.ok(await panel.getByText('No publication outcomes are available in this report.',{exact:true}).isVisible());
  assert.ok(await panel.getByText('1 accepted idea has no linked publication yet.',{exact:true}).isVisible());
  const posts=()=>traffic.filter(r=>r.width===row.width&&r.path===endpoint&&r.method==='POST');
  assert.equal(posts().length,0);
  await panel.getByLabel('Saved idea and account',{exact:true}).selectOption({index:1});
  const form=page.getByRole('form',{name:'Trend metric choice'});
  assert.equal(await form.getByLabel('Objective',{exact:true}).inputValue(),'');
  assert.equal(await form.getByLabel('Native metric',{exact:true}).inputValue(),'');
  assert.equal(await form.getByLabel('Measurement window',{exact:true}).inputValue(),'');
  await form.getByLabel('Objective',{exact:true}).selectOption('conversation');
  await form.getByLabel('Native metric',{exact:true}).selectOption('replies');
  await form.getByLabel('Measurement window',{exact:true}).selectOption('24h');
  await form.getByLabel('Divide by another metric (optional)',{exact:true}).selectOption('views');
  assert.equal(posts().length,0);assert.equal((await snapshot()).revision,before.revision);
  pass(`${row.width} real missing outcomes stay unmeasured; browser requires explicit choices and performs no automatic POST`);
  const response=page.waitForResponse(r=>new URL(r.url()).pathname===endpoint&&r.request().method()==='POST');
  await form.getByRole('button',{name:'Save metric choice',exact:true}).focus();await page.keyboard.press('Enter');
  const savedResponse=await response;assert.equal(savedResponse.status(),200,await savedResponse.text());
  assert.deepEqual(savedResponse.request().postDataJSON(),input);
  const saved=t.trendMetricChoiceResponseSchema.parse(await savedResponse.json());
  assert.equal(saved.data.confirmed,true);assert.equal(saved.data.selected_by,row.principal);
  await page.getByText('Metric choice saved for future publications. Past results are unchanged.',{exact:true}).waitFor();
  const after=await snapshot(), refreshed=await read();
  assert.equal(after.revision,before.revision+1);
  assert.equal(refreshed.choice_options[0].saved_choice.id,saved.data.id);
  assert.deepEqual(refreshed.denominator,descriptor.denominator);assert.deepEqual(refreshed.outcome_states,descriptor.outcome_states);
  assert.deepEqual(after.state.variants,before.state.variants);assert.deepEqual(after.state.phase2.jobs,before.state.phase2.jobs);
  assert.deepEqual(after.state.sources,before.state.sources);
  assert.equal(posts().length,1);
  pass(`${row.width} real explicit metric-choice POST persisted once; no backfill/generation/publication/source mutation`);
  await page.reload();await panel.waitFor();await panel.getByText('Saved metric choices',{exact:true}).click();
  assert.ok(await panel.getByText(/replies \/ views · Conversation · 24 hours/).isVisible());
  assert.equal((await snapshot()).revision,after.revision);
  pass(`${row.width} real saved choice survives full reload with no GET writes`);
  const fixtureStage=async action=>{
    fs.writeFileSync(path.join(out,`learning-${row.width}-${action}-request.json`),JSON.stringify({workspace_id:row.workspace_id}));
    const done=path.join(out,`learning-${row.width}-${action}-done.json`), deadline=Date.now()+30000;
    while(!fs.existsSync(done)&&Date.now()<deadline){
      if(fs.existsSync(path.join(out,'learning-fixture-error.json')))throw new Error(fs.readFileSync(path.join(out,'learning-fixture-error.json'),'utf8'));
      await new Promise(r=>setTimeout(r,100));
    }
    assert.ok(fs.existsSync(done),'Explicit seed stage timed out: '+action);
    return JSON.parse(fs.readFileSync(done,'utf8')).result;
  };
  const publicationFixture=await fixtureStage('publications');
  const timed=await read(), observed=timed.exposures.flatMap(e=>e.outcomes);
  const past=observed.find(o=>o.job_id===publicationFixture.past_job), future=observed.find(o=>o.job_id===publicationFixture.future_job);
  assert.equal(past.state,'objective_unselected');assert.equal(past.value,null);assert.equal(past.objective_choice_id,undefined);
  assert.equal(future.state,'pending_horizon');assert.equal(future.value,null);assert.equal(future.objective_choice_id,saved.data.id);
  assert.equal(future.treatment_state,'unknown');assert.equal(timed.outcome_states.measured,undefined);
  assert.deepEqual(timed.choice_options[0].saved_choice,saved.data);
  fs.writeFileSync(path.join(out,`real-performance-future-${row.width}.json`),JSON.stringify(timed,null,2));
  await page.reload();await panel.waitFor();
  await page.locator('[data-post-tracking]').waitFor();
  const metricsEnabled = row.metric_reads_enabled === true;
  assert.equal(await page.getByText('Automatic metric reads are off.', {exact:true}).count(), metricsEnabled ? 0 : 1);
  const trackingResponse = await api('GET', ws + '/coworker/performance');
  const tracking = t.postTrackingSchema.parse((await trackingResponse.json()).post_tracking);
  assert.equal(tracking.enabled, metricsEnabled);
  assert.equal(tracking.posts.length, 2);
  assert.ok(tracking.posts.every(p => p.horizons.length === 4 && p.horizons.every(h => metricsEnabled
    ? !['disabled','measured'].includes(h.state) : h.state === 'disabled')));
  pass(`${row.width} actual tracking preserves four horizons and workspace admission (${metricsEnabled ? 'admitted, unmeasured' : 'disabled'}) with no provider dispatch`);
  assert.ok(await panel.getByText('Waiting for the measurement window',{exact:true}).isVisible());
  assert.ok(await panel.getByText('No prior metric choice for this window',{exact:true}).isVisible());
  assert.equal(posts().length,1);
  pass(`${row.width} explicit synthetic stored publications prove no post-hoc backfill; later publication uses saved choice but remains pending/null/meaning unknown`);

  await page.addScriptTag({path:require.resolve('axe-core/axe.min.js')});
  const violations=await page.evaluate(async()=>{const r=await axe.run(document.querySelector('[data-trend-learning]'));return r.violations.filter(v=>['serious','critical'].includes(v.impact)).map(v=>({id:v.id,targets:v.nodes.map(n=>n.target)}));});
  assert.deepEqual(violations,[]);assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth+1));
  await panel.screenshot({path:path.join(out,`real-performance-${row.width}.png`)});
  pass(`${row.width} actual Performance axe and responsive layout`);
  await fixtureStage('revoke');
  const revoked=await read();
  assert.deepEqual(revoked.choice_options,[]);assert.deepEqual(revoked.exposures,[]);assert.deepEqual(revoked.outcome_states,{});
  const refused=await api('POST',endpoint,input);assert.equal(refused.status(),400);assert.match(refused.headers()['cache-control'],/no-store/);
  await page.reload();await panel.waitFor();
  assert.ok(await panel.getByText('No current saved trend ideas are available for a metric choice.',{exact:true}).isVisible());
  assert.ok(await panel.getByText('No publication outcomes are available in this report.',{exact:true}).isVisible());
  assert.equal(await panel.getByLabel('Saved idea and account',{exact:true}).count(),0);
  fs.writeFileSync(path.join(out,`real-performance-revoked-${row.width}.json`),JSON.stringify(revoked,null,2));
  await panel.screenshot({path:path.join(out,`real-performance-revoked-${row.width}.png`)});
  pass(`${row.width} actual policy revocation removes current choices/outcomes and refuses subsequent save`);

}

async function main() {
  const browser = await chromium.launch({
    headless: true,
    ...(process.env.BROWSER_EXECUTABLE ? { executablePath: process.env.BROWSER_EXECUTABLE } : {})
  });
  try {
    for (const row of [...seed.seeds, ...seed.lab_seeds, ...seed.dismiss_seeds]) {
      const context = await browser.newContext({
        viewport: { width: row.width, height: 1000 },
        reducedMotion: 'reduce'
      });
      const other = seed.seeds.find((s) => s.principal !== row.principal);
      const root = `/api/workspaces/${row.workspace_id}/coworker/trends`;
      const headers = {
        Authorization: 'Bearer dev:' + row.principal,
        'X-PostRiff-Request': 'founder-alpha',
        Origin: base
      };
      const external = [],
        errors = [];
      // This guard only blocks external navigation. Every same-origin request continues unchanged.
      await context.route('**/*', (route) => {
        const url = new URL(route.request().url());
        if (url.origin === base) return route.continue();
        external.push(url.origin);
        return route.abort();
      });
      await context.addCookies([
        { name: 'postriff_dev', value: '1', url: base },
        { name: 'postriff_dev_principal', value: row.principal, url: base },
        { name: 'postriff_theme', value: 'rafii', url: base }
      ]);
      const tours = [
        ...fs
          .readFileSync(path.join(__dirname, '../src/features/onboarding/tours.ts'), 'utf8')
          .matchAll(/^ {2,4}id: '([a-z-]+)'/gm)
      ].map((m) => m[1]);
      await context.addInitScript(
        ({ principal, tours }) => {
          localStorage.setItem('postriff-dev-principal', principal);
          const state = JSON.stringify({
            completed: {},
            dismissed: Object.fromEntries(tours.map((t) => [t, 1])),
            nudged: Object.fromEntries(tours.map((t) => [t, 1]))
          });
          localStorage.setItem('postriff-onboarding', state);
          localStorage.setItem('postriff-onboarding:' + principal, state);
        },
        { principal: row.principal, tours }
      );
      const page = await context.newPage();
      page.setDefaultTimeout(25000);
      page.on('pageerror', (e) => errors.push(e.message));
      page.on('response', (response) => {
        const url = new URL(response.url());
        if (url.pathname.includes('/coworker/trends') || url.pathname.endsWith('/actions'))
          traffic.push({
            width: row.width,
            method: response.request().method(),
            path: url.pathname,
            status: response.status(),
            cache: response.headers()['cache-control']
          });
      });
      const api = async (method, route, data, custom = headers) =>
        context.request.fetch(base + route, { method, headers: custom, data });
      try {
        if (row.scenario === 'learning') {
          await checkLearning({ page, row, root, api, headers, other });
          assert.deepEqual(external, []);
          assert.deepEqual(errors, []);
          pass(`${row.width} real Performance has zero browser egress and runtime errors`);
          continue;
        }
        if (row.scenario === 'dismiss') {
          await checkDismiss({ page, row, root, api, headers, other });
          assert.deepEqual(external, []);
          assert.deepEqual(errors, []);
          pass(`${row.width} real dismissal has zero browser egress and runtime errors`);
          continue;
        }
        if (row.scenario === 'lab') {
          await checkLab({ page, row, root, api, headers, other });
          assert.deepEqual(external, [], 'No Lab browser egress attempts');
          assert.deepEqual(errors, [], 'No Lab browser runtime errors');
          pass(`${row.width} real Lab zero browser egress and runtime errors`);
          continue;
        }
        for (const [name, custom, endpoint, expected] of [
          ['missing token', { 'X-PostRiff-Request': 'founder-alpha' }, root, 401],
          ['invalid token', { ...headers, Authorization: 'Bearer invalid-test-token' }, root, 401],
          [
            'foreign tenant list',
            { ...headers, Authorization: 'Bearer dev:' + other.principal },
            root,
            404
          ],
          [
            'foreign tenant receipt',
            { ...headers, Authorization: 'Bearer dev:' + other.principal },
            `${root}/${row.trend_id}/receipts/${row.receipt_id}`,
            404
          ]
        ]) {
          const response = await api('GET', endpoint, undefined, custom);
          assert.equal(response.status(), expected, name);
          assert.match(response.headers()['cache-control'] || '', /no-store/);
          assert.ok(!(await response.text()).includes(row.title), 'No foreign topic disclosure');
          pass(`${row.width} ${name} denied`, { status: response.status(), no_store: true });
        }
        const denied = await api(
          'POST',
          root + '/opportunities/' + row.opportunity_id + '/accept',
          {
            revision: 1,
            angle_id: 'synthetic-angle',
            channel_id: row.channel_id,
            goal: 'Synthetic foreign attempt',
            idempotency_key: randomUUID()
          },
          { ...headers, Authorization: 'Bearer dev:' + other.principal }
        );
        assert.equal(denied.status(), 404);
        pass(`${row.width} foreign acceptance denied`, { status: denied.status() });
        const listResponse = await api('GET', root);
        assert.equal(listResponse.status(), 200);
        assert.match(listResponse.headers()['cache-control'], /no-store/);
        const list = t.envelopeSchema(z.array(t.trendSchema)).parse(await listResponse.json());
        assert.deepEqual(
          list.data.map((t) => t.id),
          [row.trend_id]
        );
        assert.equal(list.data[0].verification_state, 'verified');
        assert.equal(
          list.data[0].inferred.stage,
          null,
          'Shadow synthetic method cannot claim public stage'
        );
        pass(`${row.width} real stored list validates canonical Zod contract`);
        const receiptResponse = await api(
          'GET',
          `${root}/${row.trend_id}/receipts/${row.receipt_id}`
        );
        assert.equal(receiptResponse.status(), 200);
        const receipt = t.envelopeSchema(t.receiptSchema).parse(await receiptResponse.json());
        assert.equal(receipt.data.receipt_id, row.receipt_id);
        pass(`${row.width} real database receipt is currently verified`);
        const exposureSeen = page.waitForResponse(
          (r) => r.url().endsWith(root + '/exposures') && r.status() === 200
        );
        const receiptSeen = page.waitForResponse(
          (r) => r.url().includes('/receipts/' + row.receipt_id) && r.status() === 200
        );
        await page.goto(base + '/app/trends');
        await page.getByRole('heading', { name: row.title, exact: true }).waitFor();
        await page.getByRole('button', { name: 'Why should I trust this?' }).click();
        await receiptSeen;
        const drawer = page.getByRole('dialog');
        await drawer.getByRole('heading', { name: row.title, exact: true }).waitFor();
        await drawer
          .getByText('Synthetic stored observation for real API and database integration.', {
            exact: true
          })
          .waitFor();
        await page.screenshot({
          path: path.join(out, `real-receipt-${row.width}.png`),
          fullPage: false
        });
        await page.keyboard.press('Escape');
        await drawer.waitFor({ state: 'hidden' });
        pass(`${row.width} Radar opens real stored trust drawer`);
        await page.getByRole('region', { name: 'Original contribution' }).scrollIntoViewIfNeeded();
        const actualExposure = t
          .envelopeSchema(t.exposureSchema)
          .parse(await (await exposureSeen).json()).data;
        assert.equal(actualExposure.opportunity_id, row.opportunity_id);
        const generationResponse = page.waitForResponse(r => r.url().endsWith(`/opportunities/${row.opportunity_id}/angles`) && r.request().method() === 'POST');
        await page.getByRole('button', { name: 'Give me 3 original angles', exact: true }).click();
        const generation = await generationResponse;
        assert.equal(generation.status(), 200);
        assert.equal((await generation.json()).data.status, 'disabled');
        await page.getByText('Angle generation is not enabled for this workspace. Your saved evidence is unchanged.', { exact: true }).waitFor();
        pass(`${row.width} explicit angle request respects disabled model gate without provider calls`);
        await page.getByText('Develop this idea', { exact: true }).click();
        await page
          .getByRole('combobox', { name: /^Destination account/ })
          .selectOption(row.channel_id);
        await page
          .getByLabel('Your goal', { exact: true })
          .fill('Explain my own practice comparison');
        const acceptance = page.waitForResponse(
          (r) =>
            r.url().endsWith('/opportunities/' + row.opportunity_id + '/accept') &&
            r.request().method() === 'POST'
        );
        await page.getByRole('button', { name: 'Save to Ideas', exact: true }).click();
        const response = await acceptance;
        assert.equal(response.status(), 200, await response.text());
        const accepted = t.envelopeSchema(t.acceptedOpportunitySchema).parse(await response.json());
        assert.equal(accepted.data.verified, true);
        assert.equal(accepted.data.existing, false);
        const submitted = response.request().postDataJSON();
        assert.deepEqual(
          Object.keys(submitted).toSorted(),
          [
            'revision',
            'angle_id',
            'channel_id',
            'goal',
            'idempotency_key',
            'exposure_id'
          ].toSorted()
        );
        assert.equal(
          submitted.exposure_id,
          actualExposure.exposure_id,
          'Acceptance links the actual client-reported view'
        );
        const sourceId = accepted.data.source_id;
        await page.getByRole('link', { name: 'Review source and create original post' }).click();
        await page.waitForURL(base + '/app/ideas?source=' + encodeURIComponent(sourceId));
        const inspector =
          row.width < 1024
            ? page.getByRole('dialog')
            : page.getByRole('complementary', { name: 'Source inspector' });
        await inspector.getByText(row.title, { exact: true }).first().waitFor();
        await page.reload();
        await inspector.getByText(row.title, { exact: true }).first().waitFor();
        const workspace = await api('GET', `/api/workspaces/${row.workspace_id}`);
        assert.equal(workspace.status(), 200);
        const saved = await workspace.json();
        const source = saved.state.sources.find((s) => s.id === sourceId);
        assert.ok(source && source.active);
        assert.equal(source.origin.trendLineage.opportunity_id, row.opportunity_id);
        assert.equal(source.origin.trendLineage.trust_receipt_id, row.receipt_id);
        assert.deepEqual(saved.state.variants, [], 'No generation or publication');
        await page.screenshot({
          path: path.join(out, `real-ideas-${row.width}.png`),
          fullPage: false
        });
        pass(
          `${row.width} acceptance persists source and server lineage into existing Ideas after reload`
        );
        const replay = await api(
          'POST',
          root + '/opportunities/' + row.opportunity_id + '/accept',
          submitted
        );
        assert.equal(replay.status(), 200);
        const replayBody = t.envelopeSchema(t.acceptedOpportunitySchema).parse(await replay.json());
        assert.equal(replayBody.data.source_id, sourceId);
        assert.equal(replayBody.data.existing, true);
        pass(`${row.width} actual acceptance replay retains one source`);
        await page.goto(base + '/app/trends');
        await page.getByText('More ways to use this opportunity', { exact: true }).click();
        assert.equal(await page.getByRole('link', { name: 'Add to weekly plan', exact: true }).getAttribute('href'), `/app/weekly?tab=setup&source=${encodeURIComponent(sourceId)}`);
        assert.equal(await page.getByRole('link', { name: 'Turn into campaign', exact: true }).getAttribute('href'), `/app/automations?source=${encodeURIComponent(sourceId)}`);
        await page.getByRole('button', { name: 'Ask Rafii about this trend', exact: true }).click();
        await page.waitForFunction(id => [...document.querySelectorAll('textarea')].some(n => n.value.includes('Ideas source ' + id)), sourceId);
        pass(`${row.width} chat opens with bound source and receipt without sending`);
        // Navigation closes the staged handoff; no send, model or scheduling action.
        await page.goto(base + `/app/weekly?tab=setup&source=${encodeURIComponent(sourceId)}`);
        const sources = page.getByRole('group', { name: 'Sources for this plan', exact: true });
        await sources.waitFor();
        const choice = sources.getByRole('checkbox');
        assert.equal(await choice.isChecked(), false);
        await choice.check();
        await page.getByLabel('Goals', { exact: true }).fill('Explain my own practice comparison');
        await page.getByRole('checkbox', { name: /^Include / }).first().check();
        await page.getByLabel('Weekly drafting limit (USD)', { exact: true }).fill('0');
        const weeklySaved = page.waitForResponse(r => r.url().includes('/coworker/weekly/recipes') && r.request().method() === 'POST');
        await page.getByRole('button', { name: 'Save weekly plan', exact: true }).click();
        const weeklyResult = await weeklySaved;
        assert.equal(weeklyResult.status(), 201, await weeklyResult.text());
        const current = await (await api('GET', `/api/workspaces/${row.workspace_id}`)).json();
        const recipe = current.state.coworker.weekly.recipes.find(r => r.sourceIds.includes(sourceId));
        assert.ok(recipe);
        assert.equal(recipe.maxCostUsdMicroPerWeek, 0);
        await page.reload();
        await page.getByRole('group', { name: 'Sources for this plan', exact: true }).getByRole('checkbox', { checked: true }).waitFor();
        const weeklyEdited = page.waitForResponse(r => r.url().includes('/coworker/weekly/recipes/') && r.request().method() === 'PATCH');
        await page.getByRole('button', { name: 'Save changes', exact: true }).click();
        assert.equal((await weeklyEdited).status(), 200);
        const edited = await (await api('GET', `/api/workspaces/${row.workspace_id}`)).json();
        assert.deepEqual(edited.state.coworker.weekly.recipes.find(r => r.id === recipe.id).sourceIds, [sourceId]);
        assert.deepEqual(edited.state.variants, []);
        pass(`${row.width} Weekly saves and preserves the explicit source on edit without drafting`);
        await page.goto(base + `/app/automations?source=${encodeURIComponent(sourceId)}`);
        const campaignDialog = page.getByRole('dialog');
        await campaignDialog.waitFor();
        assert.equal(await campaignDialog.locator('#automation-goal').inputValue(), 'Explain my own practice comparison');
        await campaignDialog.getByRole('button', { name: 'Next', exact: true }).click();
        await campaignDialog.getByRole('button', { name: 'Next', exact: true }).click();
        assert.ok((await campaignDialog.innerText()).toLowerCase().includes(row.platform.toLowerCase()));
        await page.screenshot({ path: path.join(out, `real-campaign-handoff-${row.width}.png`), fullPage: false });
        pass(`${row.width} campaign builder receives the saved goal and destination for review`);

        assert.deepEqual(external, [], 'No browser egress attempts');
        assert.deepEqual(errors, [], 'No browser runtime errors');
        pass(`${row.width} zero browser egress and runtime errors`);
      } catch (error) {
        fs.writeFileSync(
          path.join(out, `real-failure-${row.scenario}-${row.width}.txt`),
          JSON.stringify({ error: String(error), errors, traffic }, null, 2) +
            '\n' +
            (await page
              .locator('body')
              .innerText()
              .catch(() => ''))
        );
        await page
          .screenshot({
            path: path.join(out, `real-failure-${row.scenario}-${row.width}.png`),
            fullPage: false
          })
          .catch(() => {});
        throw error;
      } finally {
        await context.close();
      }
    }
  } finally {
    await browser.close();
    fs.writeFileSync(
      path.join(out, 'browser-results.json'),
      JSON.stringify(
        { execution: seed.execution, trend_api_interception: false, results, traffic },
        null,
        2
      )
    );
  }
}
main().catch((error) => {
  console.error(error.stack);
  process.exitCode = 1;
});
