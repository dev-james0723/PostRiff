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

  // Documents show a server-rendered source page (PR #134); before it exists they say "Preparing preview" or
  // "Preview unavailable", never a stand-in that looks like the page.
  const thumbnail = feature('asset-thumbnail.tsx');
  for (const banned of ['SHEET PREVIEW', 'SLIDE PREVIEW', 'WORD · FIRST PAGE', 'DOCUMENT · FIRST PAGE', 'TEXT PREVIEW', 'charCodeAt', 'asset.aiSummary', '<iframe']) assert.ok(!thumbnail.includes(banned), banned);
  // The real page needs no badge on the tile (James, 2026-10-09): the raster carries data-thumbnail-preview and the
  // card's accessible name says "first-page preview"; no visible "PDF · PAGE 1" chip.
  assert.ok(!thumbnail.includes('· PAGE 1'), 'no page badge on the tile');
  assert.match(thumbnail, /data-thumbnail-preview='first-page-raster'/);
  assert.match(thumbnail, /api\.libraryPreviewUrl\(workspaceId, asset\.id\)/);
  assert.match(thumbnail, /'Preparing preview' : failed \? 'No preview' : 'Preview unavailable'/);
  // A file the server could not read is never shown as still preparing.
  assert.match(thumbnail, /preparing=\{!failed && /);
  // Card and row names say what the cover is: a first page only once a raster can exist.
  assert.match(thumbnail, /if \(PREVIEW_READY\.includes\(asset\.processing \|\| ''\)\) return ', first-page preview';/);
  assert.match(thumbnail, /preview being prepared/);
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
  const audioCover = thumbnail.slice(thumbnail.indexOf('function AudioCover'), thumbnail.indexOf('export function AssetFileThumbnail'));
  assert.match(audioCover, /peaksToBars\(peaks,/);
  assert.match(audioCover, /bars \? 'audio-waveform' : 'audio-file'/);
  assert.doesNotMatch(audioCover, /hash|seed|asset\.id/, 'no bars derived from the file identity');
  assert.match(feature('asset-detail.tsx'), /peaks=\{card\?\.media\?\.peaks \?\? null\}/, 'the detail uses the understanding card peaks');

  // The gallery's inline preview (PR #134) is the one other media element: video starts muted and loops only while in
  // view (a press under reduced motion), audio waits for a press, and either pauses when Now Playing or another preview plays.
  const inline = feature('gallery-media-preview.tsx');
  assert.match(inline, /useState\(video \? 0 : 0\.8\)/, 'video previews start muted');
  assert.match(inline, /video \? visible && \(activated \|\| ownsSilent\) : activated/, 'audio plays only after a press; video after a press or while it holds the silent slot');
  // One silent video preview at a time: the slot is claimed only while motion is allowed, released otherwise.
  assert.match(inline, /const eligible = enabled && ready && visible && foreground && !reduce && !userPaused && !activated;/);
  assert.match(inline, /if \(eligible\) claimSilent\(slot\);\s*else releaseSilent\(slot\);/);
  assert.match(inline, /if \(silentOwner === slot \|\| \(silentOwner && !force\)\) return;/, 'a second video never takes the slot unless pointed at');
  // Speed and volume sit behind Playback options; play, time and the timeline stay visible.
  assert.match(inline, /label='Playback options'/);
  assert.match(inline, /useNowPlaying\.subscribe\(/, 'Now Playing pauses an inline preview');
  assert.match(inline, /window\.dispatchEvent\(new CustomEvent\(PLAY_EVENT/, 'one audible preview at a time');
  for (const { file, text } of sources()) {
    assert.doesNotMatch(text, /autoPlay|autoplay/, `${file}: no autoplay`);
    if (file !== 'gallery-media-preview.tsx') assert.doesNotMatch(text, /<audio[\s>]|<video[\s>]/, `${file}: the Now Playing bar owns playback outside the inline preview`);
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
  assert.match(bar, /onClick=\{onBuildPack\}/, 'the batch bar opens the one source-pack flow');
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /api\.libraryRecommendSources\(/);
  assert.match(fs.readFileSync(path.join(LIB, 'source-pack.ts'), 'utf8'), /actionType: 'source_pack\.create'/);
});

test('test_drawer_focus_restore: the sheet and drawer trap focus, close on Escape and return focus to the opener', () => {
  const detail = feature('asset-detail.tsx');
  assert.match(detail, /<DrawerContent[^>]*finalFocus=\{finalFocus\}/);
  assert.match(detail, /<SheetContent[^>]*finalFocus=\{finalFocus\}/);
  assert.match(detail, /const selector = asset \? openerSelector\(asset\.id\) : null;/);
  assert.doesNotMatch(detail, /modal=\{false\}|disablePointerDismissal/, 'modal (focus-trapping, Escape-closable) primitives');
  assert.match(detail, /label='Close asset details'/, 'every form of the panel has a named close control');
  // Docked (from 1280 px) the inspector is non-modal: Escape closes it and focus returns to the card that opened it.
  assert.match(detail, /if \(event\.key !== 'Escape' \|\| event\.defaultPrevented\) return;\s*if \(!panelRef\.current\?\.contains\(document\.activeElement\)\) return;/);
  assert.match(detail, /const opener = finalFocus\(\);\s*onOpenChange\(false\);/);
  assert.match(detail, /aria-labelledby='library-inspector-title'/);
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
  assert.match(toolbar, /const withCount = \(text: string, value: number \| undefined\) => \(typeof value === 'number' \? `\$\{text\} · \$\{value\.toLocaleString\(\)\}` : text\)/, 'each filter option has one spoken name, its count joined to the words');

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
  const state = { ...U.DEFAULT_LIBRARY_STATE, q: 'Brahms rehearsal', scope: 'selection', use: 'unused', kind: 'audio', mode: 'list', density: 'compact', sel: ['2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f', 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6'], asset: 'a1b2c3d4e5f6a7b8c9d0e1f2a3b4c5d6' };  // pragma: allowlist secret -- synthetic asset UUIDs
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
  assert.deepEqual(U.assetRefFor('2F0C6C1E-5A1B-4C6A-9D0E-3B2A1C0D9E8F'), { assetId: '2f0c6c1e5a1b4c6a9d0e3b2a1c0d9e8f', versionId: '', sha256: '' });  // pragma: allowlist secret -- synthetic asset UUID
  assert.ok(!U.scrollKey('ws', state).includes('sel='), 'scroll is kept per view, not per selection');
});

test('detail: sections, provenance in words, no voice scores, and a separate danger area', () => {
  const detail = feature('asset-detail.tsx');
  for (const section of ["id='overview' title='Overview'", "id='content' title='Content'", "id='related' title='Related'", "id='usage' title='Usage'"]) assert.ok(detail.includes(section), section);
  assert.match(detail, /<summary[^>]*>\s*Technical details/, 'hash and MIME sit in an expandable area');
  assert.match(detail, /<DangerArea /);
  assert.match(detail, /DocumentText/);
  const sections = feature('intelligence', 'detail-sections.tsx');
  const voicePanel = feature('intelligence', 'voice-panel.tsx');
  assert.match(voicePanel, /I wrote or said this myself/, 'My voice needs the owner’s authorship statement');
  assert.doesNotMatch(sections + voicePanel, /confidence|%\s*match|matchPercent|similarity/i, 'no match percentages anywhere');
  assert.match(feature('intelligence', 'usage-panel.tsx'), /Metrics: unknown/);
  assert.match(detail, /<VoicePanel /);
  assert.match(detail, /<UsagePanel usage=\{usage\} \/>/);
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
  assert.match(hook, /\(fresh\.collections \?\? \[\]\)\.filter\(\(value\) => manualCollectionIds\.has\(value\)\)/, 'item edits never send smart collection ids');
  assert.match(hook, /const fresh = await readFresh\(/, 'collection edits start from the item as re-read, not a cached copy');
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

const P2 = load(path.join(LIB, 'proactive.ts'));

test('suggestions: honest cap, in-app only, set_state payloads, critical warnings cannot be switched off', () => {
  const inbox = { cap: { noncriticalPerDay: 3, shownToday: 1 }, delivery: { channels: ['in_app'], external: false, note: 'Suggestions stay inside Rafii.' } };
  assert.equal(P2.capLine(inbox), 'At most 3 new suggestions a day (1 today); permission and source warnings always show. Shown only here in Rafii.');
  assert.ok(!P2.capLine({ ...inbox, delivery: { channels: ['in_app', 'other'], external: true } }).includes('only here'), 'never claims in-app only when the server says otherwise');
  const item = { id: HEX('s'), category: 'unused_relevant', critical: false, actions: ['open', 'dismiss', 'snooze', 'disable_category'] };
  assert.deepEqual(P2.suggestionEnvelope(item, 'dismiss', { actionId: 'a' }).payload, { suggestionId: HEX('s'), action: 'dismiss' });
  assert.deepEqual(P2.suggestionEnvelope(item, 'snooze', { actionId: 'a' }).payload, { suggestionId: HEX('s'), action: 'snooze', snoozeDays: 7 }, 'snooze defaults to 7 days');
  assert.equal(P2.suggestionEnvelope(item, 'snooze', { snoozeDays: 400, actionId: 'a' }).payload.snoozeDays, 90);
  assert.equal(P2.suggestionEnvelope(item, 'snooze', { snoozeDays: 0, actionId: 'a' }).payload.snoozeDays, 1);
  assert.deepEqual(P2.suggestionEnvelope(item, 'disable_category', { actionId: 'a' }).payload, { suggestionId: HEX('s'), action: 'disable_category' });
  assert.equal(P2.suggestionEnvelope(item, 'apply', { actionId: 'a' }), null, 'apply only on organization proposals');
  const critical = { id: HEX('c'), category: 'permission', critical: true, actions: ['open', 'dismiss', 'snooze', 'disable_category'] };
  assert.equal(P2.suggestionEnvelope(critical, 'disable_category', { actionId: 'a' }), null, 'a critical warning can never be switched off');
  assert.equal(P2.suggestionEnvelope(critical, 'dismiss', { actionId: 'a' }).actionType, 'suggestion.set_state');
  assert.equal(P2.affectedLabel({ kind: 'proposal', name: 'Recital', itemCount: 4 }), 'Proposed collection “Recital” · 4 items');
  const panel = feature('intelligence', 'suggestions-panel.tsx');
  assert.match(panel, /\{data\.delivery\.note\}/, 'the server’s in-app note is shown');
  assert.match(panel, /\{capLine\(data\)\}/);
  assert.match(panel, /item\.actions\.includes\('disable_category'\) && canDisable && !item\.critical/);
  assert.doesNotMatch(panel, /toast|email|push|notif|unread|badge|text-destructive|bg-red|animate-pulse/i, 'no toast storm, other channels or urgency styling');
  assert.match(feature('library-view.tsx'), /<SuggestionsPanel/);
});

test('voice: one passage at a time, explicit attestation, AI text approved separately, no scores anywhere', () => {
  const passages = P2.voicePassages([
    { id: 'a', kind: 'text', text: 'My own opening line.', locator: { kind: 'text', start: 0, end: 20 } },
    { id: 'b', kind: 'sheet', text: 'A1', locator: { kind: 'sheet', sheetName: 'S', cellRange: 'A1' } },
    { id: 'c', kind: 'transcript', text: 'Spoken.', locator: { kind: 'time', startMs: 0, endMs: 900 } },
    { id: 'd', kind: 'text', text: '   ', locator: { kind: 'text', start: 20, end: 23 } }
  ]);
  assert.deepEqual(passages.map((passage) => passage.id), ['a', 'c'], 'cells, image regions and empty text are never voice examples');
  const draft = { passage: passages[0], polarity: 'positive', personaId: 'default', language: 'en', attested: false, method: 'written_by_me', localAnalysis: true, writer: false, grantVoice: false, approveGeneratedText: false };
  assert.equal(P2.voiceApproval(draft, 2).ok, false, 'attestation is required');
  assert.match(P2.voiceApproval(draft, 2).reason, /wrote or said this yourself/);
  assert.equal(P2.voiceApproval({ ...draft, attested: true, passage: null }, 2).ok, false, 'a passage, never the whole file');
  assert.equal(P2.voiceApproval({ ...draft, attested: true, language: '' }, 2).ok, false, 'language is explicit');
  assert.equal(P2.voiceApproval({ ...draft, attested: true, personaId: 'bad persona!' }, 2).ok, false, 'persona is explicit');
  assert.equal(P2.voiceApproval({ ...draft, attested: true, localAnalysis: false }, 2).ok, false, 'a voice example says what it is for');
  const ok = P2.voiceApproval({ ...draft, attested: true, grantVoice: true }, 2);
  assert.deepEqual(ok.payload, {
    locator: { kind: 'text', start: 0, end: 20 },
    personaId: 'default',
    language: 'en',
    polarity: 'positive',
    attestation: { authoredByMe: true, method: 'written_by_me' },
    confirmed: true,
    uses: [{ purpose: 'analysis', route: 'local-rules' }],
    grantVoice: true
  });
  const negative = P2.voiceApproval({ ...draft, attested: true, polarity: 'negative', localAnalysis: false }, 2);
  assert.equal(negative.ok, true);
  assert.equal('uses' in negative.payload, false, 'a don’t-write-like-this example has no uses');
  assert.equal(P2.voiceApproval({ ...draft, attested: true, approveGeneratedText: true }, 2).payload.approveGeneratedText, true);
  assert.deepEqual(P2.voiceRevocation({ sampleId: HEX('v'), revision: 2, assetRef: REF('a') }, 'r').payload, { sampleId: HEX('v'), confirmed: true });
  assert.equal(P2.voiceCoverage([{ status: 'approved' }, { status: 'revoked' }], [{ status: 'approved' }]), '1 voice example · 1 “don’t write like this” example from this item');

  const panel = feature('intelligence', 'voice-panel.tsx');
  assert.match(panel, /result\.status === 'requires_confirmation'/, 'AI-written text answers requires_confirmation');
  assert.match(panel, /void approve\(true\)/, 'and is approved by a separate press');
  assert.match(panel, /actionType: 'voice\.approve_span'/);
  assert.match(panel, /<fieldset disabled=\{!canApprove \|\| reference \|\| busy\}/, 'owner-only controls are disabled for others');
  assert.match(panel, /Only the workspace owner can choose voice examples\./);
  for (const { file, text } of sources()) {
    assert.doesNotMatch(text, /\b(voice|match|similarity)[- ](score|percentage|percent|rate)\b|\d+\s*%\s*(match|similar|voice)|percent(age)?\s+(match|similar)/i, `${file}: no voice or match percentages`);
  }
  for (const file of ['voice-panel.tsx', 'suggestions-panel.tsx', 'usage-panel.tsx']) assert.doesNotMatch(feature('intelligence', file), /percent|%/i, `${file}: no percentages at all`);
});

test('usage: unknown is never 0, readings carry their time, and nothing claims a cause', () => {
  assert.equal(P2.metricValue(null), 'unknown');
  assert.equal(P2.metricValue({ value: null, display: 'unknown', observedAt: null }), 'unknown');
  assert.equal(P2.metricValue({ value: Number.NaN, observedAt: null }), 'unknown');
  assert.equal(P2.metricValue({ value: 0, display: '0', observedAt: 1 }), '0', 'a real zero stays zero');
  assert.equal(P2.metricValue({ value: 1250, display: '1250', observedAt: 1 }), '1,250');
  assert.equal(P2.metricName('link_clicks'), 'Link clicks');
  assert.equal(P2.usageLabel({ source: 'citation', type: 'used_in', kind: 'source_pack', status: 'stale' }), 'Cited by a source pack (an older version)');
  assert.equal(P2.usageLabel({ source: 'post_job', type: 'post_job' }), 'Prepared in a post');
  const panel = feature('intelligence', 'usage-panel.tsx');
  assert.match(panel, /\{metricValue\(reading\)\}/);
  assert.match(panel, /as of \$\{formatDateTime\(reading\.observedAt\)\}/, 'each reading shows its source time');
  assert.match(panel, /\{usage\.note\}/, 'the server’s correlation-not-causation note is shown');
  assert.doesNotMatch(panel, /\?\? 0|\|\| 0/, 'no missing value becomes 0');
  for (const file of ['usage-panel.tsx', 'suggestions-panel.tsx']) assert.doesNotMatch(feature('intelligence', file), P2.CAUSAL_WORDING, `${file}: no causal or ranking claims`);
  assert.doesNotMatch(fs.readFileSync(path.join(LIB, 'proactive.ts'), 'utf8').replace(/export const CAUSAL_WORDING[^\n]*\n/, ''), P2.CAUSAL_WORDING);
});


/* --- T08: task source packs in the Library (A049–A051) ---------------------------------------------------------- */

const SP = load(path.join(LIB, 'source-pack.ts'));
const S = load(path.join(LIB, 'openui-schemas.ts'));
const SHA = 'c'.repeat(64);
const SREF = (character, version = character) => ({ assetId: HEX(character), versionId: HEX(version), sha256: SHA });

/** A pack as `source_packs._build` returns it. */
function serverPack(overrides = {}) {
  return {
    contractVersion: 'rafii-library/1',
    packId: HEX('9'),
    revision: 1,
    status: 'draft',
    taskContext: { userGoal: 'Announce my Brahms recital', scope: { kind: 'workspace' }, purpose: 'draft_evidence', channels: ['Instagram'], selectedSourceRefs: [] },
    returnTo: { query: 'brahms', scope: { kind: 'workspace' }, selection: [HEX('a')] },
    evidenceRefs: [
      { purpose: 'evidence', selection: 'user', assetRef: SREF('a'), title: 'Programme', kind: 'document', locatorLabel: 'Page 2', segmentId: HEX('5'), locator: { kind: 'page', page: 2 }, review: 'approved', reviewReason: null, rights: 'approved_public', current: true, why: ['You selected this.', 'Facts approved for drafts.'] },
      { purpose: 'evidence', selection: 'recommended', assetRef: SREF('b'), title: 'Hall booking', kind: 'document', locatorLabel: 'whole item', review: 'needs_review', reviewReason: 'facts_unreviewed', rights: 'unknown', current: false, why: ['Matches: recital'] }
    ],
    styleRefs: [
      { purpose: 'style', polarity: 'positive', sampleId: 'sample-1', voiceSourceId: 'vs-1', assetRef: SREF('d'), locator: { kind: 'text', start: 0, end: 120 }, locatorLabel: 'characters 0–120', language: 'en' },
      { purpose: 'style', polarity: 'negative', sampleId: 'sample-2', voiceSourceId: 'vs-2', assetRef: SREF('d'), locator: { kind: 'text', start: 200, end: 260 }, locatorLabel: 'characters 200–260', language: 'en' }
    ],
    rationale: [{ code: 'scope', message: 'Looked only in your whole Library.' }],
    gaps: [
      { code: 'missing_fact_venue', message: 'No approved fact gives the recital venue.' },
      { code: 'missing_public_image', message: 'No image approved for public use for Instagram.' }
    ],
    rightsWarnings: [
      { code: 'rights_unknown', assetRef: SREF('b'), message: 'Rights for “Hall booking” are unknown. Confirm you may use it before publishing.' },
      { code: 'older_version', assetRef: SREF('b'), message: '“Hall booking” cites an older version. Review the newer version before relying on it.' },
      { code: 'excluded_by_policy', assetRef: SREF('e'), message: '“Old flyer” can’t be used: its source was withdrawn or its use policy doesn’t allow it.' }
    ],
    grantRevision: 4,
    draftId: null,
    style: { personaId: 'workspace', language: 'en' },
    limits: { maxEvidence: 20, maxRecommended: 8 },
    warnings: [],
    ...overrides
  };
}

test('test_pack_evidence_style_separate: two lists in the review, two fields in the request, nothing crosses over', () => {
  const pack = serverPack();
  const props = SP.packReviewProps(pack, (id) => (id === HEX('d') ? 'My spring newsletter' : null));
  assert.equal(S.parseLibraryProps('SourcePackReview', props).ok, true, 'the deterministic props pass the same strict schema as generated ones');
  assert.deepEqual(props.evidence.map((entry) => entry.title), ['Programme', 'Hall booking']);
  assert.deepEqual(props.style.map((entry) => [entry.title, entry.rationale]), [['My spring newsletter', 'Write like this'], ['My spring newsletter', 'Don’t write like this']]);
  assert.ok(props.style.every((entry) => !('rights' in entry)), 'style samples carry no evidence fields');
  assert.equal(props.evidence[0].locatorLabel, 'Page 2', 'each ref shows where it points');
  assert.deepEqual(props.evidence[0].sourceRef, { assetRef: SREF('a'), segmentId: HEX('5'), locator: { kind: 'page', page: 2 } });
  assert.equal(props.evidence[0].rationale, 'You selected this. · Facts approved for drafts.');
  assert.equal(props.evidence[1].warnings.length, 2, 'rights and currency notes sit on their own ref');
  assert.deepEqual(props.rightsWarnings, ['“Old flyer” can’t be used: its source was withdrawn or its use policy doesn’t allow it.'], 'notes about items not in the lists stay pack-level');

  // Leave out the recommendation and the negative example: only what is kept is sent, evidence and style apart.
  const kept = new Set(SP.allEntryKeys(pack));
  kept.delete(SP.packEntryKey(pack.evidenceRefs[1]));
  kept.delete(SP.packEntryKey(pack.styleRefs[1]));
  const envelope = SP.createPackEnvelope(pack, kept, pack.returnTo);
  assert.equal(envelope.actionType, 'source_pack.create');
  assert.deepEqual(envelope.payload.evidence, [{ assetRef: SREF('a'), segmentId: HEX('5'), locator: { kind: 'page', page: 2 } }]);
  assert.deepEqual(envelope.payload.styleSampleIds, ['sample-1']);
  assert.deepEqual(envelope.targetRefs, [SREF('a')], 'every chosen evidence ref is a target; style refs are not evidence');
  assert.deepEqual(Object.keys(envelope.payload).toSorted(), ['evidence', 'returnTo', 'styleSampleIds', 'taskContext'], 'exactly the create_action payload keys');
  assert.deepEqual(envelope.payload.taskContext.selectedSourceRefs, []);
  assert.equal(S.isSafePayload(envelope.payload), true);
  // Two passages of one item are two entries; two samples of one span are two entries.
  assert.notEqual(SP.packEntryKey(pack.styleRefs[0]), SP.packEntryKey(pack.styleRefs[1]));

  const components = feature('intelligence', 'openui', 'components.tsx');
  assert.match(components, /<section aria-label='Evidence'/);
  assert.match(components, /<section aria-label='Style samples'/);
  assert.match(components, /style samples are not evidence/);
  assert.match(components, /reviewEntryKey\('evidence', entry\.sourceRef\)/);
  assert.match(components, /reviewEntryKey\('style', entry\.sourceRef, entry\.sampleId\)/);
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /<SourcePackReview\s+\{\.\.\.\(packReviewProps\(recommended, titleOf\)/, 'the review is the SourcePackReview component, deterministic');
  assert.match(flow, /pickable: true/);
  assert.match(flow, /createPackEnvelope\(recommended, kept, buildReturnTo\(request\.state\)\)/, 'create sends exactly the kept entries');
});

test('test_no_cleared_rights_wording: rights read as approved, not approved, internal or unknown — never cleared', () => {
  for (const code of ['approved_public', 'needs_review', 'internal', 'unknown', 'cleared', '', null, 'something_new']) {
    assert.doesNotMatch(SP.rightsLabel(code), SP.CLEARED_WORDING, String(code));
  }
  assert.equal(SP.rightsLabel('cleared'), 'Rights unknown', 'an unknown code can never claim more');
  assert.equal(SP.rightsLabel('approved_public'), 'Public use approved in Ideas');
  const props = SP.packReviewProps(serverPack());
  const bad = (patch) => S.parseLibraryProps('SourcePackReview', { ...props, ...patch }).ok;
  assert.equal(bad({ rightsWarnings: ['Rights cleared for all uses'] }), false, 'the schema refuses “cleared”');
  assert.equal(bad({ evidence: [{ ...props.evidence[0], rights: 'cleared' }] }), false);
  assert.equal(bad({ gaps: ['All clear'] }), false);
  const literals = (text) => (text.match(/'[^'\n]*'|>[^<{}\n]+</g) || []).join('\n');
  for (const file of [['intelligence', 'openui', 'components.tsx'], ['intelligence', 'source-pack-flow.tsx']]) assert.doesNotMatch(literals(feature(...file)), SP.CLEARED_WORDING, file.join('/'));
  assert.doesNotMatch(literals(fs.readFileSync(path.join(LIB, 'source-pack.ts'), 'utf8')), SP.CLEARED_WORDING);
  assert.match(feature('intelligence', 'openui', 'components.tsx'), /Rights: \{rightsLabel\(entry\.rights\)\}/, 'rights are shown through the fixed words');
});

test('test_gaps_rendered: named gaps say what is missing, in review and after saving', () => {
  const pack = serverPack();
  assert.deepEqual(SP.gapMessages(pack), ['No approved fact gives the recital venue.', 'No image approved for public use for Instagram.']);
  assert.deepEqual(SP.packReviewProps(pack).gaps, SP.gapMessages(pack));
  const components = feature('intelligence', 'openui', 'components.tsx');
  assert.match(components, /<section aria-label='Missing'[\s\S]*?\{gaps\.map\(\(gap\) => \(\s*<li key=\{gap\}>\{gap\}<\/li>/);
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /Still missing/);
  assert.match(flow, /saved\.gaps\.map\(\(gap\) =>/);
});

test('test_attach_expected_revision_conflict_no_auto_retry: attach names the pack revision; a conflict is shown, never re-sent', () => {
  const pack = serverPack({ revision: 3 });
  const envelope = SP.attachEnvelope(pack, HEX('f'));
  assert.deepEqual([envelope.actionType, envelope.expectedRevision, envelope.targetRefs, envelope.payload], ['source_pack.attach', 3, [], { packId: HEX('9'), draftId: HEX('f') }]);
  assert.notEqual(SP.envelopeDigest(envelope), SP.envelopeDigest(SP.attachEnvelope({ ...pack, revision: 4 }, HEX('f'))), 'a new revision is a new request (new key)');

  const conflict = SP.readAttachResult(
    {
      status: 'conflict',
      warnings: ['Permissions or sources changed since this pack was made. Review the changes.'],
      result: {
        status: 'conflict',
        changes: [
          { purpose: 'evidence', assetRef: SREF('a'), change: 'permission_narrowed', after: { allowed: false, reason: 'egress_consent_required', message: 'Cloud processing needs your consent.' } },
          { purpose: 'style', assetRef: SREF('d'), change: 'voice_example_withdrawn' },
          { purpose: 'evidence', assetRef: SREF('x'), change: 'unavailable' }
        ]
      }
    },
    (versionId) => (versionId === HEX('a') ? 'Programme' : null)
  );
  assert.equal(conflict.kind, 'conflict');
  assert.deepEqual(conflict.changes, [
    'Source “Programme”: its permission was narrowed. Cloud processing needs your consent.',
    'Voice example: the voice example was withdrawn.',
    'Source: it is no longer available.'
  ]);
  const revoked = SP.readAttachResult({ status: 'conflict', result: { changes: [{ purpose: 'pack', assetRef: {}, change: 'pack_revoked', message: 'A permission this pack relied on was withdrawn.' }] } });
  assert.deepEqual(revoked.changes, ['A permission this pack relied on was withdrawn.']);
  const applied = SP.readAttachResult({ status: 'applied', warnings: [], result: { composer: { draftId: HEX('f'), sourcePackId: HEX('9'), sourceIds: ['src-1'], voiceMode: 'neutral', voiceSourceIds: [] }, alreadyAttached: false, warnings: ['Some voice examples aren’t selected.'] } });
  assert.equal(applied.kind, 'applied');
  assert.deepEqual(applied.warnings, ['Some voice examples aren’t selected.']);

  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /const envelope = attachEnvelope\(saved, draft\.id\);/);
  assert.match(flow, /if \(!attachKey\.current \|\| attachKey\.current\.digest !== digest\)/, 'the same attach keeps its key');
  assert.equal((flow.match(/void attach\(\)/g) || []).length, 1, 'attach is only ever sent from its button');
  assert.match(flow, /onClick=\{\(\) => void attach\(\)\}/);
  assert.match(flow, /conflict \? \(\s*<Button[^>]*onClick=\{refreshPack\}>[\s\S]*?Refresh pack/, 'a conflict offers Refresh pack instead of Attach');
  const refresh = flow.slice(flow.indexOf('function refreshPack()'), flow.indexOf('async function savePack()'));
  assert.doesNotMatch(refresh, /attach\(/, 'refreshing never attaches by itself');
  assert.match(flow, /Nothing was attached\. Refresh the pack/);
});

test('test_return_to_no_url_or_secret: the Library state a draft carries is stable keys only', () => {
  const state = {
    ...U.DEFAULT_LIBRARY_STATE,
    q: 'see https://cdn.example/a.jpg?X-Amz-Signature=abc&token=xyz',
    scope: 'selection',
    kind: 'document',
    tag: 'https://evil.example',
    sel: ['2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f', HEX('a'), '../etc/passwd', 'legacy-1'],
    asset: HEX('a')
  };
  const back = SP.buildReturnTo(state);
  const text = JSON.stringify(back);
  assert.doesNotMatch(text, /:\/\/|token=|signature|bearer|workspace[I_]?d|actor/i);
  assert.equal(back.query, undefined, 'a query that looks like a link is left out, not sent');
  assert.equal(back.filters.tags, undefined);
  assert.deepEqual(back.filters.kinds, ['document']);
  assert.deepEqual(back.selection, ['2f0c6c1e5a1b4c6a9d0e3b2a1c0d9e8f', HEX('a')], 'only 32-hex keys');  // pragma: allowlist secret -- synthetic asset key
  assert.equal(back.scope.kind, 'selection');
  assert.equal(back.anchor, HEX('a'));
  for (const key of Object.keys(back)) assert.ok(['query', 'scope', 'filters', 'sort', 'density', 'selection', 'anchor', 'view'].includes(key), key);
  assert.equal(SP.buildReturnTo({ ...U.DEFAULT_LIBRARY_STATE, q: 'select pieces from brahms' }).query, undefined, 'text the server refuses as code is not sent');
  const many = SP.buildReturnTo({ ...U.DEFAULT_LIBRARY_STATE, scope: 'selection', sel: Array.from({ length: 200 }, (_, index) => index.toString(16).padStart(32, '0')) });
  assert.ok(SP.serverLength(many) <= 4000, 'bounded like the server, which measures with spaces after separators');
  assert.ok(many.selection.length > 0 && many.scope.assetRefs.length === many.selection.length, 'the selection gives way, consistently');
  // The address keeps the pack id only as a stable id, and scroll is kept without it.
  assert.equal(U.parseLibraryState({ pack: 'https://x/y' }).pack, '');
  assert.equal(U.parseLibraryState({ pack: HEX('9') }).pack, HEX('9'));
  assert.ok(!U.scrollKey('ws', { pack: HEX('9') }).includes('pack='), 'scroll is kept per view, not per pack');
  assert.equal(SP.taskProblem({ goal: 'Post about https://example.com', selected: [] }) !== null, true, 'a goal with a link is refused before sending');
  assert.equal(SP.taskProblem({ goal: 'Announce the recital', selected: [] }), null);
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /buildReturnTo\(request\.state\)/, 'returnTo is built from the Library state only');
});

test('test_round_trip_restores_selection: back from the draft, the same view and selection, minus what became inaccessible', () => {
  const dashed = '2f0c6c1e-5a1b-4c6a-9d0e-3b2a1c0d9e8f';
  const state = { ...U.DEFAULT_LIBRARY_STATE, q: 'Brahms rehearsal', scope: 'selection', kind: 'audio', tag: 'spring', use: 'unused', sort: 'largest', mode: 'list', density: 'compact', sel: [dashed, HEX('a'), HEX('b')], asset: HEX('a') };
  const back = SP.buildReturnTo(state);
  // The server drops what the person can no longer reach and says how many, never which.
  const served = { ...back, selection: back.selection.filter((key) => key !== HEX('b')) };
  const current = { ...state, sel: [dashed, HEX('a'), HEX('b')] };
  const patch = SP.restoreLibraryState(served, current);
  assert.deepEqual(patch.sel, [dashed, HEX('a')], 'kept ids keep their own spelling; the inaccessible one is gone');
  assert.equal(patch.scope, 'selection');
  assert.deepEqual([patch.q, patch.kind, patch.tag, patch.use, patch.sort, patch.mode, patch.density, patch.asset], ['Brahms rehearsal', 'audio', 'spring', 'unused', 'largest', 'list', 'compact', HEX('a')]);
  const restored = U.parseLibraryState(new URLSearchParams(U.serializeLibraryState({ ...current, ...patch })));
  assert.deepEqual(restored.sel, [dashed, HEX('a')]);
  assert.equal(SP.removedNotice(1), 'One selected item is no longer available, so it was removed from your selection.');
  assert.equal(SP.removedNotice(0), null);
  assert.doesNotMatch(SP.removedNotice(2), /[0-9a-f]{32}/, 'never names the item');
  assert.deepEqual(SP.restoreLibraryState(null, current), {});
  assert.equal(SP.restoreLibraryState({ query: 'javascript:alert(1)' }, current).q, undefined);

  const view = feature('library-view.tsx');
  assert.match(view, /api\s*\.librarySourcePack\(workspaceId, packId\)/);
  assert.match(view, /const patch = restoreLibraryState\(pack\.returnTo, latestUrl\.current\);/);
  assert.match(view, /update\(\{ \.\.\.patch, pack: '' \}\);/);
  assert.match(view, /const notice = removedNotice\(pack\.returnToRemoved\);/);
  assert.match(view, /return commit\(\{ pack: packId \}\);/, 'leaving for the composer records the pack in the address first');
  assert.match(view, /state: \{ \.\.\.url, q: query \}/, 'the pack keeps the Library state of the moment it was asked for');
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /await onLeave\(saved\.packId\);\s*router\.push\(`\/app\/agent\/\$\{encodeURIComponent\(run\.conversationId\)\}`\);/);
  assert.match(flow, /\.\.\.composerTurn\(composer, target, saved\.taskContext\.userGoal\)/, 'the writer gets the composer fields');
  const turn = SP.composerTurn({ draftId: HEX('f'), sourceIds: ['src-1', 'src-2'], voiceMode: 'personalized', voiceSourceIds: ['vs-1'] }, { id: HEX('f'), platform: 'Instagram', language: 'English', channelId: 'acct-1' }, 'Announce the recital');
  assert.deepEqual(turn.sourceIds, ['src-1', 'src-2']);
  assert.deepEqual(turn.references, [{ kind: 'post', id: HEX('f'), role: 'rework' }], 'the draft the pack is attached to is the one reworked');
  assert.deepEqual([turn.voiceMode, turn.voiceSourceIds], ['personalized', ['vs-1']]);
  assert.deepEqual(turn.destinations, [{ platform: 'Instagram', channelId: 'acct-1', language: 'English' }]);
  assert.equal(SP.composerTurn({ draftId: HEX('f'), sourceIds: [], voiceMode: 'personalized', voiceSourceIds: [] }, { id: HEX('f'), platform: 'LinkedIn', language: 'English' }, 'x').voiceMode, 'neutral', 'no usable sample, no personalized voice');
});

test('status flags: entry points that are off are hidden or explained; the deterministic Library still works', () => {
  const off = SP.libraryGates({ retrieval: false, voice: false, artifacts: false, task_ui: false }, true);
  assert.equal(off.packs.enabled, true, 'a pack still works from chosen items');
  for (const name of ['ask', 'recommendations', 'voice', 'artifacts', 'taskUi']) {
    assert.equal(off[name].enabled, false, name);
    assert.match(off[name].reason, /\w/, `${name}: a plain explanation`);
  }
  const on = SP.libraryGates({ retrieval: true, voice: true, artifacts: true, task_ui: true }, true);
  for (const name of ['packs', 'ask', 'recommendations', 'voice', 'artifacts', 'taskUi']) assert.deepEqual(on[name], { enabled: true, reason: null }, name);
  const unreachable = SP.libraryGates({ retrieval: true }, false);
  assert.equal(unreachable.packs.enabled, false);
  assert.equal(unreachable.ask.enabled, false);

  const view = feature('library-view.tsx');
  assert.match(view, /const gates = libraryGates\(intel\.flags, intel\.reachable\);/);
  assert.match(view, /const asking = url\.panel === 'ask' && gates\.ask\.enabled;/);
  assert.match(view, /gates\.ask\.enabled \? \(\s*<SegmentedControl/, 'Ask is offered only where its search is on');
  assert.match(view, /canEdit && gates\.packs\.enabled\s*\?/);
  assert.match(view, /voiceEnabled(?:=\{|: )gates\.voice\.enabled/);
  assert.match(feature('asset-detail.tsx'), /\{voiceEnabled \? <VoicePanel[^:]*: <p[^>]*>\{voiceNote/);
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /gates\.recommendations\.reason/);
  assert.match(flow, /gates\.voice\.reason/);
  assert.match(flow, /gates\.artifacts\.enabled \?/);
  assert.match(feature('intelligence', 'openui', 'error-boundary.tsx'), /Renderer && generated && !rendererFailed/, 'task_ui off: no generated renderer');
  assert.match(feature('asset-detail.tsx'), /Use in draft/);
});

test('batch edits: re-read before writing, user tags only, and each item’s key is sent', () => {
  const hook = feature('intelligence', 'use-batch-actions.ts');
  assert.match(hook, /export function userTagsOf\(asset: Pick<LibraryAsset, 'tags'>\) \{\s*return asset\.tags \?\? \[\];/);
  assert.doesNotMatch(hook, /aiTags/, 'AI-suggested tags are never written back as the person’s');
  assert.match(hook, /const fresh = await readFresh\(asset, listed\);/, 'each item is read again right before its write');
  assert.match(hook, /api\.libraryFile\(workspaceId, asset\.id\)/);
  assert.match(hook, /await client\.refetchQueries\(\{ queryKey: \['library-assets', workspaceId\] \}\);/);
  assert.match(hook, /const tags = userTagsOf\(fresh\);/);
  assert.match(hook, /const current = \(fresh\.collections \?\? \[\]\)/, 'membership comes from the fresh read');
  assert.match(hook, /actionType: 'metadata\.update',[\s\S]{0,120}idempotencyKey: key,/, 'the per-item key is sent');
  assert.doesNotMatch(hook, /_key\b/, 'no unused key parameter');
  assert.match(hook, /if \(!listed\) throw new Error/, 'without a fresh read nothing is written from the page’s copy');
  const bar = feature('intelligence', 'batch-bar.tsx');
  assert.match(bar, /const unresolved = Boolean\(run && !run\.running && run\.summary\.retryIds\.length > 0\);/, 'a run that didn’t finish waits for its own Retry');
  assert.match(bar, /Retry or dismiss the last change before starting another\./);
});

test('host writes: a failed press becomes Retry with the same key; an applied one is done', () => {
  const flow = feature('intelligence', 'source-pack-flow.tsx');
  assert.match(flow, /if \(!createKey\.current \|\| createKey\.current\.digest !== digest\) createKey\.current = \{ digest, key: newIdempotencyKey\('lib-pack-create', randomKey\) \};/);
  assert.match(flow, /\{lost === 'create' \? 'Retry' : 'Save source pack'\}/);
  assert.match(flow, /\{lost === 'attach' \? 'Retry' : 'Attach to draft'\}/);
  assert.match(flow, /\{lost === 'write' \? 'Retry' : 'Rework this draft with these sources'\}/);
  assert.match(flow, /write\.current \?\?= \{ conversationId: null, key: newIdempotencyKey\('lib-pack-write', randomKey\) \};/, 'the same turn and conversation on Retry');
  assert.match(flow, /const attempt = write\.current;/);
  assert.match(flow, /idempotencyKey: attempt\.key/);
  // After saving, the step moves on: the Save control is gone, and the pack is not saved twice from here.
  assert.match(flow, /setSaved\(result\.result\);\s*setStep\('saved'\);/);
  // Detail actions key by request digest, so pressing again after a lost answer is the same request.
  for (const [file, pattern] of [
    ['versions-panel.tsx', /replaceKey\.current\.plan !== digest/],
    ['audio-player.tsx', /momentKey\.current\.digest !== digest/],
    ['voice-panel.tsx', /keys\.current\[digest\] \?\?= newIdempotencyKey/],
    ['smart-collections.tsx', /saveKey\.current\.digest !== requestDigest/]
  ])
    assert.match(feature('intelligence', file), pattern, file);
});
