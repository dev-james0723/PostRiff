/**
 * G4-LOOP presentation (src/lib/growth-v2/briefs-present.ts, proof-present.ts): EN + zh-Hant copy, at most three brief
 * items, stored-only labelling, honest unknown/unavailable states, separate assisted exports, Time Back classes and
 * unknown cost, owner-only decisions and the week's applied/not-applied summary.
 *
 *   node --test web/tests/growth-v2-loop.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { actionTarget, briefCopy, coverageLine, coverageNote, decisionLabel, handledItems, itemStatus, loopLocale, outcomeSourceId, relevanceText, safeHref, timeLine, visibleItems } from '../src/lib/growth-v2/briefs-present.ts';
import { appliedSummary, correctionText, decisionActions, evidenceGroups, figureText, FIGURE_ORDER, proofCopy, scopeText, usd } from '../src/lib/growth-v2/proof-present.ts';

const item = (extra = {}) => ({ id: 'bi_1', source: 'listening', kind: 'question', title: 'How do adults keep a routine?', publishedAt: null, retrievedAt: 1_790_000_000,
  coverage: { availability: 'available', completeness: 'partial' }, decision: null, ...extra });

test('locale (D-022): Traditional Chinese only for zh-Hant, zh-TW, zh-HK, zh-MO and Cantonese; other Chinese reads English', () => {
  assert.equal(loopLocale('en-GB'), 'en');
  assert.equal(loopLocale(undefined), 'en');
  for (const tag of ['zh-Hant', 'zh-Hant-HK', 'zh-TW', 'zh-HK', 'zh-MO', 'zh_TW', 'yue', 'yue-Hant-HK']) assert.equal(loopLocale(tag), 'zh-Hant', tag);
  for (const tag of ['zh', 'zh-Hans', 'zh-CN', 'zh-SG', 'zh-Hans-HK', 'zh-twx', 'yuez']) assert.equal(loopLocale(tag), 'en', tag);
  assert.equal(proofCopy('zh').title, proofCopy('en').title);
  assert.equal(proofCopy('zh-CN').figure.assistedExports, 'Assisted exports (separate)');
  assert.equal(briefCopy('zh-Hant-HK').title, '機會簡報');
  assert.equal(proofCopy('zh-TW').figure.assistedExports, '輔助匯出（另計）');
  for (const copy of [briefCopy('en'), briefCopy('zh-Hant')]) assert.equal(Object.keys(copy.reasons).length, 8);
});

test('a brief never shows more than three items and labels stored results, never "today"', () => {
  const brief = { edition: { items: [item(), item({ id: 'bi_2' }), item({ id: 'bi_3' }), item({ id: 'bi_4' })] } };
  assert.equal(visibleItems(brief).length, 3);
  assert.deepEqual(visibleItems({ edition: { items: [] } }), []);
  for (const locale of ['en', 'zh-Hant']) {
    const copy = briefCopy(locale);
    assert.doesNotMatch(copy.description + copy.stored, /today|今天的新/i);
    assert.match(copy.storedNote, /not today|並非今天/);
  }
});

test('unknown times say unknown; coverage reads in words', () => {
  const copy = briefCopy('en');
  assert.equal(timeLine(item(), copy, () => '7 Oct'), 'Published unknown · Retrieved 7 Oct');
  assert.equal(coverageLine(item(), copy), 'available · partial');
  assert.equal(coverageLine({ coverage: { availability: 'unknown' } }, copy), 'unknown');
});

test('relevance and coverage notes read in the person\'s language', () => {
  const matched = { relevance: { reason: 'Server text', matches: [{ kind: 'goal', label: 'Teach adults' }] }, coverage: { availability: 'available', scope: 'watchlist', note: 'Research Broker note' } };
  assert.equal(relevanceText(matched, briefCopy('en')), 'Matches your goal “Teach adults”.');
  assert.equal(relevanceText(matched, briefCopy('zh-Hant')), '配合你的目標「Teach adults」。');
  assert.equal(relevanceText({ relevance: { reason: 'Server text', matches: [] } }, briefCopy('en')), 'Server text');
  assert.doesNotMatch(coverageNote(matched, briefCopy('en')), /Broker/);
  assert.equal(coverageNote({ coverage: { availability: 'available', scope: 'other', note: 'Own note' } }, briefCopy('zh-Hant')), 'Own note');
  for (const copy of [briefCopy('en'), briefCopy('zh-Hant')]) assert.deepEqual(Object.keys(copy.relevance).sort(), ['brand', 'fit', 'goal', 'interest', 'material']);
});

test('only https links become links', () => {
  assert.equal(safeHref('https://news.example/a'), 'https://news.example/a');
  for (const bad of ['http://news.example/a', 'javascript:alert(1)', 'https://user:pass@x.example/', '', null, 'not a url']) assert.equal(safeHref(bad), null);
});

test('item state, decision wording and outcome follow the latest action', () => {
  const copy = briefCopy('en');
  assert.equal(itemStatus(item()), 'open');
  const saved = item({ decision: { action: 'save_idea', reasonCode: null, outcomeRefs: [{ type: 'source', id: 'src-9' }], createdAt: 1 } });
  assert.equal(itemStatus(saved), 'done');
  assert.equal(outcomeSourceId(saved), 'src-9');
  const dismissed = item({ decision: { action: 'dismiss', reasonCode: 'not_now', outcomeRefs: [], createdAt: 1 } });
  assert.equal(itemStatus(dismissed), 'set_aside');
  assert.equal(decisionLabel(dismissed, copy), 'Dismissed · Not now');
  assert.equal(decisionLabel(item({ decision: { action: 'restore', reasonCode: null, outcomeRefs: [], createdAt: 1 } }), copy), null);
});

test('an action targets the version the person saw', () => {
  assert.deepEqual(actionTarget({ id: 'e1', materialDigest: 'd' }), { editionId: 'e1' });
  assert.deepEqual(actionTarget({ id: null, materialDigest: 'd' }), { materialDigest: 'd' });
});

test('proof figures: unavailable is never zero, exports stay separate, time classes and unknown cost stay apart', () => {
  const copy = proofCopy('en');
  assert.equal(figureText('outcomes', { value: null, dataState: 'unavailable', reason: 'results_unavailable', evidence: {} }, copy), 'Unavailable — Result tracking is not available yet');
  assert.equal(figureText('providerCost', { value: null, dataState: 'restricted', evidence: {} }, copy), 'Owners only');
  assert.equal(figureText('verifiedPublications', { value: 0, dataState: 'available', evidence: {} }, copy), '0');
  assert.equal(figureText('assistedExports', { value: { exportReady: 3, downloaded: 2, userConfirmedUsed: 5 }, dataState: 'available', evidence: {} }, copy),
               '3 ready · 2 downloaded · 5 confirmed used');
  assert.equal(figureText('timeBack', { value: [{ confidence: 'estimated', outcomes: 1, savedSeconds: 480 }, { confidence: 'measured', outcomes: 1, savedSeconds: 360 }], dataState: 'available', evidence: {} }, copy),
               '8 min estimated · 6 min measured');
  assert.equal(figureText('providerCost', { value: { actualUsdMicro: 1200, actualEntries: 1, unknownEntries: 1, unknownReservedEstimateUsdMicro: 5000 }, dataState: 'partial', evidence: {} }, copy),
               'US$0.0012 actual (1 entry) · 1 unknown (US$0.0050 reserved estimate, not actual)');
  assert.match(figureText('outcomes', { value: { provider_native: null, first_party_reported: { counts: { lead: 2 } }, user_declared: { counts: {} } }, dataState: 'partial', evidence: {} }, copy),
               /^Platform-reported: Unavailable · Your site or form: 2 leads · You declared: 0$/);
  assert.match(figureText('outcomes', { value: { provider_native: null, first_party_reported: { counts: { newsletter_signup: 1 } }, user_declared: null }, dataState: 'partial', evidence: {} }, proofCopy('zh-Hant')),
               /你的網站或表格: 電子報訂閱 1/);
  assert.equal(usd(2_500_000), 'US$2.50');
  assert.deepEqual(FIGURE_ORDER.slice(0, 3), ['acceptedWork', 'verifiedPublications', 'assistedExports']);
});

test('handled items stay reachable, bounded, each with the stored edition to act on', () => {
  const handled = Array.from({ length: 12 }, (_, n) => item({ id: `bi_h${n}`, editionId: `e${n}`, decision: { action: 'not_relevant', reasonCode: 'wrong_topic', outcomeRefs: [], createdAt: n } }));
  const shown = handledItems({ edition: { items: [], handled } });
  assert.equal(shown.length, 10);
  assert.equal(itemStatus(shown[0]), 'set_aside');
  assert.equal(decisionLabel(shown[0], briefCopy('zh-Hant')), '已標示為不相關 · 主題不對');
  assert.deepEqual(handledItems({ edition: { items: [] } }), []);
  for (const copy of [briefCopy('en'), briefCopy('zh-Hant')]) assert.ok(copy.handled && copy.handledNote);
});

test('a cost correction shows only that it changed to non-owners', () => {
  assert.equal(correctionText({ figure: 'providerCost', restricted: true }, proofCopy('en')), 'AI and data service cost: Owners only');
  assert.equal(correctionText({ figure: 'providerCost', restricted: true }, proofCopy('zh-Hant')), 'AI 及資料服務費用: 只限擁有者');
});

test('evidence groups, corrections and decisions', () => {
  const copy = proofCopy('en');
  assert.deepEqual(evidenceGroups({ evidence: { jobIds: ['j1', 'j2'], weekIds: [] } }), [{ label: 'job ids', ids: ['j1', 'j2'] }]);
  assert.equal(correctionText({ figure: 'verifiedPublications', before: 1, after: 2 }, copy), 'Verified publications: 1 → 2');
  assert.equal(correctionText({ figure: 'outcomes', before: null, after: null, evidenceOnly: true }, copy), 'Outcomes by source: Evidence');
  assert.deepEqual(decisionActions({ actions: ['accept', 'edit', 'reject'] }, false), []);
  assert.deepEqual(decisionActions({ actions: ['edit', 'revoke'] }, true), ['edit', 'revoke']);
  assert.deepEqual(scopeText({ goalId: 'g', channelId: 'ch1', language: 'en', contentType: null }, copy, () => 'Threads @studio'), ['Account: Threads @studio', 'Language: en']);
});

test('the week view lists applied decisions, revocations since planning and reasons in words', () => {
  const copy = proofCopy('zh-Hant');
  const decisions = [{ id: 'sd_a', status: 'revoked', statement: 'Prefer questions' }, { id: 'sd_b', status: 'edited', statement: 'One post from the idea' }];
  const summary = appliedSummary([{ id: 'sd_a', revision: 2, slotIds: ['s1', 's2'] }], [{ id: 'sd_b', revision: 2, reason: 'already_applied' }], decisions, copy);
  assert.deepEqual(summary.applied, [{ id: 'sd_a', revision: 2, statement: 'Prefer questions', slots: 2, revokedSince: true }]);
  assert.deepEqual(summary.notApplied, [{ id: 'sd_b', revision: 2, statement: 'One post from the idea', reason: '已在較早的一週計劃中使用' }]);
  assert.deepEqual(appliedSummary(undefined, undefined, [], copy), { applied: [], notApplied: [] });
});
