/**
 * Chips UI (chat-context SPEC §4.4–§4.6, §13; PLAN S26): the chip's visible word, why a reference can't be read, and
 * the structural rules the components must keep (44 px targets, named remove segment, no red tints, non-modal
 * inputs outside popups, SPEC §13 strings).
 *
 *   node --test web/tests/attachments-ui.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const WEB = path.join(__dirname, '..');
const SRC = path.join(WEB, 'src');
const DIR = path.join(SRC, 'features', 'agent', 'attachments');
const read = (file) => fs.readFileSync(path.join(DIR, file), 'utf8');

/** Load exported pure functions from a component file, every import stubbed (the functions under test use none). */
function pure(file, names) {
  const source = read(file);
  const { outputText } = ts.transpileModule(source, {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(() => new Proxy({}, { get: () => () => null }), mod, mod.exports);
  return Object.fromEntries(names.map((name) => [name, mod.exports[name]]));
}

const { chipWord } = pure('reference-chip.tsx', ['chipWord']);
const { readBlocker } = pure('media-options.tsx', ['readBlocker']);

test('the chip says its role or state in SPEC §13 words', () => {
  const photo = { key: 'k', kind: 'image', id: 'a', label: 'Photo A' };
  assert.equal(chipWord({ ...photo, upload: { status: 'preparing' } }), 'Uploading');
  assert.equal(chipWord({ ...photo, upload: { status: 'uploading', progress: 40 } }), 'Uploading 40%');
  assert.equal(chipWord({ ...photo, upload: { status: 'checking' } }), 'Uploading');
  assert.equal(chipWord({ ...photo, upload: { status: 'failed', message: 'x' } }), 'Failed');
  assert.equal(chipWord({ ...photo, role: 'post' }), 'In post');
  assert.equal(chipWord({ ...photo, role: 'reference' }), 'Reference');
  assert.equal(chipWord({ ...photo, role: 'reference', read: { status: 'reading' } }), 'Reading');
  assert.equal(chipWord({ ...photo, role: 'reference', read: { status: 'read', note: 'n' } }), 'Read');
  assert.equal(chipWord({ ...photo, role: 'reference', read: { status: 'failed' } }), 'Failed');
  assert.equal(chipWord({ key: 'p', kind: 'post', id: 'p', label: 'Post', role: 'rework' }), 'Rework');
  assert.equal(chipWord({ key: 'p', kind: 'post', id: 'p', label: 'Post', role: 'inspire' }), 'For ideas');
  assert.equal(chipWord({ key: 's', kind: 'source', id: 's', label: 'Notes' }, { needsOk: true }), 'Needs your OK');
});

test('reading is blocked with the SPEC §13 line for each reason, and owners get the allow path', () => {
  const catalog = { notes: { available: true } };
  assert.deepEqual(readBlocker({ catalog: { notes: { available: false } }, fixtureWriter: false, consent: { cloud: true, reconfirm: false }, isOwner: true }), {
    message: "Photo reading isn't available here.",
    allow: false
  });
  assert.equal(readBlocker({ catalog, fixtureWriter: true, consent: { cloud: true, reconfirm: false }, isOwner: true }).message,
    "The free preview writer doesn't use photo notes. Choose another writer to use them.");
  assert.deepEqual(readBlocker({ catalog, fixtureWriter: false, consent: { cloud: false, reconfirm: false }, isOwner: true }), {
    message: 'Allow Rafii to look at photos and videos first.',
    allow: true
  });
  assert.deepEqual(readBlocker({ catalog, fixtureWriter: false, consent: { cloud: false, reconfirm: false }, isOwner: false }), {
    message: 'Ask the workspace owner to allow photo reading on the Memory page.',
    allow: false
  });
  assert.equal(readBlocker({ catalog, fixtureWriter: false, consent: { cloud: true, reconfirm: true }, isOwner: false }).message,
    'The workspace owner needs to allow the new photo reader.');
  assert.equal(readBlocker({ catalog, fixtureWriter: false, consent: { cloud: true, reconfirm: false }, isOwner: false }), null);
});

test('chip, bar and sheets keep the SPEC §4.4/§11.6 structure', () => {
  const chip = read('reference-chip.tsx');
  assert.match(chip, /h-11/, 'the chip is 44 px tall');
  assert.match(chip, /aria-label=\{`Remove \$\{chip\.label\}`\}/, 'the remove segment is named "Remove {label}"');
  assert.match(chip, /w-11 shrink-0[^']*border-l/, 'a full-height 44 px remove segment behind a hairline');
  const bar = read('attachment-bar.tsx');
  assert.match(bar, /aria-label='Add to message'/);
  assert.match(bar, /size-11/);
  assert.match(bar, /aria-live='polite'/);
  assert.equal((bar.match(/aria-live=/g) ?? []).length, 1, 'one live region per composer');
  assert.match(bar, /scroll-fade-x/);
  assert.match(bar, /toast\('Removed',\s*\{\s*duration: UNDO_MS,\s*action: \{\s*label: 'Undo'/);
  // The hidden inputs live in the bar, not inside a popup, and are clicked inside the tap.
  assert.match(bar, /type='file'/);
  assert.match(bar, /onPickDevice=\{\(\) => deviceInput\.current\?\.click\(\)\}/);
  const sheet = read('plus-sheet.tsx');
  for (const text of ['Photo or video', 'From this device', 'From Library', 'Photos and videos you uploaded', 'Rework a draft or use it for ideas', 'Write this message with a template', 'Facts Rafii may use', 'Where this draft goes', '.txt or .md, up to 20 KB', 'Add to this message', 'Search posts', 'Search templates', 'Search sources', 'Search accounts and folders', 'Videos cost more to read than photos.'])
    assert.ok(sheet.includes(text), `plus sheet: ${text}`);
  assert.match(sheet, /useCloseWatcher/);
  assert.match(sheet, /useVisualViewport/);
  assert.match(sheet, /aria-label='Back'/);
  const text = read('text-file-sheet.tsx');
  assert.match(text, /useState\(false\);\s*const \[cloud, setCloud\] = useState\(false\)/, 'both controls start unticked');
  for (const file of ['reference-chip.tsx', 'attachment-bar.tsx', 'media-options.tsx', 'plus-sheet.tsx', 'library-grid.tsx', 'text-file-sheet.tsx'])
    assert.doesNotMatch(read(file), /(text|bg|border|ring)-(red|rose|destructive)/, `${file}: no red tints (DNA §4.3)`);
});
