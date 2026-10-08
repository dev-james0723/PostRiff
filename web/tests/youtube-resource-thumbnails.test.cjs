const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(name, bindings = {}) {
  const file = path.resolve(__dirname, '../src/features/youtube', name);
  const { outputText, diagnostics } = ts.transpileModule(fs.readFileSync(file, 'utf8'), {
    fileName: file,
    reportDiagnostics: true,
    compilerOptions: {
      module: ts.ModuleKind.CommonJS,
      target: ts.ScriptTarget.ES2022,
      jsx: ts.JsxEmit.ReactJSX
    }
  });
  assert.deepEqual(diagnostics?.filter((diagnostic) => diagnostic.category === ts.DiagnosticCategory.Error) || [], []);
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)((id) => {
    if (Object.hasOwn(bindings, id)) return bindings[id];
    throw new Error(`Unexpected resource component dependency: ${id}`);
  }, mod, mod.exports);
  return mod.exports;
}

const thumbnails = load('resource-thumbnails.ts');
const { youtubeThumbnailUrls } = thumbnails;

/** Execute the actual TSX and its image error callbacks, with isolated keyed useState cells. */
function mountList(initialProps) {
  const states = new Map();
  let activeHooks;
  const jsx = (type, props, key) => ({ type, props: props || {}, key });
  const { YouTubeResourceList } = load('resource-list.tsx', {
    react: {
      useState(initial) {
        assert.ok(activeHooks, 'Hooks must execute inside a mounted component.');
        const cells = activeHooks.cells;
        const index = activeHooks.cursor++;
        if (!(index in cells)) cells[index] = typeof initial === 'function' ? initial() : initial;
        return [cells[index], (next) => {
          cells[index] = typeof next === 'function' ? next(cells[index]) : next;
        }];
      }
    },
    'react/jsx-runtime': { jsx, jsxs: jsx },
    '@/components/icons': { Icons: { video: 'icon-video', folder: 'icon-folder', check: 'icon-check' } },
    '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') },
    './resource-thumbnails': thumbnails
  });
  let props = initialProps;

  function render(nextProps = props) {
    props = nextProps;
    const mounted = new Set();

    function expand(node, location) {
      if (Array.isArray(node)) return node.map((child, index) => {
        const identity = child && typeof child === 'object' && child.key !== undefined
          ? `key=${child.key}` : `index=${index}`;
        return expand(child, `${location}/${identity}`);
      });
      if (node === null || node === undefined || typeof node === 'boolean') return null;
      if (typeof node !== 'object') return node;
      if (typeof node.type === 'function') {
        const identity = `${location}/${node.type.name}`;
        mounted.add(identity);
        if (!states.has(identity)) states.set(identity, []);
        const previous = activeHooks;
        activeHooks = { cells: states.get(identity), cursor: 0 };
        let output;
        try {
          output = node.type(node.props);
        } finally {
          activeHooks = previous;
        }
        return expand(output, `${identity}/output`);
      }
      return { ...node, props: {
        ...node.props,
        children: expand(node.props.children, `${location}/${node.type}/children`)
      } };
    }

    const tree = expand(jsx(YouTubeResourceList, props), 'root');
    for (const identity of states.keys()) if (!mounted.has(identity)) states.delete(identity);
    return tree;
  }

  return { render };
}

function findAll(node, predicate) {
  if (Array.isArray(node)) return node.flatMap((child) => findAll(child, predicate));
  if (!node || typeof node !== 'object') return [];
  return [...(predicate(node) ? [node] : []), ...findAll(node.props.children, predicate)];
}

function text(node) {
  if (Array.isArray(node)) return node.map(text).join('');
  if (node === null || node === undefined || typeof node === 'boolean') return '';
  return typeof node === 'object' ? text(node.props.children) : String(node);
}

const tags = (tree, type) => findAll(tree, (node) => node.type === type);
const thumbnailFrames = (tree) => findAll(tree, (node) => node.props['data-youtube-thumbnail']);
const hasLabel = (tree, label) => findAll(tree, (node) => node.type === 'span' && text(node) === label).length > 0;

test('video and playlist rows use only supplied thumbnail URLs, row-sized first', () => {
  const thumbnails = {
    default: { url: 'https://i.ytimg.com/supplied/default.jpg' },
    medium: { url: 'https://i.ytimg.com/supplied/medium.jpg' },
    high: { url: 'https://i.ytimg.com/supplied/high.jpg' },
    standard: { url: 'https://i.ytimg.com/supplied/standard.jpg' },
    maxres: { url: 'https://i.ytimg.com/supplied/maxres.jpg' }
  };
  for (const id of ['video-id', 'playlist-id']) {
    assert.deepEqual(youtubeThumbnailUrls({ id, snippet: { thumbnails } }), [
      thumbnails.medium.url,
      thumbnails.high.url,
      thumbnails.standard.url,
      thumbnails.maxres.url,
      thumbnails.default.url
    ]);
  }
});

