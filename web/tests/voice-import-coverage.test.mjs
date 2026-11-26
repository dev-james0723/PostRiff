/**
 * Coverage receipt model and readable labels: five states, unknown totals, zero posts, mixed routes, sparse history.
 *   node --test tests/voice-import-coverage.test.mjs
 */
import test from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { loadTs } from './fixtures/voice-import/load-ts.mjs';

const { coverageStates, coverageLines, accountLines, coverageTotals, accountReceipts, voiceGroups, waitingForAuthor, anyImportActive, modalityLine, MIN_ELIGIBLE } = await loadTs('lib/voice-import/coverage.ts');
const { traitLabel, TRAIT_LABELS, platformName, languageName, exclusionPhrase, exclusionLabel } = await loadTs('lib/voice-import/labels.ts');
const { exportGuide, routeReason, routeOffer, noteText } = await loadTs('lib/voice-import/guides.ts');

const modality = { text: 'analysed', images: 'not_analysed', video: 'not_analysed' };
const none = { repost: 0, duplicate: 0, rafii_published: 0, too_short: 0, other_author: 0, outdated: 0, manual: 0 };
const threads = {
  provider: 'threads', accountKey: 'acct-1', label: '@studio_example', route: 'official_api', voiceScope: 'brand', retrieved: 312, eligible: 280,
  excluded: { ...none, repost: 20, duplicate: 9, too_short: 3 }, languages: { en: 200, yue: 70, mixed: 10 },
  observed: { oldest: '2021-03-04T10:00:00+00:00', newest: '2026-11-20T08:00:00+00:00' }, moreRemaining: null, totalKnown: false
};
const exported = {
  provider: 'x', accountKey: 'studio_example', label: 'studio_example', route: 'platform_export', voiceScope: 'separate', retrieved: 40, eligible: 0,
  excluded: { ...none, repost: 1 }, languages: { en: 39 }, observed: { oldest: '2024-02-18T12:33:11+00:00', newest: '2024-02-21T10:00:00+00:00' }, moreRemaining: false, totalKnown: true
};

test('the five states come from the workspace; a state it leaves out is read from the accounts and a profile state is never assumed', () => {
  const stated = coverageStates({ states: { connected: 'done', retrieved: 'partial', processed: 'done', proposed: 'done', approved: 'none' }, accounts: [threads], modality });
  assert.deepEqual(stated, [
    { id: 'connected', status: 'done' },
    { id: 'retrieved', status: 'partial' },
    { id: 'processed', status: 'done' },
    { id: 'proposed', status: 'done' },
    { id: 'approved', status: 'none' }
  ]);
  assert.deepEqual(coverageStates(undefined).map((state) => state.status), ['none', 'none', 'none', 'none', 'none']);
  assert.deepEqual(coverageStates({ accounts: [] }).map((state) => state.status), ['none', 'none', 'none', 'none', 'none']);
  // No states object: an unknown remainder is never reported as complete, and nothing claims a proposal.
  assert.deepEqual(coverageStates({ accounts: [threads] }).map((state) => state.status), ['done', 'partial', 'partial', 'none', 'none']);
  assert.deepEqual(coverageStates({ accounts: [exported] }).map((state) => state.status), ['done', 'done', 'done', 'none', 'none']);
  assert.deepEqual(coverageStates({ accounts: [{ ...threads, retrieved: 0, eligible: 0 }] }).map((state) => state.status), ['done', 'pending', 'none', 'none', 'none']);
  // A word the client does not know is not passed through.
  assert.equal(coverageStates({ states: { approved: 'yes' }, accounts: [] })[4].status, 'none');
});

test('an unknown total is called unknown and never turned into a share', () => {
  const lines = accountLines(threads, 'en');
  assert.equal(lines[0], '312 posts retrieved; the platform does not say how many exist.');
  assert.ok(!lines.join(' ').includes('%'));
  assert.ok(!lines.some((line) => /\bof 3\d\d\b/.test(line)), 'no "x of y" against an unknown total');
  assert.ok(lines.includes('Posts from Mar 2021 to Nov 2026.'));
  assert.ok(lines.includes('280 can be used for the profile.'));
  assert.ok(lines.includes('Left out: 20 reposts, 9 duplicates, 3 too short to learn from.'));
  assert.ok(lines.includes('Languages: English 200, Cantonese 70, Chinese and English mixed 10.'));
  assert.ok(!lines.some((line) => line.includes('end of what the platform returns')), 'an unknown remainder says nothing about the end');
  assert.ok(accountLines({ ...threads, moreRemaining: true }, 'en').includes('More posts exist that were not read.'));
  assert.ok(accountLines({ ...threads, moreRemaining: false }, 'en').includes('Rafii read to the end of what the platform returns.'));
  assert.equal(accountLines(exported, 'en')[0], '40 posts retrieved; the source lists no more.');
  assert.equal(accountLines({ ...threads, retrieved: 1, eligible: 1, excluded: none, languages: {} }, 'en')[0], '1 post retrieved; the platform does not say how many exist.');
});

