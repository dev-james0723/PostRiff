/**
 * Rafii Intelligent Library — T09 shell, previews and accessible interactions
 * (docs/design/rafii-intelligent-library-2026-10-08/03-UI-OPENUI-SPEC.md; A016, A021, A048, A051, A059–A066).
 *
 * Source-text assertions on the Library feature plus real logic from the pure helpers in src/lib/library, which are
 * transpiled here on their own (no '@/' imports), like media-libs.test.cjs.
 *
 *   node --test web/tests/library-intelligence-ui.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const SRC = path.join(__dirname, '..', 'src');
const LIB = path.join(SRC, 'lib', 'library');
const FEATURE = path.join(SRC, 'features', 'library');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(source, /from '@\//, `${path.basename(file)} must not use @/ imports (plain node --test transpile)`);
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}

const read = (...parts) => fs.readFileSync(path.join(SRC, ...parts), 'utf8');
const feature = (...parts) => read('features', 'library', ...parts);

function sources(dir = FEATURE) {
  const out = [];
  for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
    const full = path.join(dir, entry.name);
    if (entry.isDirectory()) out.push(...sources(full));
    else if (/\.(ts|tsx)$/.test(entry.name)) out.push({ file: path.relative(FEATURE, full), text: fs.readFileSync(full, 'utf8') });
  }
  return out;
}

/** Every `useEffect(...)` call's source, by bracket depth (good enough for this codebase's effect bodies). */
function effectBodies(text) {
  const bodies = [];
  let index = 0;
  while ((index = text.indexOf('useEffect(', index)) !== -1) {
    let depth = 0;
    let end = index + 'useEffect'.length;
    for (; end < text.length; end += 1) {
      const character = text[end];
      if (character === '(') depth += 1;
      else if (character === ')') {
        depth -= 1;
        if (depth === 0) break;
      }
    }
    bodies.push(text.slice(index, end + 1));
    index = end;
  }
  return bodies;
}

const W = load(path.join(LIB, 'wording.ts'));
const B = load(path.join(LIB, 'batch.ts'));
const U = load(path.join(LIB, 'url-state.ts'));
const L = load(path.join(LIB, 'layout.ts'));
const R = load(path.join(LIB, 'smart-rules.ts'));
const V = load(path.join(LIB, 'versions.ts'));
const A = load(path.join(LIB, 'answers.ts'));

test('test_single_add_entry: one Add menu (upload, link, note) and no competing upload button', () => {
  const view = feature('library-view.tsx');
  const add = feature('intelligence', 'add-menu.tsx');
  assert.doesNotMatch(view, /Upload images/, 'the separate Upload images button is gone');
  assert.doesNotMatch(view, /'Add assets'|>\s*Add assets\s*</, 'no second "Add assets" action');
  assert.doesNotMatch(view, /StatefulButton/);
  assert.equal((view.match(/<AddMenu\b/g) || []).length, 1, 'exactly one Add control on the page');
  const tourHooks = sources().reduce((total, { text }) => total + (text.match(/data-tour='library-upload'/g) || []).length, 0);
  assert.equal(tourHooks, 1, 'one library-upload tour target, on the Add trigger');
  assert.match(add, /data-tour='library-upload'/);
  for (const copy of ['Upload files', 'Paste link', 'Quick note', 'api.libraryIngestLink(', 'api.libraryIngestNote(', 'I wrote this', 'authoredByMe']) assert.ok(add.includes(copy), copy);
  assert.match(add, /const \[authoredByMe, setAuthoredByMe\] = useState\(false\)/, 'authorship is never assumed');
  // Drag and drop, the photo compatibility path and the video/document flows stay behind "Upload files".
  for (const kept of ['useDropzone(', 'upload.enqueue(', 'uploadLibraryVideo(', 'beginLibraryFile', 'commitLibraryFile', "aria-label='Choose assets to add to Library'", 'onUploadFiles={() => filePicker.current?.click()}']) assert.ok(view.includes(kept), kept);
  // The other tour hooks survive the move.
  assert.match(view, /data-tour='library-empty'/);
  assert.match(feature('intelligence', 'library-toolbar.tsx'), /data-tour='library-filter'/);
  assert.match(feature('asset-card.tsx'), /data-tour=\{first \? 'library-card' : undefined\}/);
  assert.match(feature('asset-list-row.tsx'), /data-tour=\{first \? 'library-card' : undefined\}/);
});

