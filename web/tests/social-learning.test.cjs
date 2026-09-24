const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
function load(relative) {
  const filename = path.resolve(__dirname, '../src', relative);
  const source = fs.readFileSync(filename, 'utf8');
  const code = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
  const mod = { exports: {} };
  new Function('module', 'exports', 'require', code)(mod, mod.exports, require);
  return mod.exports;
}
const h = load('lib/channels/owned-posts.ts');
const v = load('features/agent/voice-learning-intent.ts');
const post = (id, publishedAt = '2026-09-20T12:00:00Z') => ({ id, text: `My caption ${id}`, platform: 'Instagram', publishedAt, mediaType: 'IMAGE', permalink: null, thumbnailUrl: null });
const page = (id, nextCursor, first = true) => ({ connectionId: 'c', providerAccountId: '1789', receipt: `sealed-${id}`, expiresAt: 9999, posts: [post(id)], nextCursor, scannedCount: 1, skippedCount: 0, partialCoverage: Boolean(nextCursor || !first), coverageNote: 'Eligible captions only', coverage: { startedFromBeginning: first, endReached: nextCursor === null } });

test('append keeps selected older pages and deduplicates imported post identities', () => {
  const first = page('1', 'after-1');
  const second = { ...page('2', null, false), posts: [post('1'), post('2')], scannedCount: 2 };
  const pages = h.appendOwnedPage([first], second, 'after-1');
  assert.deepEqual(h.loadedPosts(pages).map((p) => p.id), ['1', '2']);
  assert.equal(h.selectedReceipts(pages, ['1', '2'], 100).flatMap((x) => x.postIds).length, 2);
  assert.equal(first.posts.length, 1);
});
test('foreign accounts, broken cursor chains, duplicate cursors and unbounded previews fail', () => {
  const first = page('1', 'after-1');
  assert.throws(() => h.appendOwnedPage([first], { ...page('2', null, false), providerAccountId: 'foreign' }, 'after-1'));
  assert.throws(() => h.appendOwnedPage([first], page('2', null, false), 'wrong'));
  assert.throws(() => h.appendOwnedPage([first], page('2', 'after-1', false), 'after-1'));
  assert.throws(() => h.appendOwnedPage(Array.from({ length: 4 }, (_, i) => page(String(i), 'more')), page('5', null, false), 'more'));
});
test('coverage describes the loaded date range and never says all posts', () => {
  const first = { ...page('1', 'more'), posts: [post('1', '2025-01-01T00:00:00Z'), post('2')] };
  const summary = h.coverageSummary([first]);
  assert.match(summary, /Loaded 2 posts from Jan 2025–Sep 2026/);
  assert.doesNotMatch(summary, /all posts/i);
  assert.match(h.coverageSummary([{ ...first, posts: [] }]), /No eligible captions in the retrieved pages/);
});
test('only selected verified unexpired posts can form a bounded retention request', () => {
  assert.throws(() => h.selectedReceipts([page('1', null)], ['foreign'], 100));
  assert.throws(() => h.selectedReceipts([page('1', null)], ['1'], 10000));
  assert.throws(() => h.selectedReceipts([page('1', null)], [], 100));
  assert.throws(() => h.selectedReceipts([page('1', null)], Array.from({ length: 51 }, (_, i) => String(i)), 100));
});
test('Ask Rafii recognizes explicit own-writing analysis without treating it as a draft', () => {
  assert.deepEqual(v.voiceLearningIntent('Analyze my recent Instagram posts and learn how I write.'), { platform: 'Instagram', instructions: 'Analyze my recent Instagram posts and learn how I write.' });
  assert.equal(v.voiceLearningIntent('Analyse my LinkedIn posts and learn my voice').platform, 'LinkedIn');
  assert.equal(v.voiceLearningIntent('幫我分析 Instagram 貼文，學習我的寫作風格').platform, 'Instagram');
  assert.equal(v.voiceLearningIntent('Write an Instagram post about my piano recital'), null);
  assert.equal(v.voiceLearningIntent('Analyse another author\'s Instagram posts'), null);
  assert.equal(v.voiceLearningIntent('Publish my Instagram post now'), null);
  assert.equal(v.voiceLearningIntent('Learn my voice from my past posts').platform, undefined);
});
test('manual setup does not silently preselect warm as a learned tone', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/features/workspace/voice-setup.tsx'), 'utf8');
  assert.ok(!/const \[tone, setTone\].*\('warm'\)/.test(source), 'Warm must not be preselected');
  assert.ok(/not a learned conclusion/.test(source), 'Explain manually chosen tone');
});
test('both chat entry points intercept learning before drafting or publishing', () => {
  for (const relative of ['features/agent/home-view.tsx', 'features/agent/conversation-view.tsx']) {
    const source = fs.readFileSync(path.resolve(__dirname, '../src', relative), 'utf8');
    assert.ok(/voiceLearningIntent\(body\)/.test(source), `${relative}: intercept own-writing requests`);
    assert.ok(/VoiceLearningPanel/.test(source), `${relative}: render the shared review panel`);
    const intercept = source.indexOf('voiceLearningIntent(body)');
    // Home drafts through its generation hook (features/agent/home/use-home-generation.ts calls api.quickStart).
    const generation = Math.max(source.indexOf('await api.quickStart('), source.indexOf('await api.turn('), source.indexOf('await generation.start('));
    assert.ok(generation > -1, `${relative}: a drafting call exists`);
    assert.ok(intercept < generation);
  }
});