test('posts whose author is unknown wait: they are neither usable nor left out', () => {
  const mixed = { ...threads, retrieved: 100, eligible: 60, excluded: { ...none, repost: 10 } };
  assert.equal(waitingForAuthor(mixed), 30);
  assert.ok(accountLines(mixed, 'en').includes('30 posts wait for you to say who wrote them.'));
  assert.ok(accountLines({ ...mixed, eligible: 89 }, 'en').includes('1 post waits for you to say who wrote it.'));
  assert.equal(waitingForAuthor({ ...mixed, eligible: 95 }), 0, 'never negative');
});

test('zero posts', () => {
  assert.deepEqual(coverageLines({ states: {}, accounts: [], modality }, 'en'), ['No posts retrieved yet.', 'Text is analysed. Images and video are not analysed.']);
  assert.deepEqual(coverageLines(null, 'zh-Hant'), ['尚未取得任何貼文。', '只分析文字，不分析圖片及影片。']);
  assert.deepEqual(accountLines({ provider: 'threads', accountKey: 'a', retrieved: 0 }, 'en'), ['No posts retrieved yet.']);
  assert.deepEqual(coverageTotals(undefined), { accounts: 0, retrieved: 0, eligible: 0, brandEligible: 0, excluded: 0, waiting: 0 });
});

test('mixed routes: a connected account and an export are counted together and named apart', () => {
  const coverage = { states: {}, accounts: [threads, exported], modality };
  assert.deepEqual(coverageTotals(coverage), { accounts: 2, retrieved: 352, eligible: 280, brandEligible: 280, excluded: 33, waiting: 39 });
  assert.deepEqual(coverageLines(coverage, 'en'), [
    '352 posts retrieved from 2 accounts; the total is unknown for 1 of them.',
    'Sources: 1 connected, 1 from export files.',
    '280 can be used for the profile; 33 were left out; 39 wait for an author.',
    'Text is analysed. Images and video are not analysed.'
  ]);
  assert.equal(coverageLines({ accounts: [threads], modality }, 'en')[0], '312 posts retrieved; the platform does not say how many exist.');
  assert.equal(coverageLines({ accounts: [threads, { ...exported, totalKnown: false }], modality }, 'en')[0], '352 posts retrieved from 2 accounts; the platforms do not say how many exist.');
  assert.equal(coverageLines({ accounts: [{ ...threads, totalKnown: true }, exported], modality }, 'en')[0], '352 posts retrieved from 2 accounts; the sources list no more.');
  for (const language of ['zh-Hant', 'zh-Hans']) assert.ok(coverageLines(coverage, language).every((line) => line.length > 0 && !/posts retrieved/.test(line)), language);
});

test('images and video are reported as not analysed unless the workspace says otherwise', () => {
  assert.equal(modalityLine({ modality }, 'en'), 'Text is analysed. Images and video are not analysed.');
  assert.equal(modalityLine({}, 'en'), 'Text is analysed. Images and video are not analysed.');
  assert.equal(modalityLine({ modality: { text: 'analysed', images: 'analysed', video: 'not_analysed' } }, 'en'), 'Text and images are analysed. Video is not analysed.');
});

