// node --test web/src/lib/content-library/taxonomy.test.cjs
const test = require('node:test');
const assert = require('node:assert/strict');
const crypto = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

const here = __dirname;
const web = path.resolve(here, '../../..');
const repo = path.resolve(web, '..');
const publicDir = path.join(web, 'public/rafii/library');

/* A tiny CommonJS loader for the TypeScript modules: relative imports and the `@/lib/content-library` alias. */
const cache = new Map();
function load(file) {
  const full = path.resolve(file);
  if (cache.has(full)) return cache.get(full).exports;
  const source = fs.readFileSync(full, 'utf8');
  const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2020 } });
  const mod = { exports: {} };
  cache.set(full, mod);
  const localRequire = (spec) => {
    if (spec.startsWith('.')) return load(path.resolve(path.dirname(full), spec.endsWith('.ts') ? spec : `${spec}.ts`).replace(/\.ts\.ts$/, '.ts'));
    if (spec === '@/lib/content-library') return load(path.join(here, 'index.ts'));
    if (spec.startsWith('@/lib/content-library/')) return load(path.join(here, `${spec.slice('@/lib/content-library/'.length)}.ts`));
    return require(spec);
  };
  new Function('require', 'module', 'exports', outputText)(localRequire, mod, mod.exports);
  return mod.exports;
}
function resolveDir(spec) {
  return fs.existsSync(spec) && fs.statSync(spec).isDirectory() ? path.join(spec, 'index.ts') : spec;
}
const L = load(resolveDir(path.join(here, 'index.ts')));
const markup = load(path.join(here, 'artwork-markup.ts'));
const choice = load(path.join(web, 'src/features/agent/content-choice.ts'));

const sha256 = (bytes) => 'sha256:' + crypto.createHash('sha256').update(bytes).digest('hex');
const svgIds = (markup) => [...markup.matchAll(/id="([^"]+)"/g)].map((m) => m[1]);
const quoted = (body) => [...body.matchAll(/"([a-z_]+)"/g)].map((m) => m[1]);
const editorial = L.TAXONOMY.filter((item) => item.dimension === 'editorial');
const native = L.TAXONOMY.filter((item) => item.dimension === 'native');

test('51 unique ids: 31 editorial types and 20 native formats, every one in a real category with tags and pairings', () => {
  assert.equal(L.TAXONOMY.length, 51);
  assert.equal(new Set(L.TAXONOMY.map((item) => item.id)).size, 51);
  assert.equal(editorial.length, 31);
  assert.equal(native.length, 20);
  assert.equal(L.EDITORIAL_TYPES.length, 31);
  assert.equal(L.NATIVE_FORMATS.length, 20);
  assert.equal(L.CATEGORIES.editorial.length, 7);
  assert.equal(L.CATEGORIES.native.length, 7);
  for (const item of L.TAXONOMY) {
    assert.ok(item.title && item.description && item.family, item.id);
    assert.ok(L.CATEGORIES[item.dimension].some((category) => category.id === item.category), `${item.id} category ${item.category}`);
    assert.ok(item.tags.includes(item.dimension === 'native' ? 'format' : 'editorial'), `${item.id} tags`);
    assert.ok(item.pairings.length > 0, `${item.id} has pairings`);
    for (const platform of item.platforms) assert.ok(L.platformInfo(platform), `${item.id} platform ${platform}`);
    assert.equal(item.platform_support, 'unverified');
  }
  // Every category is used, so the filter never offers an empty group.
  for (const dimension of ['editorial', 'native']) for (const category of L.CATEGORIES[dimension]) assert.ok(L.TAXONOMY.some((item) => item.dimension === dimension && item.category === category.id), category.id);
});