test('test_scope_visible: the scope is always written out beside search, and search falls back to the deterministic Library', () => {
  assert.equal(W.scopeLabel({ kind: 'workspace' }), 'Entire permitted Library');
  assert.equal(W.scopeLabel({ kind: 'collection', collectionName: 'Practice' }), 'This collection');
  assert.equal(W.scopeDetail({ kind: 'collection', collectionName: 'Practice' }), 'This collection: Practice');
  assert.equal(W.scopeLabel({ kind: 'selection', selectedCount: 1 }), 'Selected 1 item');
  assert.equal(W.scopeLabel({ kind: 'selection', selectedCount: 3 }), 'Selected 3 items');

  const toolbar = feature('intelligence', 'library-toolbar.tsx');
  assert.match(toolbar, /const label = scopeLabel\(scope\)/);
  assert.match(toolbar, /aria-describedby=\{`\$\{id\}-scope`\}/, 'the scope describes the search field');
  assert.match(toolbar, /Searching <span[^>]*>\{label\}<\/span>/);
  assert.match(toolbar, /type='search'/);

  const view = feature('library-view.tsx');
  assert.match(view, /<LibrarySearchField\s+value=\{query\}\s+onChange=\{setQuery\}\s+scope=\{scope\}/);
  assert.match(view, /useLibrarySearch\(\{ enabled: intel\.retrieval,/, 'intelligent search only when the status route says retrieval is on');
  assert.match(view, /query: intelligent \? '' : query/, 'the deterministic list takes the query whenever the intelligent search is not answering');

  const hook = feature('intelligence', 'use-library-search.ts');
  assert.match(hook, /new AbortController\(\)/);
  assert.match(hook, /abort\.abort\(\)/, 'a newer query aborts the obsolete request');
  assert.match(hook, /api\s*\.librarySearch\(workspaceId, [^,]+, abort\.signal\)/);
  assert.match(hook, /library_capability_unavailable/);
  assert.match(hook, /unavailable\.current = true/, 'a missing capability stops further attempts this session');

  assert.equal(
    W.coverageLabel({ accessibleAssetCount: 1252, indexedAssetCount: 1240, pendingAssetCount: 12, failedAssetCount: 0, partial: true }),
    'Searched 1,240 of 1,252 permitted items · 12 still being indexed'
  );
  assert.equal(W.coverageLabel({ accessibleAssetCount: 1, indexedAssetCount: 1, pendingAssetCount: 0, failedAssetCount: 0, partial: false }), 'Searched 1 of 1 permitted item');
});

test('test_honest_document_preview: text covers say extracted text; only a real rendition says first page', () => {
  const base = { hasExtractedText: true, hasSummary: false, genuineRendition: false };
  for (const extension of ['docx', 'xlsx', 'pptx', 'csv', 'md', 'txt', 'pdf']) assert.equal(W.documentCoverLabel({ ...base, extension }), 'Extracted text preview', extension);
  assert.equal(W.documentCoverLabel({ extension: 'pdf', hasExtractedText: true, hasSummary: false, genuineRendition: true }), 'PDF · FIRST PAGE');
  assert.equal(W.documentCoverLabel({ extension: 'docx', hasExtractedText: false, hasSummary: true, genuineRendition: false }), 'AI summary preview');
  assert.equal(W.documentCoverLabel({ extension: 'xlsx', hasExtractedText: false, hasSummary: false, genuineRendition: false }), 'XLSX file');
  assert.equal(W.documentPreviewPhrase({ extension: 'pptx', ...base }), 'extracted text preview');

  const thumbnail = feature('asset-thumbnail.tsx');
  for (const banned of ['SHEET PREVIEW', 'SLIDE PREVIEW', 'WORD · FIRST PAGE', 'DOCUMENT · FIRST PAGE', 'TEXT PREVIEW', 'charCodeAt']) assert.ok(!thumbnail.includes(banned), banned);
  const firstPageLines = thumbnail.split('\n').filter((line) => line.includes('FIRST PAGE'));
  assert.equal(firstPageLines.length, 1, 'one first-page label');
  const label = thumbnail.indexOf('PDF · FIRST PAGE');
  assert.ok(label > thumbnail.indexOf('function PdfFirstPage') && label < thumbnail.indexOf('function AudioCover'), 'the label sits on the real PDF iframe rendition');
  assert.match(thumbnail, /documentCoverLabel\(\{[^}]*genuineRendition: false/, 'text covers never claim a rendition');
  assert.match(thumbnail, /data-thumbnail-preview=\{preview\.source === 'extracted' \? 'extracted-text'/);
  assert.ok(thumbnail.includes("title='First page PDF thumbnail'") && thumbnail.includes('page=1&view=Fit'), 'the real PDF iframe path stays');
  // Card and row names say what the cover is.
  assert.match(thumbnail, /', extracted text preview'/);
  for (const file of ['asset-card.tsx', 'asset-list-row.tsx']) {
    const text = feature(file);
    assert.match(text, /documentPreviewSuffix\(asset\)/, file);
    assert.doesNotMatch(text, /wordAsset/, `${file}: Word files are not "first-page" previews`);
  }
  // Images are letterboxed, not cropped.
  assert.doesNotMatch(feature('asset-card.tsx'), /object-cover/);
  assert.doesNotMatch(feature('asset-list-row.tsx'), /object-cover/);
});

test('test_audio_no_autoplay: real peaks or a neutral symbol, and playback only from a press', () => {
  assert.equal(W.peaksToBars(undefined, 10), null);
  assert.equal(W.peaksToBars([], 10), null);
  assert.equal(W.peaksToBars([0, 0, 0], 4), null, 'silence is not drawn as a waveform');
  assert.deepEqual(W.peaksToBars([0.1, 0.5, 1, 0.25], 2), [0.5, 1]);
  assert.deepEqual(W.peaksToBars([0.2, 0.4], 4), [0.5, 0.5, 1, 1]);

  const thumbnail = feature('asset-thumbnail.tsx');
  const audioCover = thumbnail.slice(thumbnail.indexOf('function AudioCover'), thumbnail.indexOf('function GenericFileCover'));
  assert.match(audioCover, /peaksToBars\(peaks,/);
  assert.match(audioCover, /'audio-symbol'/);
  assert.doesNotMatch(audioCover, /hash|seed|asset\.id/, 'no bars derived from the file identity');
  assert.match(feature('asset-detail.tsx'), /peaks=\{card\?\.media\?\.peaks \?\? null\}/, 'the detail uses the understanding card peaks');

  for (const { file, text } of sources()) {
    assert.doesNotMatch(text, /autoPlay|autoplay/, `${file}: no autoplay`);
    assert.doesNotMatch(text, /<audio[\s>]|<video[\s>]/, `${file}: the Now Playing bar owns the only media element`);
    for (const body of effectBodies(text)) {
      assert.ok(!body.includes('getState().open(') && !body.includes('startPlayback(') && !body.includes('playFrom('), `${file}: an effect must not start playback`);
    }
  }
  const player = feature('intelligence', 'audio-player.tsx');
  assert.equal((player.match(/useNowPlaying\.getState\(\)\.open\(/g) || []).length, 1);
  assert.match(player, /async function startPlayback\(startAt\?: number\) \{[\s\S]*?useNowPlaying\.getState\(\)\.open\(\{ kind: 'audio'/);
  assert.match(player, /onClick=\{\(\) => void startPlayback\(\)\}/);
  assert.match(player, /Play audio in Now Playing/);
  assert.match(player, /actionType: 'moment\.save'/);
  assert.match(player, /payload: \{ startMs: check\.startMs, endMs: check\.endMs \}/, 'media.save_moment_action takes {startMs, endMs, label?}');
  assert.match(player, /useNowPlaying\.getState\(\)\.seek\(seconds, assetId\)/, 'seeking goes through the Now Playing store');

  assert.deepEqual(W.momentInterval(42, 57, 120), { ok: true, startMs: 42000, endMs: 57000 });
  assert.equal(W.momentInterval(57, 42, 120).ok, false);
  assert.equal(W.momentInterval(110, 130, 120).ok, false, 'a moment cannot run past the recording');
  assert.equal(W.momentInterval(null, 10, 120).ok, false);
});

test('test_batch_partial_failure: per-item outcomes, reused keys and rollback', () => {
  const outcomes = [
    { id: 'a', status: 'applied' },
    B.outcomeFromError('b', { status: 403 }),
    B.outcomeFromError('c', { status: 500 }),
    B.outcomeFromActionResult('d', { status: 'conflict', warnings: ['This source version changed.'] })
  ];
  const summary = B.reduceBatchOutcomes(outcomes, 'updated');
  assert.equal(summary.total, 4);
  assert.equal(summary.applied, 1);
  assert.equal(summary.label, '1 of 4 updated · 1 changed elsewhere · 1 not allowed · 1 failed');
  assert.deepEqual(summary.retryIds, ['c'], 'only the retryable failure is offered again');
  assert.deepEqual([...summary.rollbackIds].sort(), ['b', 'c', 'd'], 'every item that did not apply is rolled back on screen');
  assert.equal(B.reduceBatchOutcomes([{ id: 'a', status: 'applied' }, { id: 'b', status: 'applied' }], 'deleted').label, '2 items deleted');
  assert.equal(B.reduceBatchOutcomes([{ id: 'a', status: 'applied' }], 'deleted').label, '1 item deleted');
  assert.equal(B.reduceBatchOutcomes([{ id: 'a', status: 'pending' }]).done, false);

  assert.equal(B.outcomeFromError('x', { status: 404 }, 'delete').status, 'skipped', 'an already-removed item is not a failure on delete');
  assert.equal(B.outcomeFromError('x', { status: 404 }, 'update').status, 'denied');
  assert.equal(B.outcomeFromError('x', { status: 409 }).status, 'conflict');
  assert.equal(B.outcomeFromError('x', { status: 503, code: 'library_capability_unavailable' }).retryable, false);
  assert.equal(B.outcomeFromError('x', {}).retryable, true, 'a network failure may be retried');
  assert.deepEqual(B.outcomeFromActionResult('r', { status: 'applied', replayed: true }), { id: 'r', status: 'applied', message: 'Already done' });
  assert.equal(B.outcomeFromActionResult('r', { status: 'denied', warnings: [] }).status, 'denied');

  let keys = {};
  let made = 0;
  const make = () => `lib-batch-${++made}-000000000000`;
  const first = B.idempotencyKeyFor(keys, 'run-1', 'a', make);
  keys = first.keys;
  const retried = B.idempotencyKeyFor(keys, 'run-1', 'a', make);
  assert.equal(retried.key, first.key, 'a retry of the same run reuses the item key');
  assert.equal(made, 1);
  const sibling = B.idempotencyKeyFor(retried.keys, 'run-1', 'b', make);
  assert.notEqual(sibling.key, first.key, 'each item has its own key');
  assert.notEqual(B.idempotencyKeyFor(sibling.keys, 'run-2', 'a', make).key, first.key, 'a new run gets new keys');
  assert.match(B.newIdempotencyKey('lib-batch', () => 'abc'), /^[A-Za-z0-9_.:-]{16,120}$/);
  assert.match(B.newIdempotencyKey('lib-batch', () => '6f1c0b9e-1f2a-4c3d-9e8f-0a1b2c3d4e5f'), /^lib-batch-6f1c0b9e-1f2a-4c3d-9e8f-0a1b2c3d4e5f$/);
  assert.deepEqual(B.mergeOutcomes([{ id: 'a', status: 'failed' }, { id: 'b', status: 'applied' }], [{ id: 'a', status: 'applied' }]), [
    { id: 'a', status: 'applied' },
    { id: 'b', status: 'applied' }
  ]);

  const hook = feature('intelligence', 'use-batch-actions.ts');
  assert.match(hook, /execute\(run\.kind, run\.summary\.retryIds, run\.params, run\)/, 'Retry re-sends only failed items, in the same run');
  assert.match(hook, /const runId = previous\?\.runId \?\?/);
  assert.match(hook, /idempotencyKeyFor\(itemKeys\.current, runId, asset\.id,/);
  assert.match(hook, /for \(const id of summary\.rollbackIds\) delete next\[id\]/);
  const bar = feature('intelligence', 'batch-bar.tsx');
  assert.match(bar, /if \(count === 0 && !run\) return null;/, 'batch actions appear only after selection');
  assert.match(bar, /OUTCOME_TEXT\[outcome\.status\]/, 'each item reports its own result');
  assert.match(bar, /Delete selected…/);
  assert.match(bar, /<AlertDialog open=\{confirmDelete\}/, 'delete keeps its own confirmation');
  assert.match(bar, /actionType: 'source_pack\.create'/);
  assert.match(bar, /api\.libraryRecommendSources\(/);
});

test('test_drawer_focus_restore: the sheet and drawer trap focus, close on Escape and return focus to the opener', () => {
  const detail = feature('asset-detail.tsx');
  assert.match(detail, /<DrawerContent[^>]*finalFocus=\{finalFocus\}/);
  assert.match(detail, /<SheetContent[^>]*finalFocus=\{finalFocus\}/);
  assert.match(detail, /const selector = asset \? openerSelector\(asset\.id\) : null;/);
  assert.doesNotMatch(detail, /modal=\{false\}|disablePointerDismissal/, 'modal (focus-trapping, Escape-closable) primitives');
  assert.match(detail, /aria-label='Close asset details'/);
  for (const file of ['asset-card.tsx', 'asset-list-row.tsx']) assert.match(feature(file), /data-library-open=\{asset\.id\}/, file);
  assert.equal(U.openerSelector('2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f'), '[data-library-open="2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f"]');
  assert.equal(U.openerSelector('x"], body'), null, 'never builds a selector from an unsafe id');
  // Returning from detail or a draft restores the same view.
  const view = feature('library-view.tsx');
  assert.match(view, /scrollKey\(workspaceId, \{ \.\.\.url, q: query \}\)/);
  assert.match(view, /window\.sessionStorage\.setItem\(viewKey/);
});

test('test_bottom_bars_no_overlap: the batch bar and last result clear the tab bar, Now Playing and safe area', () => {
  assert.ok(read('components', 'layout', 'mobile-tab-bar.tsx').includes(`h-[calc(${L.TAB_BAR_REM}rem+env(safe-area-inset-bottom))]`), 'tab bar height matches');
  const player = read('features', 'now-playing', 'now-playing-bar.tsx');
  assert.ok(player.includes(`bottom-[calc(${L.PLAYER_BOTTOM_MOBILE_REM}rem+env(safe-area-inset-bottom))]`), 'player offset matches');
  assert.ok(player.includes('md:bottom-5'));
  assert.ok(read('components', 'layout', 'app-shell.tsx').includes(`pb-[calc(${L.TAB_BAR_REM}rem+env(safe-area-inset-bottom))]`), 'the shell pads for the tab bar');

  const phone = L.bottomClearance({ mobile: true, playerOpen: true });
  const playerTop = L.PLAYER_BOTTOM_MOBILE_REM + L.PLAYER_HEIGHT_REM;
  assert.equal(phone.coveredRem, playerTop);
  assert.equal(phone.stickyBottom, `calc(${playerTop + L.GAP_REM}rem + env(safe-area-inset-bottom))`, 'the batch bar sits above the player and the tab bar');
  assert.ok(parseFloat(phone.spacer) >= playerTop - L.TAB_BAR_REM, 'the last result scrolls clear of the player');
  const idle = L.bottomClearance({ mobile: true, playerOpen: false });
  assert.equal(idle.spacer, '0rem');
  assert.equal(idle.stickyBottom, `calc(${L.TAB_BAR_REM + L.GAP_REM}rem + env(safe-area-inset-bottom))`);
  assert.equal(L.bottomClearance({ mobile: false, playerOpen: true }).coveredRem, L.PLAYER_BOTTOM_DESKTOP_REM + L.PLAYER_HEIGHT_REM);
  assert.equal(L.bottomClearance({ mobile: true, playerOpen: true, playerExpanded: true }).coveredRem, playerTop + L.PLAYER_VIDEO_REM);

  const view = feature('library-view.tsx');
  assert.match(view, /bottomClearance\(\{ mobile: isMobile, playerOpen: Boolean\(track\)/);
  assert.match(view, /style=\{\{ height: clearance\.spacer \}\}/);
  assert.match(view, /stickyBottom=\{clearance\.stickyBottom\}/);
  const bar = feature('intelligence', 'batch-bar.tsx');
  assert.match(bar, /style=\{\{ bottom: stickyBottom \}/);
  assert.match(bar, /'rafii-elevated sticky/);
  assert.match(bar, /prefers-reduced-transparency:reduce\)\]:bg-popover/, 'glass has an opaque fallback');
  assert.match(feature('asset-detail.tsx'), /pb-\[max\(1rem,env\(safe-area-inset-bottom\)\)\]/, 'the drawer footer clears the home indicator');
});

test('test_mobile_first_asset_visible: compact chrome puts the first item on screen at 390 × 844', () => {
  const layout = L.mobileFirstAsset();
  assert.ok(layout.visible, JSON.stringify(layout));
  assert.ok(layout.titleBottom <= 844 - L.TAB_BAR_REM * 16);
  assert.ok(Math.round(layout.cardWidth) >= 160, 'two readable columns');

  const view = feature('library-view.tsx');
  assert.doesNotMatch(view, /CollectionManager|Manage collections|workspace storage used/, 'no management accordion or storage line above results');
  assert.match(view, /\{notice\?\.warning \? <StateMessage/, 'storage speaks up only near the limit');
  assert.match(view, /comfortable: 'grid grid-cols-2 /);
  const order = ['<LibrarySearchField', '<CollectionRail', '<LibraryFilters', '{content}'].map((marker) => view.indexOf(marker));
  assert.deepEqual([...order].sort((a, b) => a - b), order, 'search, collection switcher, filters, then results');
  assert.ok(order.every((index) => index > 0));
  const rail = feature('intelligence', 'collection-rail.tsx');
  assert.match(rail, /overflow-x-auto/, 'the phone switcher is one row that scrolls inside itself');
  assert.match(rail, /Manage collections/);
  assert.doesNotMatch(feature('library-organizer.tsx'), /Manage collections/);

  assert.equal(W.storageNotice(100, 1000).warning, null);
  assert.equal(W.storageNotice(900, 1000).level, 'near');
  assert.match(W.storageNotice(900, 1000).warning, /almost full/);
  assert.equal(W.storageNotice(1000, 1000).level, 'full');
  assert.equal(W.storageNotice(undefined, 1000).level, 'unknown');
});

test('test_animated_counts_single_accessible_name: digits are hidden, one label speaks, plurals are right', () => {
  for (const { file, text } of sources()) {
    if (file.endsWith('animated-count.tsx')) continue;
    assert.doesNotMatch(text, /DigitSwap/, `${file}: animated digits go through AnimatedCount`);
  }
  const count = feature('intelligence', 'animated-count.tsx');
  assert.match(count, /<span className='sr-only'>\{spoken\}<\/span>/);
  assert.match(count, /<span aria-hidden='true'[^>]*>\s*<DigitSwap/);
  assert.equal((count.match(/sr-only/g) || []).length, 1);
  const toolbar = feature('intelligence', 'library-toolbar.tsx');
  assert.match(toolbar, /ariaLabel: counts \? `\$\{text\}, \$\{countLabel\(counts\[value\]\)\}` : text/, 'each filter segment has one spoken name');

  assert.equal(W.countLabel(1), '1 item');
  assert.equal(W.countLabel(0), '0 items');
  assert.equal(W.countLabel(2), '2 items');
  assert.equal(W.countLabel(1200), '1,200 items');
  assert.equal(W.countLabel(1, 'match', 'matches'), '1 match');
  assert.equal(W.countLabel(3, 'match', 'matches'), '3 matches');
  assert.equal(W.totalLabel({ total: 1500, loaded: 200, complete: false }), '1,500 items', 'a server total wins');
  assert.equal(W.totalLabel({ total: null, loaded: 200, complete: false }), '200 loaded · more available', 'loaded cards are never passed off as the total');
  assert.equal(W.totalLabel({ loaded: 1, complete: true }), '1 item');
});

test('navigation state: stable ids only, defaults omitted, signed links never reach the address', () => {
  const state = { ...U.DEFAULT_LIBRARY_STATE, q: 'Brahms rehearsal', scope: 'selection', use: 'unused', kind: 'audio', mode: 'list', density: 'compact', sel: ['2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f', 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'], asset: 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6' };
  const params = U.serializeLibraryState(state);
  assert.deepEqual(Object.keys(params), ['q', 'scope', 'use', 'kind', 'mode', 'density', 'sel', 'asset']);
  assert.deepEqual(U.parseLibraryState(new URLSearchParams(params)), state);
  assert.equal(U.libraryHref({}), '/app/library');
  assert.equal(U.safeQuery('https://storage.example/obj?token=abc'), '');
  assert.equal(U.safeQuery('notes?X-Amz-Signature=1'), '');
  assert.deepEqual(U.sanitizeIds(['ok-id-1234', 'https://x', '../etc', 'ok-id-1234', 'a:b']), ['ok-id-1234']);
  assert.equal(U.sanitizeIds(Array.from({ length: 300 }, (_, index) => `item-${String(index).padStart(4, '0')}`)).length, U.MAX_SELECTED);
  assert.equal(U.parseLibraryState({ asset: 'https://x/y', mode: 'carousel', sel: 'abcd1234,../x' }).asset, '');
  assert.equal(U.parseLibraryState({ mode: 'carousel' }).mode, 'gallery');
  assert.deepEqual(U.reconcileSelection(['a1b2c3d4', 'gone1234'], ['A1B2-C3D4'], true), { kept: ['a1b2c3d4'], dropped: 1 });
  assert.deepEqual(U.reconcileSelection(['a1b2c3d4', 'notloaded'], ['a1b2c3d4'], false), { kept: ['a1b2c3d4', 'notloaded'], dropped: 0 }, 'an incomplete list cannot prove absence');
  assert.deepEqual(U.assetRefFor('2F0C6C1E-5A1B-4C6A-9D0E-3B2A1C0D9E8F'), { assetId: '2f0c6c1e5a1b4c6a9d0e3b2a1c0d9e8f', versionId: '', sha256: '' });
  assert.ok(!U.scrollKey('ws', state).includes('sel='), 'scroll is kept per view, not per selection');
});

test('detail: sections, provenance in words, no voice scores, and a separate danger area', () => {
  const detail = feature('asset-detail.tsx');
  for (const section of ["id='overview' title='Overview'", "id='content' title='Content'", "id='related' title='Related'", "id='usage' title='Usage'"]) assert.ok(detail.includes(section), section);
  assert.match(detail, /<summary[^>]*>\s*Technical details/, 'hash and MIME sit in an expandable area');
  assert.match(detail, /<DangerArea /);
  assert.match(detail, /DocumentText/);
  const sections = feature('intelligence', 'detail-sections.tsx');
  assert.match(sections, /attestation: \{ authoredByMe: true \}/, 'My voice needs the owner’s authorship statement');
  assert.match(sections, /I wrote or said this myself/);
  assert.doesNotMatch(sections, /confidence|%\s*match|matchPercent|similarity/i, 'no match percentages anywhere');
  assert.match(sections, /Metrics: unknown/);
  assert.match(sections, /'unknown'/);
  assert.equal(W.originLabel('ai_suggested'), 'AI suggestion');
  assert.equal(W.originLabel('user_confirmed'), 'Confirmed by you');
  assert.equal(W.originLabel('extracted'), 'Extracted');
  assert.match(sections, /ORIGIN_ICON\[origin as keyof typeof ORIGIN_ICON\]/, 'origin has an icon as well as words');
  assert.deepEqual(
    W.purposeLines({ voice: { allowed: false, reason: 'not_author' }, browse: { allowed: true } }).map((line) => `${line.label}: ${line.detail}`),
    ['Find and open it in Library: Allowed', 'Learn your writing voice from it: Not allowed · only material you wrote can teach your voice']
  );
  assert.equal(W.locatorLabel({ kind: 'time', startMs: 83000, endMs: 101000 }), '1:23–1:41');
  assert.equal(W.locatorLabel({ kind: 'page', page: 4, section: 'Programme' }), 'Page 4 · Programme');
  assert.equal(W.locatorLabel({ kind: 'sheet', sheetName: 'Budget', cellRange: 'A1:C9' }), 'Budget · A1:C9');
  assert.equal(W.matchSummary([{ kind: 'phrase' }, { kind: 'title' }, { kind: 'phrase' }]), 'Matched: Exact phrase · Title');
});

test('now playing: seek moves the loaded track in place and refuses other items', () => {
  const media = load(path.join(SRC, 'lib', 'media', 'now-playing.ts'));
  const store = media.useNowPlaying;
  store.getState().close();
  assert.equal(store.getState().seek(10), false, 'nothing loaded');
  store.getState().open({ kind: 'audio', workspaceId: 'w', assetId: 'a', title: 'Take', url: '/take' });
  store.getState().setPosition(0, 60);
  assert.equal(store.getState().seek(12, 'b'), false, 'another item');
  assert.equal(store.getState().seek(12, 'a'), true);
  const first = store.getState().seekRequest;
  assert.deepEqual({ assetId: first.assetId, seconds: first.seconds }, { assetId: 'a', seconds: 12 });
  assert.equal(store.getState().seconds, 12);
  store.getState().seek(90, 'a');
  assert.equal(store.getState().seekRequest.seconds, 60, 'bounded by the known duration');
  assert.notEqual(store.getState().seekRequest.nonce, first.nonce);
  store.getState().close();
  assert.equal(store.getState().seekRequest, null);
  const bar = read('features', 'now-playing', 'now-playing-bar.tsx');
  assert.match(bar, /seekRequest\.assetId !== track\.assetId/);
  assert.equal(W.hitTotalLabel({ value: 1000, relation: 'gte' }), '1,000+ matching items');
  assert.equal(W.hitTotalLabel({ value: 1, relation: 'eq' }), '1 matching item');
  assert.equal(W.hitTotalLabel(null), null);
});

const HEX = (character) => character.repeat(32);
const REF = (character, version = character) => ({ assetId: HEX(character), versionId: HEX(version), sha256: '' });

test('smart rule builder: only the server allowlist of fields, operators and value types', () => {
  assert.deepEqual(Object.keys(R.RULE_FIELDS), ['kind', 'tag', 'title_contains', 'filename_contains', 'created_after', 'created_before', 'mime_prefix', 'language', 'capability', 'source_kind', 'duration_ms', 'orientation', 'usage', 'text_matches']);
  assert.equal(R.isRuleField('sql'), false);
  assert.equal(R.validateRow({ field: 'sql', op: 'raw', value: 'DROP TABLE x' }), 'Choose a criterion from the list.');
  assert.match(R.validateRow({ field: 'tag', op: 'like', value: 'x' }), /Choose how tag should match/);
  assert.match(R.validateRow({ field: 'title_contains', op: 'contains', value: 'see https://evil.example' }), /plain words/);
  assert.match(R.validateRow({ field: 'text_matches', op: 'matches', value: 'select name from users' }), /plain words/);
  assert.equal(R.validateRow({ field: 'kind', op: 'in', value: ['audio', 'video'] }), null);
  assert.match(R.validateRow({ field: 'kind', op: 'in', value: ['spreadsheet'] }), /Choose from the listed types/);
  assert.match(R.validateRow({ field: 'duration_ms', op: 'gte', value: 1.5 }), /24 hours/);
  assert.match(R.validateRow({ field: 'created_after', op: 'on_or_after', value: '08/10/2026' }), /2026-10-08/);
  assert.match(R.validateRow({ field: 'title_contains', op: 'contains', value: 'a\u0000b' }), /characters/);
  assert.match(R.validateRow({ field: 'capability', op: 'in', value: ['ready'] }), /processing step/);
  assert.equal(R.validateRow({ field: 'capability', op: 'in', value: ['ready'], capability: 'transcribe' }), null);

  const built = R.buildRule({ join: 'any', rows: [{ field: 'tag', op: 'has', value: ' recital ' }, { field: 'created_after', op: 'on_or_after', value: '2026-09-01', timeZone: 'Asia/Hong_Kong' }] });
  assert.deepEqual(built, { ok: true, rule: { any: [{ field: 'tag', op: 'has', value: 'recital', origin: 'user' }, { field: 'created_after', op: 'on_or_after', value: '2026-09-01', timeZone: 'Asia/Hong_Kong' }] } });
  assert.equal(R.buildRule({ join: 'all', rows: [] }).ok, false);
  assert.equal(R.buildRule({ join: 'all', rows: [{ field: 'usage', op: 'eq', value: 'maybe' }] }).ok, false);
  assert.deepEqual(R.draftFromRule(built.rule), { join: 'any', rows: [{ field: 'tag', op: 'has', value: 'recital', origin: 'user' }, { field: 'created_after', op: 'on_or_after', value: '2026-09-01', timeZone: 'Asia/Hong_Kong' }] });
  assert.equal(R.draftFromRule({ all: [{ any: [{ field: 'tag', op: 'has', value: 'x' }] }] }), null, 'nested groups stay as saved');
  assert.deepEqual(R.parseList('yue, en ,yue,'), ['yue', 'en']);

  const builder = fs.readFileSync(path.join(FEATURE, 'intelligence', 'smart-collections.tsx'), 'utf8');
  assert.doesNotMatch(builder, /<textarea/, 'no free-form rule text');
  assert.match(builder, /Object\.entries\(RULE_FIELDS\)\.map/, 'the field picker lists the allowlist only');
  assert.match(builder, /\{preview\.result\.explanation\}/, 'the explanation is the server’s');
  assert.match(builder, /disabled=\{busy !== null \|\| !previewCurrent\}/, 'saving needs a preview of the current criteria');
});

test('smart collection preview, save, override and undo use the server revision', () => {
  const summary = R.previewSummary({ count: 14, changes: { added: { count: 3 }, removed: { count: 1 } }, coverage: { partial: false, notYetProcessed: 2 } });
  assert.equal(summary.line, '14 items · 3 joining · 1 leaving · 2 still processing');
  assert.equal(R.previewSummary({ count: 1, changes: null }).line, '1 item', 'a new collection has no before');
  const save = R.saveEnvelope({ all: [] }, { name: 'Recital', collectionId: null, revision: 5, actionId: 'a1' });
  assert.equal(save.actionType, 'collection.save');
  assert.equal(save.expectedRevision, null, 'a new collection sends no revision');
  assert.deepEqual(save.payload, { rule: { all: [] }, name: 'Recital' });
  const edit = R.saveEnvelope({ all: [] }, { collectionId: HEX('c'), revision: 5, actionId: 'a2' });
  assert.equal(edit.expectedRevision, 5);
  assert.deepEqual(edit.payload, { rule: { all: [] }, collectionId: HEX('c') });
  const exclude = R.overrideEnvelope(HEX('c'), 'exclude', [REF('a')], 6, 'a3');
  assert.deepEqual([exclude.actionType, exclude.expectedRevision, exclude.payload], ['collection.override', 6, { collectionId: HEX('c'), mode: 'exclude' }]);
  const undo = R.undoEnvelope(HEX('c'), 7, 'a4');
  assert.deepEqual([undo.actionType, undo.expectedRevision, undo.targetRefs, undo.payload], ['collection.undo', 7, [], { collectionId: HEX('c') }]);

  const panel = fs.readFileSync(path.join(FEATURE, 'intelligence', 'smart-collections.tsx'), 'utf8');
  assert.match(panel, /undoEnvelope\(collection\.id, collection\.revision,/);
  assert.match(panel, /\{canUndo \? \(/, 'undo only when the server says there is something to restore');
  assert.match(panel, /Re-evaluating membership…/);
  assert.match(panel, /evaluationCurrent \? 4000 : false|!query\.state\.data\.collection\.evaluationCurrent \? 4000 : false/);
  const hook = fs.readFileSync(path.join(FEATURE, 'intelligence', 'use-batch-actions.ts'), 'utf8');
  assert.match(hook, /overrideEnvelope\(collectionId, kind === 'collection-include' \? 'include' : 'exclude'/);
  assert.match(hook, /\(asset\.collections \?\? \[\]\)\.filter\(\(id\) => manualCollectionIds\.has\(id\)\)/, 'item edits never send smart collection ids');
  const organizer = fs.readFileSync(path.join(FEATURE, 'library-organizer.tsx'), 'utf8');
  assert.match(organizer, /filter\(\(c\) => c\.kind !== 'smart'\)/);
});

test('version comparison is honest about unsupported pairs, and replacement always needs confirmation', () => {
  assert.deepEqual(V.comparisonHeadline({ mode: 'unsupported', supported: false, message: 'Comparison of these two formats is not supported. Their details are compared below.' }), {
    supported: false,
    line: 'Comparison of these two formats is not supported. Their details are compared below.'
  });
  assert.equal(V.comparisonHeadline({ mode: 'unsupported', supported: false }).line, V.UNSUPPORTED_COMPARISON);
  assert.equal(V.comparisonHeadline({ mode: 'text', supported: true, text: { summary: { added: 2, removed: 1, changed: 0, unchanged: 9 }, available: true, truncated: false } }).line, '2 lines added · 1 line removed');
  assert.equal(V.comparisonHeadline({ mode: 'text', supported: true, text: { summary: { added: 0, removed: 0, changed: 0, unchanged: 9 }, available: true, truncated: false } }).line, 'No text differences.');
  assert.match(V.comparisonHeadline({ mode: 'image', supported: true, image: { sameDimensions: false } }).line, /does not judge which is better/);
  assert.equal(V.comparisonHeadline({ mode: 'media', supported: true, media: { durationDeltaMs: -4000 } }).line, 'The newer version is 4 s shorter.');
  assert.deepEqual(V.diffRows([{ op: 'equal', count: 3 }, { op: 'replace', left: [{ text: 'old' }], right: [{ text: 'new' }], clipped: true }]), [
    { type: 'same', count: 3 },
    { type: 'removed', text: 'old', locator: undefined },
    { type: 'added', text: 'new', locator: undefined },
    { type: 'clipped' }
  ]);

  const entry = { kind: 'source_pack', key: HEX('p'), label: 'Spring pack', citesVersion: REF('a', 'a'), currentVersion: REF('a', 'b'), flagged: true };
  const plan = V.replacementPlan(entry, [{ versionNo: 1, assetRef: REF('a', 'a') }, { versionNo: 2, assetRef: REF('a', 'b') }]);
  assert.equal(plan.requiresConfirmation, true);
  assert.equal(plan.title, 'Use version 2 instead of version 1 in “Spring pack”?');
  assert.equal(plan.revisionSource, 'source_pack');
  assert.ok(plan.consequences.some((line) => /Approval of the old version does not carry over/.test(line)));
  assert.equal(V.replacementEnvelope(plan, { confirmed: false, expectedRevision: 3, actionId: 'r1' }), null, 'never without confirmation');
  assert.equal(V.replacementEnvelope(plan, { confirmed: true, expectedRevision: null, actionId: 'r1' }), null, 'never without the revision it was checked against');
  const envelope = V.replacementEnvelope(plan, { confirmed: true, expectedRevision: 3, actionId: 'r1' });
  assert.deepEqual([envelope.actionType, envelope.expectedRevision, envelope.targetRefs, envelope.payload], ['version.accept_replacement', 3, [REF('a', 'a'), REF('a', 'b')], { dependentKind: 'source_pack', dependentKey: HEX('p') }]);
  assert.equal(V.replacementPlan({ ...entry, kind: 'draft' }, []).revisionSource, 'organization');
  assert.equal(V.linkVersionEnvelope(REF('a'), REF('a'), 1, 'l1'), null, 'an item is not its own version');
  assert.deepEqual(V.linkVersionEnvelope(REF('b'), REF('a'), 4, 'l1').payload, { relation: 'version_of' });

  const panel = fs.readFileSync(path.join(FEATURE, 'intelligence', 'versions-panel.tsx'), 'utf8');
  assert.match(panel, /replacementEnvelope\(confirmed, \{ confirmed: true,/);
  const confirmCalls = panel.split('\n').filter((line) => line.includes('confirmReplacement('));
  assert.ok(confirmCalls.some((line) => /if \(plan\) void confirmReplacement\(plan\)/.test(line)), 'replacement runs from the confirmation button');
  assert.equal(confirmCalls.filter((line) => !/async function confirmReplacement|if \(plan\) void confirmReplacement\(plan\)/.test(line)).length, 0, 'and from nowhere else');
  assert.doesNotMatch(panel, /merge|deleteLibraryFile|Delete/, 'near duplicates offer no merge or delete');
  assert.match(panel, /<OriginBadge origin='ai_suggested' \/>/, 'near duplicates are labelled as suggestions');
});

test('ask library: explicit scope, explicit permission, honest abstention, fresh citation links', () => {
  assert.deepEqual(A.answerRequest('  When is the recital? ', { kind: 'collection', collectionId: HEX('c') }), { question: 'When is the recital?', search: { query: '', scope: { kind: 'collection', collectionId: HEX('c') } } });
  const grants = [{ grantType: 'purpose', scopeKind: 'collection', scopeKey: HEX('c'), purpose: 'answer', location: null, category: null }];
  assert.deepEqual(A.answerPermission(grants, { kind: 'collection', collectionId: HEX('c') }), { answers: true, summaries: false });
  assert.deepEqual(A.answerPermission(grants, { kind: 'workspace' }), { answers: false, summaries: false }, 'a collection grant does not open the whole Library');
  assert.deepEqual(A.answerPermission([{ grantType: 'processing', scopeKind: 'workspace', scopeKey: '*', purpose: null, location: 'cloud', category: 'llm' }], { kind: 'workspace' }), { answers: false, summaries: true });
  assert.deepEqual(A.SUMMARY_GRANT, { grantType: 'processing', scope: { kind: 'workspace' }, location: 'cloud', category: 'llm' });
  assert.equal(A.answerModeLabel('extractive'), 'Verbatim quotations from the sources (no AI summary)');
  const coverage = { scopeDescription: 'This collection', accessibleAssetCount: 4, pendingAssetCount: 2, failedAssetCount: 1 };
  assert.deepEqual(A.abstentionLines({ scope: 'This collection', coverage, scopeCoverage: { ...coverage, pendingAssetCount: 3 } }), [
    'The selected material doesn’t support an answer.',
    'Searched: This collection.',
    '3 items are still being processed and may help later.',
    '1 item could not be read fully.'
  ]);
  assert.equal(A.supportLabel({ support: 'conflicting', kind: 'conflict' }), 'Sources disagree');
  assert.equal(A.supportLabel({ support: 'supported', kind: 'quotation' }), 'Quotation');
  const cited = { assetRef: REF('a', 'b'), segmentId: HEX('s'), locator: { kind: 'page', page: 3 }, quoteHash: 'f'.repeat(64), displayTitle: 'Programme', excerpt: 'Doors at 7', locatorLabel: 'Page 3' };
  assert.deepEqual(Object.keys(A.sourceRefOnly(cited)), ['assetRef', 'segmentId', 'locator', 'quoteHash'], 'only identity fields go to the viewer');
  assert.equal(A.citationKey(REF('a', 'b'), { page: 3, kind: 'page' }), A.citationKey(REF('a', 'b'), { kind: 'page', page: 3 }));

  const old = { isCurrentVersion: false, versionNo: 1, mime: 'application/pdf', kind: 'document', locator: { kind: 'page', page: 3 }, target: { kind: 'signedUrl', url: 'https://storage.example/obj?sig=1', expiresAt: 2000 } };
  const plan = A.viewerOpenPlan(old, 1000);
  assert.equal(plan.href, 'https://storage.example/obj?sig=1#page=3');
  assert.equal(plan.newerVersion, true);
  assert.match(plan.versionNote, /version 1\. A newer version exists; this view stays on the cited version/);
  assert.equal(A.viewerOpenPlan(old, 3000).href, null, 'an expired link is never used');
  assert.equal(A.viewerOpenPlan({ ...old, mime: 'audio/mpeg', kind: 'audio', locator: { kind: 'time', startMs: 83000, endMs: 90000 } }, 1000).playFrom, 83);

  const panel = fs.readFileSync(path.join(FEATURE, 'intelligence', 'ask-library.tsx'), 'utf8');
  assert.match(panel, /api\.libraryAnswer\(workspaceId, answerRequest\(question, scope\), abort\.signal\)/);
  assert.match(panel, /const \{ target, \.\.\.info \} = data;/, 'the viewer link is not kept in state');
  assert.match(panel, /<SourceCitation key=/, 'citations render with the deterministic OpenUI component');
  assert.match(panel, /<SourceScope /);
  const view = feature('library-view.tsx');
  assert.match(view, /<div hidden=\{asking\} className=/, 'switching to Ask keeps the search results mounted');
  assert.match(view, /label='Library mode'/);
  const client = read('lib', 'api', 'client.ts');
  assert.match(client, /search: LibrarySearchRequest & \{ scope: LibraryScope \}/, 'the client type requires a scope');
  assert.match(client, /intelligence<ViewerResult>\(w, 'POST', 'viewer', \{\s*sourceRef:/);
});