test('one receipt per account joins the coverage row to its runs, newest first, and keeps every route used', () => {
  const runs = [
    { id: 'i1', route: 'official_api', provider: 'threads', accountKey: 'acct-1', accountLabel: '@studio_example', status: 'done', createdAt: '2026-11-20T08:00:00Z', consent: { voiceScope: 'brand' } },
    { id: 'i2', route: 'platform_export', provider: 'threads', accountKey: 'acct-1', accountLabel: '@studio_example', status: 'receiving', createdAt: '2026-11-24T08:00:00Z', consent: { voiceScope: 'brand' } },
    { id: 'i3', route: 'official_api', provider: 'mastodon', accountKey: 'acct-9', accountLabel: 'studio@example.social', status: 'pending', createdAt: 1795000000, consent: { voiceScope: 'separate' } }
  ];
  const receipts = accountReceipts({ imports: runs, coverage: { accounts: [threads] } });
  assert.deepEqual(receipts.map((receipt) => receipt.key), ['threads:acct-1', 'mastodon:acct-9']);
  assert.deepEqual(receipts[0].imports.map((run) => run.id), ['i2', 'i1']);
  assert.equal(receipts[0].latest.id, 'i2');
  assert.equal(receipts[0].active.id, 'i2');
  assert.deepEqual(receipts[0].routes.toSorted(), ['official_api', 'platform_export']);
  assert.equal(receipts[0].account, threads);
  assert.equal(receipts[1].account, null, 'a run with no stored post still has a receipt');
  assert.equal(receipts[1].label, 'studio@example.social');
  assert.equal(receipts[1].voiceScope, 'separate');
  assert.equal(anyImportActive({ imports: runs }), true);
  assert.equal(anyImportActive({ imports: [runs[0]] }), false);
  assert.deepEqual(accountReceipts(undefined), []);
});

test('voice groups: the brand, and each account kept separate under the workspace group key', () => {
  assert.deepEqual(voiceGroups({ coverage: { accounts: [threads, exported] } }), [
    { key: 'brand', eligible: 280 },
    { key: 'separate:x:studio_example', label: 'studio_example', eligible: 0 }
  ]);
  assert.deepEqual(voiceGroups({ coverage: { accounts: [] } }), [{ key: 'brand', eligible: 0 }]);
  assert.deepEqual(voiceGroups({ coverage: { accounts: [exported] } }), [{ key: 'separate:x:studio_example', label: 'studio_example', eligible: 0 }]);
  const stated = [{ key: 'brand', label: 'Brand voice', eligible: 5 }];
  assert.equal(voiceGroups({ coverage: { accounts: [threads] }, groups: stated }), stated, 'the workspace list wins when it is sent');
  assert.equal(MIN_ELIGIBLE, 3);
});

test('every trait dimension has a readable name in English and Traditional Chinese; unknown ids become words', () => {
  const python = readFileSync(new URL('../../src/postriff_phase2/voice_analysis.py', import.meta.url), 'utf8');
  const tuple = /^DIMENSIONS = \(([\s\S]*?)^\)/m.exec(python)?.[1] ?? '';
  const measured = [...tuple.matchAll(/"([a-z_]+)"/g)].map((match) => match[1]);
  assert.ok(measured.length >= 18 && measured.includes('sentence_length'), 'the local dimension list was read');
  const corpus = ['tone', 'sentence_rhythm', 'opening_shape', 'closing_shape', 'vocabulary_register', 'structure', 'topics', 'reader_address', 'code_switching'];
  for (const id of [...measured, ...corpus]) {
    assert.ok(TRAIT_LABELS[id], `${id} has a label`);
    const [en, hant, hans] = TRAIT_LABELS[id];
    assert.ok(en && !en.includes('_') && /^[A-Z]/.test(en), `${id} English`);
    assert.ok(/[一-鿿]/.test(hant) && /[一-鿿]/.test(hans), `${id} Chinese`);
    assert.equal(traitLabel(id, 'zh-Hant'), hant);
  }
  assert.equal(traitLabel('sentence_length', 'en'), 'Sentence length');
  assert.equal(traitLabel('emoji:instagram', 'en'), 'Emoji');
  assert.equal(traitLabel('tone.ai:linkedin', 'zh-Hant'), '語氣');
  assert.equal(traitLabel('opening_shape.ai', 'en', 'opening_shape'), 'How posts open');
  assert.equal(traitLabel('direction-2', 'en'), 'Direction I want');
  assert.equal(traitLabel('some_new_trait', 'en'), 'Some new trait');
  assert.equal(traitLabel('some_new_trait', 'zh-Hant'), 'Some new trait');
});

