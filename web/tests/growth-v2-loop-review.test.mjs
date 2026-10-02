/**
 * Review fixes for the opportunity brief and proof (F3 / findings 8, 10, 17, 18): both languages carry every key,
 * angle options always have words, a second card acts on the stored edition, errors read in the person's language,
 * focus has somewhere to go after an action, brief links open the brief, partial figures say why, figures point to
 * their records, corrections read in words, applies-from dates stay the workspace's dates, paging merges, and the
 * week view never shows a raw decision id.
 *
 *   node --test web/tests/growth-v2-loop-review.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import {
  actionTarget, angleOptions, briefCopy, briefElementId, briefFailure, briefRefreshScopes, focusAfterAction, optionLabel, wantsBrief
} from '../src/lib/growth-v2/briefs-present.ts';
import {
  appliedSummary, appliesFromText, calendarDate, correctionText, correctionValue, coverageReasons, evidenceGroups, evidenceLink, figureState, linkedProofId,
  mergeProofPages, planningText, proofCopy, proofFailure, proofLocale, serverText
} from '../src/lib/growth-v2/proof-present.ts';

function shape(value) {
  if (typeof value === 'function') return 'function';
  if (typeof value === 'string') return 'string';
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, shape(value[key])]));
}

test('English and Traditional Chinese carry the same keys, errors included', () => {
  assert.deepEqual(shape(briefCopy('zh-Hant')), shape(briefCopy('en')));
  assert.deepEqual(shape(proofCopy('zh-Hant')), shape(proofCopy('en')));
  assert.equal(proofLocale('zh-Hant-TW'), 'zh-Hant');
  assert.equal(proofLocale('zh-Hans-CN'), 'en');
});

test('every accept-form angle has words, never a raw id; long text is shortened only in the list', () => {
  const copy = briefCopy('en');
  const ids = ['3f2c9a5e-0000-4000-8000-000000000001', '3f2c9a5e-0000-4000-8000-000000000002', '3f2c9a5e-0000-4000-8000-000000000003'];
  const item = { angle: { id: ids[0], text: 'Answer the question with your own routine' },
                 action: { kind: 'accept', angleIds: ids, angles: [{ id: ids[0], text: 'Answer the question with your own routine' }, { id: ids[1], text: '  Show a\n worked example ' }, { id: ids[2], text: '' }] } };
  assert.deepEqual(angleOptions(item, copy).map((a) => a.text), ['Answer the question with your own routine', 'Show a worked example', 'Angle 3']);
  const older = { angle: item.angle, action: { kind: 'accept', angleIds: ids } };   // a server that sends only the ids
  const texts = angleOptions(older, briefCopy('zh-Hant')).map((a) => a.text);
  assert.deepEqual(texts, ['Answer the question with your own routine', '角度 2', '角度 3']);
  for (const text of texts) assert.ok(!ids.includes(text));
  assert.deepEqual(angleOptions({ angle: { id: null, text: '' }, action: { kind: 'accept' } }, copy), []);
  const long = 'word '.repeat(40);
  assert.equal(optionLabel(long).length, 90);
  assert.ok(optionLabel(long).endsWith('…'));
  assert.equal(optionLabel('Short angle'), 'Short angle');
});

test('a second card acts on the edition the first action stored, not on a digest the server must recompose', () => {
  const stored = new Map([['d1', 'edition-9']]);
  assert.deepEqual(actionTarget({ id: null, materialDigest: 'd1' }, stored), { editionId: 'edition-9' });
  assert.deepEqual(actionTarget({ id: null, materialDigest: 'd2' }, stored), { materialDigest: 'd2' });
  assert.deepEqual(actionTarget({ id: 'e1', materialDigest: 'd1' }, stored), { editionId: 'e1' });
});

test('brief errors read in the person\'s language: known codes and statuses mapped, no server English in zh-Hant', () => {
  const zh = briefCopy('zh-Hant');
  const en = briefCopy('en');
  assert.equal(briefFailure({ code: 'already_acted', status: 409, message: 'This opportunity was already acted on.' }, zh, 'zh-Hant'), '這個機會已經處理過。');
  assert.equal(briefFailure({ code: 'revision_conflict', status: 409 }, en, 'en'), en.errors.revision_conflict);
  assert.equal(briefFailure({ status: 404, message: 'Brief item unavailable.' }, zh, 'zh-Hant'), zh.errors.not_found);
  assert.equal(briefFailure({ status: 400, message: 'Choose one of this opportunity\'s angles.' }, zh, 'zh-Hant'), zh.errors.choose_angle);
  assert.equal(briefFailure({ status: 500, message: 'The workspace could not complete that request.' }, zh, 'zh-Hant'), zh.errors.generic);
  assert.equal(briefFailure({ status: 500, message: 'Something specific' }, en, 'en'), 'Something specific');
  assert.equal(briefFailure(null, en, 'en'), en.errors.generic);
});

test('after an action, focus moves to where the work now is', () => {
  const ids = (...names) => names.map((id) => ({ id }));
  // Dismissed the first of three: the item now in its place.
  assert.equal(focusAfterAction({ itemId: 'a', index: 0, action: 'dismiss' }, ids('b', 'c'), ids('a')), briefElementId('open', 'b'));
  // Saved the last one: the one before it.
  assert.equal(focusAfterAction({ itemId: 'c', index: 2, action: 'save_idea' }, ids('a', 'b'), ids('c')), briefElementId('open', 'b'));
  // Nothing open is left: the "Already handled" summary that holds it.
  assert.equal(focusAfterAction({ itemId: 'a', index: 0, action: 'not_relevant' }, [], ids('a')), 'opportunity-brief-handled');
  // Restored: the item itself, back in the open list.
  assert.equal(focusAfterAction({ itemId: 'x', index: 0, action: 'restore' }, ids('a', 'x'), []), briefElementId('open', 'x'));
  assert.equal(focusAfterAction({ itemId: 'x', index: 0, action: 'restore' }, ids('a'), ids('y')), 'opportunity-brief-handled');
  // Nothing anywhere: the brief itself (focusable).
  assert.equal(focusAfterAction({ itemId: 'a', index: 0, action: 'accept' }, [], []), 'opportunity-brief');
  assert.equal(briefElementId('open', 'bi_1"><x'), 'brief-open-bi_1x');
});

test('a brief link opens the brief; save and accept refresh what they change beyond the brief', () => {
  assert.equal(wantsBrief('?brief=1', '#opportunity-brief'), true);
  assert.equal(wantsBrief('?brief=1', ''), true);
  assert.equal(wantsBrief('', '#opportunity-brief'), true);
  assert.equal(wantsBrief('?tab=week', ''), false);
  for (const action of ['accept', 'save_idea']) assert.deepEqual(briefRefreshScopes(action, false), ['snapshot', 'trendPool', 'listening', 'radar']);
  for (const action of ['dismiss', 'not_relevant', 'restore']) assert.deepEqual(briefRefreshScopes(action, false), []);
});

test('partial and unavailable figures are labelled, with the reason', () => {
  const copy = proofCopy('en');
  assert.deepEqual(figureState('outcomes', { value: {}, dataState: 'partial', evidence: {} }, copy), { state: 'partial', label: 'Partial', reason: copy.reason.partial });
  assert.equal(figureState('providerCost', { value: {}, dataState: 'partial', evidence: {} }, copy).reason, copy.reason.cost_unsettled);
  assert.deepEqual(figureState('assistedExports', { value: null, dataState: 'unavailable', reason: 'visual_pack_unavailable', evidence: {} }, copy),
                   { state: 'unavailable', label: 'Unavailable', reason: 'Assisted exports are not available in this workspace yet' });
  assert.deepEqual(figureState('acceptedWork', { value: 3, dataState: 'available', evidence: {} }, copy), { state: 'available', label: '', reason: null });
  assert.equal(figureState('outcomes', { value: {}, dataState: 'partial', evidence: {} }, copy, 'results_unreadable').reason, 'Results could not be read');
  const counts = {
    figures: { acceptedWork: { value: 1, dataState: 'available' }, verifiedPublications: { value: 0, dataState: 'available' },
               assistedExports: { value: null, dataState: 'unavailable', reason: 'visual_pack_unavailable' }, unresolvedSlots: { value: 0, dataState: 'available' },
               outcomes: { value: {}, dataState: 'partial' }, timeBack: { value: [], dataState: 'available' }, providerCost: { value: {}, dataState: 'available' } },
    coverage: []
  };
  assert.deepEqual(coverageReasons(counts, false, copy), [
    'Assisted exports (separate): Unavailable — Assisted exports are not available in this workspace yet',
    'Outcomes by source: Partial — Some records for this period are still incomplete',
    'Late data can still arrive for this period'
  ]);
  assert.deepEqual(coverageReasons({ figures: { ...counts.figures, assistedExports: { value: {}, dataState: 'available' }, outcomes: { value: {}, dataState: 'available' } }, coverage: [] }, true, copy), []);
});

test('figures point to their records, with ids labelled in the person\'s language', () => {
  const en = proofCopy('en');
  const zh = proofCopy('zh-Hant');
  assert.deepEqual(evidenceLink({ evidenceQuery: { resource: 'results', from: 1, to: 2 } }, en), { href: '/app/analytics#business-results', label: 'Open business results' });
  assert.deepEqual(evidenceLink({ evidenceQuery: { resource: 'visual-packs', from: 1, to: 2 } }, zh), { href: '/app/library#visual-packs', label: '在素材庫開啟輪播圖組' });
  assert.equal(evidenceLink({ evidenceQuery: { resource: 'unknown', from: 1, to: 2 } }, en), null);
  assert.equal(evidenceLink({}, en), null);
  const figure = { evidence: { resultIds: ['r1', 'r2'], packIds: ['p1'], weekIds: [] } };
  assert.deepEqual(evidenceGroups(figure, en), [{ label: 'Results', ids: ['r1', 'r2'] }, { label: 'Carousels', ids: ['p1'] }]);
  assert.deepEqual(evidenceGroups(figure, zh).map((g) => g.label), ['成果', '輪播圖組']);
  assert.deepEqual(evidenceGroups(figure).map((g) => g.label), ['result ids', 'pack ids']);
});

test('revision history reads in words, never raw JSON', () => {
  const copy = proofCopy('en');
  const exports = correctionText({ figure: 'assistedExports', before: { exportReady: 1, downloaded: 0, userConfirmedUsed: 0 }, after: { exportReady: 2, downloaded: 1, userConfirmedUsed: 0 },
                                   dataStateBefore: 'partial', dataStateAfter: 'available' }, copy);
  assert.equal(exports, 'Assisted exports (separate): 1 ready · 0 downloaded · 0 confirmed used → 2 ready · 1 downloaded · 0 confirmed used (partial → available)');
  assert.equal(correctionText({ figure: 'timeBack', before: [], after: [{ confidence: 'estimated', outcomes: 1, savedSeconds: 600 }] }, copy), 'Time Back: none → 10 min estimated');
  assert.equal(correctionText({ figure: 'outcomes', before: { changed: true }, after: { changed: true } }, copy), 'Outcomes by source: changed → changed');
  assert.equal(correctionText({ figure: 'definitionVersion', before: 'rafii.proof.v2.a', after: 'rafii.proof.v2.b' }, copy), 'Definition: rafii.proof.v2.a → rafii.proof.v2.b');
  assert.equal(correctionValue('mystery', { a: 1 }, copy), 'changed');
  for (const text of [exports, correctionText({ figure: 'outcomes', before: null, after: { user_declared: { counts: { lead: 1 } } } }, proofCopy('zh-Hant'))]) {
    assert.doesNotMatch(text, /[{}[\]"]/);
  }
});

test('applies-from is the workspace\'s own date, and deciding says truthfully which week first uses it', () => {
  assert.equal(calendarDate('2026-10-05', 'en-US'), 'Oct 5, 2026');
  assert.match(calendarDate('2026-10-05', 'zh-Hant-HK'), /2026年10月5日/);
  assert.equal(calendarDate('not a date', 'en-US'), 'not a date');
  assert.equal(calendarDate('2026-10-05', 'xx-invalid-@@'), 'Oct 5, 2026');
  // Monday 00:00 in Hong Kong is Sunday 16:00 UTC: read in the proof's zone, never shifted to the viewer's.
  const mondayHk = Date.UTC(2026, 9, 4, 16) / 1000;
  assert.equal(appliesFromText({ appliesFrom: mondayHk, appliesFromDate: null }, 'Asia/Hong_Kong', 'en-US'), 'Oct 5, 2026');
  assert.equal(appliesFromText({ appliesFrom: mondayHk, appliesFromDate: '2026-10-05' }, 'America/Los_Angeles', 'en-US'), 'Oct 5, 2026');
  assert.equal(appliesFromText({ appliesFrom: null }, 'UTC', 'en-US'), null);
  assert.equal(appliesFromText({ appliesFrom: mondayHk }, 'Asia/Hong_Kong', 'xx-invalid-@@'), 'Oct 5, 2026');
  assert.equal(appliesFromText({ appliesFrom: mondayHk }, 'Not/AZone', 'en-US'), 'Oct 4, 2026');
  const en = proofCopy('en');
  assert.deepEqual(planningText({ inEffect: true, appliesFromDate: '2026-10-12', alreadyPlanned: ['2026-10-05'], note: 'server English' }, en, 'en-US'), [
    'Applies to weekly plans from the week of Oct 12, 2026.',
    'The week of Oct 5, 2026 was already planned, so it does not use this decision.'
  ]);
  assert.deepEqual(planningText({ inEffect: true, appliesFromDate: '2026-10-05', alreadyPlanned: [], note: '' }, en, 'en-US'), ['Applies to weekly plans from the week of Oct 5, 2026.']);
  assert.deepEqual(planningText({ inEffect: false, appliesFromDate: null, note: '' }, en, 'en-US'), [en.notInEffect]);
  assert.deepEqual(planningText(undefined, en), []);
  const zh = planningText({ inEffect: true, appliesFromDate: '2026-10-12', alreadyPlanned: ['2026-10-05'], note: 'server English' }, proofCopy('zh-Hant'), 'zh-Hant-HK');
  assert.match(zh[0], /^由 2026年10月12日 那一週起/);
  assert.match(zh[1], /2026年10月5日 那一週的計劃已經完成/);
  assert.doesNotMatch(zh.join(''), /server English/);
});

test('the proof\'s fixed definitions and limitations read in Traditional Chinese; English and unknown text stay as sent', () => {
  const en = proofCopy('en');
  const zh = proofCopy('zh-Hant');
  const outcomes = 'Qualified results by provenance (provider-native, first-party reported, user declared); never one blended number, unavailable is not zero.';
  assert.equal(serverText(outcomes, en), outcomes);
  assert.match(serverText(outcomes, zh), /^按來源劃分的合資格成果/);
  assert.equal(serverText(`${outcomes} Association: rafii.result-link-association.v1.`, zh).endsWith('關聯定義：rafii.result-link-association.v1。'), true);
  assert.equal(serverText('A sentence the server changed.', zh), 'A sentence the server changed.');
  assert.equal(serverText('', zh), '');
  // Every limitation the server writes today has a translation (model.LIMITATIONS).
  const model = readFileSync(new URL('../../src/postriff_phase2/proof/model.py', import.meta.url), 'utf8');
  const block = model.slice(model.indexOf('LIMITATIONS = ('), model.indexOf(')\n', model.indexOf('LIMITATIONS = (')));
  const limitations = [...block.matchAll(/"([^"]+)"/g)].map((m) => m[1]);
  assert.equal(limitations.length, 4);
  for (const text of limitations) assert.notEqual(serverText(text, zh), text, text);
});

test('decision and proof errors read in the person\'s language', () => {
  const zh = proofCopy('zh-Hant');
  assert.equal(proofFailure({ code: 'scope_widened', status: 409, message: 'An edit can narrow…' }, zh, 'zh-Hant'), zh.errors.scope_widened);
  assert.equal(proofFailure({ code: 'too_many_active_decisions', status: 409 }, zh, 'zh-Hant'), zh.errors.too_many_active_decisions);
  assert.equal(proofFailure({ status: 403, message: 'You need owner access.' }, zh, 'zh-Hant'), zh.errors.forbidden);
  assert.equal(proofFailure({ status: 502, message: 'Upstream text' }, zh, 'zh-Hant'), zh.errors.generic);
  assert.equal(proofFailure({ status: 502, message: 'Upstream text' }, proofCopy('en'), 'en'), 'Upstream text');
});

test('proof pages merge in order, each proof once, and a recomputed or linked proof is never invisible', () => {
  const proof = (id) => ({ proofId: id });
  const pages = [{ proofs: [proof('a'), proof('b')] }, { proofs: [proof('b'), proof('c')] }];
  assert.deepEqual(mergeProofPages(pages).map((p) => p.proofId), ['a', 'b', 'c']);
  assert.deepEqual(mergeProofPages(pages, proof('z')).map((p) => p.proofId), ['z', 'a', 'b', 'c']);
  assert.deepEqual(mergeProofPages(pages, proof('b')).map((p) => p.proofId), ['a', 'b', 'c']);
  assert.deepEqual(mergeProofPages(undefined, proof('z')).map((p) => p.proofId), ['z']);
  assert.equal(linkedProofId('?proof=gp_0123456789abcdef0123'), 'gp_0123456789abcdef0123');
  for (const search of ['?proof=gp_short', '?proof=javascript:alert(1)', '', '?other=1']) assert.equal(linkedProofId(search), null);
});

test('the week view shows each decision by its wording (or a description), never its id', () => {
  const copy = proofCopy('en');
  const inEffect = [{ id: 'sd_0000000000000000000a', revision: 2, kind: 'brief_topic', statement: 'One post from the saved idea', scope: {}, appliesFromDate: '2026-10-05' }];
  const summary = appliedSummary([{ id: 'sd_0000000000000000000a', revision: 2, slotIds: ['s1'] }, { id: 'sd_00000000000000000099', revision: 1, slotIds: [] }],
                                 [{ id: 'sd_0000000000000000000b', revision: 1, reason: 'week_already_planned' }, { id: 'sd_0000000000000000000c', revision: 1, reason: 'mystery_code' }],
                                 [], copy, inEffect);
  assert.deepEqual(summary.applied.map((a) => a.statement), ['One post from the saved idea', copy.unknownDecision]);
  assert.deepEqual(summary.notApplied.map((n) => n.reason), [copy.reason.week_already_planned, copy.reason.not_applied]);
  for (const entry of [...summary.applied, ...summary.notApplied]) assert.doesNotMatch(entry.statement, /sd_/);
  // The strategy list's own status wins over "in effect" (a decision revoked since planning).
  const revoked = appliedSummary([{ id: 'sd_0000000000000000000a', revision: 2, slotIds: [] }], [], [{ id: 'sd_0000000000000000000a', status: 'revoked', statement: 'Old wording' }], copy, inEffect);
  assert.equal(revoked.applied[0].revokedSince, true);
  assert.equal(revoked.applied[0].statement, 'Old wording');
});