test('missing thumbnails never fabricate a thumbnail from video or playlist IDs', () => {
  for (const resource of [
    { id: 'video-id' },
    { id: 'playlist-id', snippet: { title: 'Playlist without artwork' } },
    { id: 'member-id', snippet: { resourceId: { videoId: 'video-id' }, thumbnails: {} } }
  ]) assert.deepEqual(youtubeThumbnailUrls(resource), []);
});

test('fallback URLs are distinct usable provider values', () => {
  assert.deepEqual(youtubeThumbnailUrls({
    id: 'video-id',
    snippet: {
      thumbnails: {
        medium: { url: ' https://i.ytimg.com/supplied/shared.jpg ' },
        high: { url: 'https://i.ytimg.com/supplied/shared.jpg' },
        standard: { url: 'not-a-url' },
        maxres: { url: 'javascript:alert(1)' },
        default: { url: 'https://i.ytimg.com/supplied/default.jpg' }
      }
    }
  }), [
    'https://i.ytimg.com/supplied/shared.jpg',
    'https://i.ytimg.com/supplied/default.jpg'
  ]);
});

test('non-HTTPS and empty images leave the missing-thumbnail fallback available', () => {
  assert.deepEqual(youtubeThumbnailUrls({
    id: 'playlist-id',
    snippet: {
      thumbnails: {
        default: { url: '' },
        medium: { url: 'http://i.ytimg.com/supplied/medium.jpg' },
        high: { url: '//i.ytimg.com/supplied/high.jpg' },
        standard: { url: 'data:image/png;base64,unused' },
        maxres: { url: 'file:///private/supplied.jpg' }
      }
    }
  }), []);
});

test('actual list renders the supplied native thumbnail and a truthful video label', () => {
  const resource = {
    id: 'video-id',
    snippet: {
      title: 'Portrait clip #shorts',
      thumbnails: { medium: { url: 'https://i.ytimg.com/supplied/portrait.jpg', width: 1080, height: 1920 } }
    },
    status: { privacyStatus: 'private', podcastStatus: 'enabled' }
  };
  const tree = mountList({ data: { source: 'unit-fixture', items: [resource] }, resourceType: 'video', select() {} }).render();
  const [image] = tags(tree, 'img');
  assert.equal(tags(tree, 'img').length, 1);
  assert.equal(image.props.src, resource.snippet.thumbnails.medium.url);
  assert.equal(image.props.alt, '');
  assert.equal(image.props.loading, 'lazy');
  assert.equal(thumbnailFrames(tree)[0].props['data-youtube-thumbnail'], 'image');
  assert.ok(hasLabel(tree, 'Video'));
  assert.equal(hasLabel(tree, 'Short'), false, 'Portrait shape and #shorts title do not establish Shorts classification.');
  assert.equal(hasLabel(tree, 'Podcast'), false, 'A video resource does not become a podcast show.');
  assert.ok(text(tree).includes(resource.snippet.title));
});

test('actual missing-image fallback leaves a native button selectable and preserves the original resource', () => {
  const resource = { id: 'video-id', snippet: { title: 'Video without artwork' } };
  let selected;
  const calls = [];
  const props = {
    data: { source: 'unit-fixture', items: [resource] },
    resourceType: 'video',
    select(item) { calls.push(item); selected = item; },
    isSelected: (item) => selected === item
  };
  const mounted = mountList(props);
  let tree = mounted.render();
  let [button] = tags(tree, 'button');
  assert.equal(tags(tree, 'img').length, 0);
  assert.equal(thumbnailFrames(tree)[0].props['data-youtube-thumbnail'], 'fallback');
  assert.ok(text(tree).includes('No thumbnail'));
  assert.equal(button.props.type, 'button');
  assert.equal(button.props.disabled, false);
  assert.equal(button.props['aria-pressed'], false);
  button.props.onClick();
  assert.equal(calls.length, 1);
  assert.strictEqual(calls[0], resource);
  assert.strictEqual(calls[0].snippet, resource.snippet);
  tree = mounted.render();
  [button] = tags(tree, 'button');
  assert.equal(button.props['aria-pressed'], true);
  assert.ok(hasLabel(tree, 'Selected'));
});