test('pairings and evidence resolve; every pairing joins a real editorial type to a real native format', () => {
  assert.equal(L.PAIRINGS.length, 67);
  assert.equal(new Set(L.PAIRINGS.map((pairing) => pairing.id)).size, 67);
  for (const pairing of L.PAIRINGS) {
    assert.equal(L.taxonomyItem(pairing.editorial)?.dimension, 'editorial', pairing.id);
    assert.equal(L.taxonomyItem(pairing.native)?.dimension, 'native', pairing.id);
    assert.equal(pairing.kind, 'fit_suggestion');
    assert.ok(pairing.why && pairing.surface_note, pairing.id);
    for (const platform of pairing.platforms) assert.ok(L.platformInfo(platform), `${pairing.id} ${platform}`);
    for (const ref of pairing.evidence) assert.ok(L.EVIDENCE[ref], `${pairing.id} evidence ${ref}`);
    assert.ok(L.taxonomyItem(pairing.editorial).pairings.includes(pairing.id), `${pairing.id} listed on its editorial item`);
    assert.ok(L.taxonomyItem(pairing.native).pairings.includes(pairing.id), `${pairing.id} listed on its native item`);
  }
  for (const record of Object.values(L.EVIDENCE)) {
    for (const key of ['label', 'kind', 'publisher', 'date', 'url', 'finding', 'sample', 'limit']) assert.ok(record[key], `${record.id} ${key}`);
    assert.match(record.url, /^https:\/\//);
  }
  assert.equal(L.TAXONOMY_SOURCE.reviewedAt, '2026-09-22');
  assert.equal(L.TAXONOMY_SOURCE.archiveSha256, sha256(fs.readFileSync(path.join(repo, L.TAXONOMY_SOURCE.archive))).slice(7));
});

test('every item has both assets, hashes match the embedded markup and the public copies, and no two items share artwork', () => {
  const largeHashes = new Set();
  const compactHashes = new Set();
  const provenance = fs.readFileSync(path.join(publicDir, 'PROVENANCE.md'), 'utf8');
  for (const item of L.TAXONOMY) {
    const art = L.artworkFor(item.id);
    assert.ok(art, `${item.id} artwork`);
    for (const [size, meta] of [['large', art.large], ['compact', art.compact]]) {
      for (const key of ['thumbnail_id', 'thumbnail_kind', 'thumbnail_asset_path', 'alt_text', 'aspect_ratio', 'visual_concept', 'source_type', 'content_hash', 'version']) assert.ok(meta[key], `${item.id} ${size} ${key}`);
      assert.equal(meta.thumbnail_kind, 'svg');
      assert.equal(meta.aspect_ratio, size === 'large' ? '8:5' : '1:1');
      assert.equal(meta.source_type, 'original_deterministic_svg');
      const markup = L.artworkMarkup(item.id, size);
      assert.ok(markup, `${item.id} ${size} markup`);
      assert.equal(sha256(markup), meta.content_hash, `${item.id} ${size} embedded markup hash`);
      const copy = path.join(web, 'public', meta.thumbnail_asset_path);
      assert.ok(fs.existsSync(copy), `${item.id} ${size} public copy`);
      assert.equal(sha256(fs.readFileSync(copy)), meta.content_hash, `${item.id} ${size} public copy hash`);
      assert.ok(provenance.includes(meta.content_hash.slice(7)), `${item.id} ${size} in PROVENANCE.md`);
      assert.doesNotMatch(markup, /<image|(?:href|src)=["']https?:/, `${item.id} ${size} no external media`);
      assert.match(markup, /xmlns="http:\/\/www.w3.org\/2000\/svg"/);
    }
    assert.match(L.artworkMarkup(item.id, 'compact'), /<g class="glyph-motion"/, `${item.id} glyph accent`);
    assert.match(L.artworkMarkup(item.id, 'large'), /<g style="filter:grayscale\(1\)">/, `${item.id} grayscale motif`);
    largeHashes.add(art.large.content_hash);
    compactHashes.add(art.compact.content_hash);
  }
  assert.equal(largeHashes.size, 51, 'large illustrations are distinct');
  assert.equal(compactHashes.size, 51, 'compact glyphs are distinct');
  assert.equal(sha256(fs.readFileSync(path.join(web, 'public', L.LEGACY_FALLBACK.thumbnail_asset_path))), L.LEGACY_FALLBACK.content_hash);
  assert.equal(L.artworkMarkup('no-such-item', 'large'), markup.LEGACY_FALLBACK_ARTWORK);
  assert.equal(sha256(markup.LEGACY_FALLBACK_ARTWORK), L.LEGACY_FALLBACK.content_hash);
  assert.equal(L.artworkMarkup('no-such-item', 'compact'), null);
});

test('render-time preparation namespaces ids, strips root semantics and adds motion hooks without touching the source', () => {
  const source = L.artworkMarkup('announcement', 'large');
  const a = L.prepareArtwork(source, { prefix: 'art-1', size: 'large' });
  const b = L.prepareArtwork(source, { prefix: 'art-2', size: 'large' });
  assert.equal(L.artworkMarkup('announcement', 'large'), source, 'source unchanged');
  assert.match(a, /id="art-1-paper"/);
  assert.match(a, /url\(#art-1-shadow\)/);
  assert.doesNotMatch(a, /id="paper"|url\(#paper\)|url\(#shadow\)/);
  assert.doesNotMatch(a, /<title>/);
  assert.match(a, /^<svg[^>]*aria-hidden="true" focusable="false">/);
  assert.doesNotMatch(a, /<svg[^>]*role="img"/);
  assert.match(a, new RegExp(`<g class="${L.ART_MOTIF_CLASS}" style="filter:grayscale\\(1\\)">`));
  assert.match(a, new RegExp(`<g class="${L.ART_ACCENT_CLASS}"><circle [^>]*\\/><\\/g>`));
  assert.equal(new Set([...svgIds(a), ...svgIds(b)]).size, svgIds(a).length + svgIds(b).length, 'two instances never share an id');
  const glyph = L.prepareArtwork(L.artworkMarkup('announcement', 'compact'), { prefix: ':r1:', size: 'compact' });
  assert.match(glyph, /<g class="glyph-motion">/);
  assert.doesNotMatch(glyph, /aria-label=|role="img"/);
  assert.match(glyph, /aria-hidden="true"/);
});

function pythonCatalog() {
  const file = path.join(repo, 'src/postriff_phase2/content_types.py');
  if (!fs.existsSync(file)) return null;
  const text = fs.readFileSync(file, 'utf8');
  const tuple = (name) => {
    const match = new RegExp(`^${name} = \\(([\\s\\S]*?)^\\)`, 'm').exec(text);
    assert.ok(match, `${name} in content_types.py`);
    return match[1];
  };
  const formats = [...tuple('FORMATS').matchAll(/\("([a-z_]+)", "([^"]+)"\)/g)].map((m) => ({ id: m[1], label: m[2] }));
  const core = [...tuple('CORE_TYPES').matchAll(/_type\("(postriff:[a-z_]+)", "([^"]+)", "([^"]+)", \(([^)]*)\)/g)].map((m) => ({ id: m[1], label: m[2], description: m[3], recommendedFormatIds: quoted(m[4]) }));
  const creator = [...tuple('CREATOR_ROWS').matchAll(/\("([a-z_]+)", "([^"]+)", "([^"]+)", \(([^)]*)\)/g)].map((m) => ({ id: `pack.creator:${m[1]}`, label: m[2], description: m[3], recommendedFormatIds: quoted(m[4]) }));
  const pack = /CREATOR_PACK_ID = "([^"]+)"[\s\S]*?CREATOR_PACK_VERSION = "([^"]+)"/.exec(text);
  return { formats, types: [...core, ...creator], pack: { packId: pack[1], version: pack[2] } };
}

test('the backend mirrors match src/postriff_phase2/content_types.py', { skip: pythonCatalog() === null && 'backend source not present' }, () => {
  const python = pythonCatalog();
  assert.deepEqual(L.BACKEND_FORMATS, python.formats);
  assert.deepEqual(L.BACKEND_CONTENT_TYPES, python.types);
  assert.deepEqual({ ...L.CREATOR_PACK }, python.pack);
});

test('every editorial type maps onto a known backend type; every native format maps onto a known format or is planning-only with a note', () => {
  const types = new Set(L.BACKEND_CONTENT_TYPE_IDS);
  const formats = new Set(L.BACKEND_FORMAT_IDS);
  assert.equal(types.size, 16);
  assert.equal(formats.size, 10);
  for (const item of editorial) {
    const mapping = L.executionFor(item.id);
    assert.ok(mapping, `${item.id} registered`);
    assert.equal(mapping.execution, 'mapped', item.id);
    assert.ok(types.has(mapping.contentTypeId), `${item.id} → ${mapping.contentTypeId}`);
    assert.equal(mapping.formatId, undefined, item.id);
    assert.ok(mapping.note.length > 20, `${item.id} note`);
  }
  let planning = 0;
  for (const item of native) {
    const mapping = L.executionFor(item.id);
    assert.ok(mapping, `${item.id} registered`);
    assert.equal(mapping.contentTypeId, undefined, item.id);
    assert.ok(mapping.note.length > 10, `${item.id} note`);
    if (mapping.execution === 'planning-only') {
      planning += 1;
      assert.equal(mapping.formatId, undefined, item.id);
    } else {
      assert.equal(mapping.execution, 'mapped');
      assert.ok(formats.has(mapping.formatId), `${item.id} → ${mapping.formatId}`);
    }
  }
  assert.deepEqual(
    native.filter((item) => L.isPlanningOnly(item.id)).map((item) => item.id),
    ['thread', 'livestream', 'quiz', 'audio', 'product_catalog']
  );
  assert.equal(planning, 5);
  assert.equal(Object.keys(L.EXECUTION).length, 51, 'no orphan registry entries');
  for (const type of L.BACKEND_CONTENT_TYPES) for (const id of type.recommendedFormatIds) assert.ok(formats.has(id), `${type.id} recommends ${id}`);
  assert.equal(L.executionFor('legacy-fallback'), undefined);
});

test('filters, search, categories, app fit and pairing routes are pure and never touch the staged choice', () => {
  const all = L.filterItems('editorial', L.EMPTY_FILTERS);
  assert.equal(all.length, 31);
  assert.deepEqual(L.categoryOptions('editorial')[0], { value: 'all', label: 'All editorial types', count: 31 });
  assert.equal(L.categoryOptions('native').reduce((sum, option) => (option.value === 'all' ? sum : sum + option.count), 0), 20);
  assert.deepEqual(L.filterItems('editorial', { ...L.EMPTY_FILTERS, category: 'news' }).map((item) => item.id), ['announcement', 'news_curation', 'event_live']);
  assert.ok(L.filterItems('native', { ...L.EMPTY_FILTERS, query: 'PDF' }).some((item) => item.id === 'document'));
  assert.ok(L.filterItems('editorial', { ...L.EMPTY_FILTERS, query: 'teach & explain' }).length > 0, 'category label is searchable');
  assert.deepEqual(L.filterItems('editorial', { ...L.EMPTY_FILTERS, query: 'zzz-nothing' }), []);
  assert.ok(L.filterItems('native', { ...L.EMPTY_FILTERS, platform: 'red' }).every((item) => item.platforms.includes('red')));
  assert.ok(!L.filterItems('native', { ...L.EMPTY_FILTERS, platform: 'red' }).some((item) => item.id === 'audio'), 'specialist surfaces have no app fit');
  assert.deepEqual(L.activeFilters('native', { query: 'x', category: 'video', platform: 'linkedin' }), { count: 2, summary: 'Video & live · LinkedIn' });
  assert.deepEqual(L.activeFilters('native', { ...L.EMPTY_FILTERS, query: 'x' }), { count: 0, summary: '' });
  assert.equal(L.platformFitId('LinkedIn'), 'linkedin');
  assert.equal(L.platformFitId('Xiaohongshu'), 'red');
  assert.equal(L.platformFitId('小紅書'), 'red');
  assert.equal(L.platformFitId('twitter'), 'x');
  assert.equal(L.platformFitId('YouTube'), null);
  assert.deepEqual(
    L.platformOptions(['LinkedIn', 'Instagram', 'Threads', 'Xiaohongshu', 'YouTube']).map((option) => option.value),
    ['all', 'instagram', 'linkedin', 'threads', 'red']
  );
  assert.equal(L.platformOptions().length, 7);
  assert.equal(L.PLATFORM_SLUGS.red, 'xiaohongshu');
  const routes = L.pairingsFor(L.taxonomyItem('status_update'));
  assert.equal(routes.length, 2);
  assert.equal(routes[0].editorial, 'status_update');
  assert.ok(L.pairingsFor(L.taxonomyItem('status_update'), 'red').every((pairing) => pairing.platforms.includes('red')));
  assert.deepEqual(['thread', 'carousel', 'document', 'livestream', 'long_video', 'text', 'audio'].map(L.intentFor), ['thread', 'carousel', 'carousel', 'video', 'video', 'post', 'post']);
});

test('content choice translates a library value into the backend selection and keeps planning-only honest', () => {
  const mapped = choice.contentChoice({ editorialId: 'how_to', nativeId: 'carousel' });
  assert.equal(mapped.contentTypeId, 'pack.creator:tutorial_how_to');
  assert.equal(mapped.formatId, 'carousel');
  assert.equal(mapped.planningOnly, null);
  assert.deepEqual(mapped.payload, { contentTypeId: 'pack.creator:tutorial_how_to', formatId: 'carousel' });
  assert.equal(mapped.intent, 'carousel');
  assert.equal(mapped.summary, 'How-to · Carousel');
  assert.equal(mapped.needsCreatorPack, true);

  const core = choice.contentChoice({ editorialId: 'status_update', nativeId: 'text' });
  assert.equal(core.contentTypeId, 'postriff:update');
  assert.equal(core.needsCreatorPack, false);
  assert.equal(core.formatLabel, 'Short text');

  const planning = choice.contentChoice({ editorialId: 'event_live', nativeId: 'livestream' });
  assert.equal(planning.contentTypeId, 'pack.creator:event_service_institutional_update');
  assert.equal(planning.formatId, 'image_caption', 'the type’s default format is recorded explicitly');
  assert.equal(planning.planningOnly.title, 'Livestream');
  assert.equal(planning.planningOnly.label, 'Planning only · export or manual posting');
  assert.match(planning.planningOnly.note, /live broadcast/);
  assert.equal(planning.planningOnly.recordedFormatLabel, 'Image + caption');
  assert.equal(planning.intent, 'video');

  assert.equal(choice.contentChoice({ editorialId: 'text', nativeId: 'status_update' }), null, 'dimensions are not interchangeable');
  assert.equal(choice.contentChoice({ editorialId: 'nope', nativeId: 'text' }), null);
});

test('selectLibraryContent installs the creator pack once, then selects; core types skip the install', async () => {
  const calls = [];
  const api = {
    act: async (workspaceId, revision, action, payload) => {
      calls.push([workspaceId, revision, action, payload]);
      return { revision: revision + 1 };
    }
  };
  const first = await choice.selectLibraryContent(api, 'ws', 5, [], { editorialId: 'how_to', nativeId: 'document' });
  assert.deepEqual(calls, [
    ['ws', 5, 'p2_content_install_pack', { packId: 'pack.creator', version: '1.0.0' }],
    ['ws', 6, 'p2_content_select', { contentTypeId: 'pack.creator:tutorial_how_to', formatId: 'carousel' }]
  ]);
  assert.equal(first.revision, 7);
  assert.equal(first.choice.planningOnly, null);
  calls.length = 0;
  await choice.selectLibraryContent(api, 'ws', 7, [{ id: 'pack.creator' }], { editorialId: 'how_to', nativeId: 'quiz' });
  assert.deepEqual(calls, [['ws', 7, 'p2_content_select', { contentTypeId: 'pack.creator:tutorial_how_to', formatId: 'carousel' }]]);
  calls.length = 0;
  await choice.selectLibraryContent(api, 'ws', 8, undefined, { editorialId: 'status_update', nativeId: 'text' });
  assert.deepEqual(calls, [['ws', 8, 'p2_content_select', { contentTypeId: 'postriff:update', formatId: 'short_text' }]]);
  await assert.rejects(choice.selectLibraryContent(api, 'ws', 9, [], { editorialId: 'x', nativeId: 'y' }), /Content Library/);
});