test('platform, language and exclusion names', () => {
  assert.deepEqual(['linkedin', 'x', 'threads', 'instagram', 'facebook', 'mastodon', 'bluesky', 'LinkedIn', 'newplace'].map(platformName), ['LinkedIn', 'X', 'Threads', 'Instagram', 'Facebook', 'Mastodon', 'Bluesky', 'LinkedIn', 'Newplace']);
  assert.equal(languageName('yue', 'en'), 'Cantonese');
  assert.equal(languageName('yue', 'zh-Hant'), '廣東話');
  assert.equal(languageName('und', 'en'), 'Language not identified');
  assert.equal(languageName('fr', 'en'), 'fr');
  assert.equal(exclusionPhrase('repost', 1, 'en'), '1 repost');
  assert.equal(exclusionPhrase('repost', 40, 'en'), '40 reposts');
  assert.equal(exclusionPhrase('rafii_published', 3, 'zh-Hant'), '3 篇由 Rafii 撰寫');
  assert.equal(exclusionPhrase('manual', 2, 'en'), '2 left out by you');
  assert.equal(exclusionPhrase('brand_new_reason', 2, 'en'), '2 brand new reason');
  assert.equal(exclusionLabel('other_author', 'en'), 'Someone else wrote it');
  assert.equal(exclusionLabel('outdated', 'zh-Hans'), '旧风格');
});

test('routes: an unavailable route says why, and names the export file to pick instead', () => {
  assert.match(routeReason('linkedin', 'official', null, 'en'), /LinkedIn no longer gives new apps permission/);
  assert.match(routeReason('facebook', 'official', '', 'en'), /Facebook permission that Rafii does not have/);
  assert.match(routeReason('x', 'official', undefined, 'en'), /X charges for each post an app reads/);
  assert.match(routeReason('x', 'official', undefined, 'zh-Hant'), /收費/);
  assert.match(routeReason('bluesky', 'export', null, 'en'), /cannot read yet/);
  // A sentence from the workspace is shown as written; a bare code is put into words after a plain statement.
  assert.equal(routeReason('threads', 'official', 'Reconnect this account to grant reading.', 'en'), 'Reconnect this account to grant reading.');
  assert.equal(routeReason('threads', 'official', 'provider_not_enabled', 'en'), 'Rafii cannot read Threads posts directly right now. (provider not enabled)');
  assert.equal(routeReason('pixelfed', 'export', null, 'en'), 'Rafii cannot read a Pixelfed export yet.');
  // The workspace's own codes for a route switched off on this deployment read as sentences, in the person's language.
  assert.equal(routeReason('mastodon', 'official', 'not_enabled', 'en'), 'Reading Mastodon posts from a connected account is not turned on here.');
  assert.equal(routeReason('instagram', 'official', 'not_configured', 'en'), 'Instagram accounts cannot be connected here yet.');
  assert.match(routeReason('mastodon', 'official', 'not_enabled', 'zh-Hant'), /此處未啟用/);
  assert.equal(routeReason('threads', 'official', 'constructor', 'en'), 'Rafii cannot read Threads posts directly right now. (constructor)', 'an unknown code is never looked up on the prototype');

  assert.deepEqual(exportGuide('x').files.map((file) => file.path), ['data/tweets.js', 'data/note-tweet.js']);
  assert.deepEqual(exportGuide('instagram').files.map((file) => file.path), ['your_instagram_activity/media/posts_1.json', 'your_instagram_activity/content/posts_1.json', 'content/posts_1.json']);
  assert.equal(exportGuide('linkedin').files[0].path, 'Shares.csv');
  assert.equal(exportGuide('mastodon').files[0].path, 'outbox.json');
  assert.equal(exportGuide('threads').files[0].path, 'your_instagram_activity/threads/threads_and_replies.json');
  assert.match(exportGuide('facebook').files[0].path, /your_posts__check_ins__photos_and_videos_1\.json$/);
  assert.equal(exportGuide('bluesky'), null);
  for (const provider of ['instagram', 'facebook', 'threads', 'x', 'linkedin', 'mastodon']) for (const text of exportGuide(provider).request) assert.ok(text.length > 10);

  assert.deepEqual(routeOffer({ provider: 'x', official: { available: false, reason: 'billed' }, export: { available: true, files: ['tweets.js'] } }), { official: false, upload: true });
  assert.deepEqual(routeOffer({ provider: 'bluesky', official: { available: true }, export: { available: false } }), { official: true, upload: false });
  assert.deepEqual(routeOffer({ provider: 'pixelfed', official: { available: false }, export: { available: true } }), { official: false, upload: false }, 'no upload is offered for an export this app cannot parse');
  assert.deepEqual(routeOffer({ provider: 'x' }), { official: false, upload: false });
  for (const note of ['not_json', 'unknown_shape']) assert.ok(noteText(note, 'zh-Hant').length > 5);
});