test('actual image error callbacks retry only distinct supplied URLs, then render the exhausted fallback', () => {
  const resource = {
    id: 'video-id',
    snippet: {
      title: 'Images that fail',
      thumbnails: {
        medium: { url: 'https://i.ytimg.com/supplied/medium.jpg' },
        high: { url: 'https://i.ytimg.com/supplied/medium.jpg' },
        standard: { url: 'invalid-url' },
        default: { url: 'https://i.ytimg.com/supplied/default.jpg' }
      }
    }
  };
  const calls = [];
  const mounted = mountList({ data: { source: 'unit-fixture', items: [resource] }, resourceType: 'video', select: (item) => calls.push(item) });
  const attempted = [];
  let tree = mounted.render();
  for (const expectedUrl of youtubeThumbnailUrls(resource)) {
    const [image] = tags(tree, 'img');
    assert.equal(tags(tree, 'img').length, 1);
    assert.equal(image.props.src, expectedUrl);
    attempted.push(image.props.src);
    image.props.onError();
    // A repeated notification from the same failed image must not skip the next URL.
    image.props.onError();
    tree = mounted.render();
  }
  assert.deepEqual(attempted, [resource.snippet.thumbnails.medium.url, resource.snippet.thumbnails.default.url]);
  assert.equal(tags(tree, 'img').length, 0);
  assert.equal(thumbnailFrames(tree)[0].props['data-youtube-thumbnail'], 'fallback');
  assert.ok(text(tree).includes('No thumbnail'));
  assert.equal(tags(tree, 'button')[0].props.disabled, false);
  assert.deepEqual(calls, [], 'Image errors do not select or replace a resource.');

  const refreshed = { ...resource, snippet: { ...resource.snippet, thumbnails: {
    medium: { url: 'https://i.ytimg.com/supplied/refreshed.jpg' }
  } } };
  tree = mounted.render({ data: { source: 'unit-fixture', items: [refreshed] }, resourceType: 'video', select: (item) => calls.push(item) });
  assert.equal(tags(tree, 'img')[0].props.src, refreshed.snippet.thumbnails.medium.url);
  assert.equal(thumbnailFrames(tree)[0].props['data-youtube-thumbnail'], 'image');
});

test('actual playlist rows label only confirmed podcast shows as Podcast', () => {
  const resources = [
    { id: 'podcast-id', snippet: { title: 'Confirmed show' }, status: { podcastStatus: 'enabled' } },
    { id: 'playlist-id', snippet: { title: 'Podcast in the title', thumbnails: {
      medium: { url: 'https://i.ytimg.com/supplied/square.jpg', width: 300, height: 300 }
    } }, status: { podcastStatus: 'disabled' } },
    { id: 'unknown-playlist-id', snippet: { title: 'No status returned' } }
  ];
  const tree = mountList({ data: { source: 'unit-fixture', items: resources }, resourceType: 'playlist', select() {} }).render();
  const buttons = tags(tree, 'button');
  assert.ok(hasLabel(buttons[0], 'Podcast'));
  assert.equal(hasLabel(buttons[0], 'Playlist'), false);
  for (const button of buttons.slice(1)) {
    assert.ok(hasLabel(button, 'Playlist'));
    assert.equal(hasLabel(button, 'Podcast'), false);
  }
});

test('actual buttons honor caller canonical IDs, selected state and unavailable/global-disabled state', () => {
  const resource = { id: 'membership-id', snippet: { title: 'Playlist episode', resourceId: { videoId: 'canonical-video' } } };
  const calls = [];
  const props = {
    data: { source: 'unit-fixture', items: [resource] },
    resourceType: 'video',
    select: (item) => calls.push(item),
    getIdentifier: (item) => item.snippet.resourceId.videoId,
    isSelected: (item) => item === resource
  };
  const mounted = mountList(props);
  let [button] = tags(mounted.render(), 'button');
  assert.equal(button.props.type, 'button');
  assert.equal(button.props['aria-pressed'], true);
  assert.equal(button.props.disabled, false);
  assert.equal(button.props['data-youtube-resource-id'], resource.id);
  assert.equal(button.props['data-youtube-selection-id'], 'canonical-video');
  assert.ok(text(button).includes('ID: canonical-video'));
  assert.equal(text(button).includes('ID: membership-id'), false);
  button.props.onClick();
  assert.strictEqual(calls[0], resource);

  [button] = tags(mounted.render({ ...props, getIdentifier: () => undefined }), 'button');
  assert.equal(button.props.disabled, true);
  assert.equal(button.props['aria-pressed'], false);
  assert.equal(button.props['data-youtube-selection-id'], undefined);
  assert.ok(text(button).includes('Video ID unavailable'));

  [button] = tags(mounted.render({ ...props, disabled: true }), 'button');
  assert.equal(button.props.disabled, true);
  assert.equal(button.props['aria-pressed'], true);
  assert.equal(calls.length, 1, 'Rendering disabled rows never invokes selection.');
});
