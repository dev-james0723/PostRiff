const { test } = require('node:test');
const assert = require('node:assert/strict');
const { createHash } = require('node:crypto');
const { readFileSync } = require('node:fs');
const path = require('node:path');
const React = require('react');
const { renderToStaticMarkup } = require('react-dom/server');
const { WEB, SRC, REPO, createLoader } = require('./agent-ui-journeys/_load.cjs');
const { createHarness } = require('./agent-ui-client-harness.cjs');

test('the comparison players serve the measured clips and the captions from each edit', () => {
  const Page = createLoader().load('src/app/app/creative/example/page').default;
  const html = renderToStaticMarkup(React.createElement(Page));
  const receipt = require(path.join(REPO, 'docs/creative-intelligence/examples/timer-study/render-receipt.json'));
  const videos = [...html.matchAll(/<video\b[^>]+src="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(videos.map(url => path.basename(url)), ['reference.mp4', 'original-cut.mp4', 'revised-cut.mp4']);
  for (const url of videos) {
    const bytes = readFileSync(path.join(WEB, 'public', url));
    assert.equal(createHash('sha256').update(bytes).digest('hex'), receipt.artifacts[path.basename(url)].sha256);
  }
  const captions = [...html.matchAll(/<track\b[^>]+src="([^"]+)"/g)].map(match => match[1]);
  assert.deepEqual(captions, videos.map(url => url.replace('.mp4', '.vtt')));
  assert.match(readFileSync(path.join(WEB, 'public', captions[0]), 'utf8'), /00:00.000 --> 00:04.000\n\[Continuous low electronic tone\]/);
  for (const [index, url] of captions.slice(1).entries()) {
    const cues = readFileSync(path.join(WEB, 'public', url), 'utf8').trim().split(/\n\n/).slice(1);
    const expected = index === 0 ? receipt.firstExport : receipt.revisedExport;
    assert.deepEqual(cues.map(cue => cue.split('\n')[1]), expected.scenes.map(scene => scene.caption));
  }
  const study = require(path.join(REPO, 'docs/creative-intelligence/examples/hypit-timing-study.json'));
  assert.ok(html.includes(`href="${study.export.relativePlaybackUrl}"`));
  const storyboard = readFileSync(path.join(WEB, 'public', study.export.relativePlaybackUrl));
  assert.equal(createHash('sha256').update(storyboard).digest('hex'), study.export.sha256);
});

test('two selectable moments show the stills from both cuts', () => {
  const Page = createLoader().load('src/app/app/creative/example/page').default;
  const html = renderToStaticMarkup(React.createElement(Page));
  assert.match(html, /role="tablist"[^>]*aria-label="Comparison time"|aria-label="Comparison time"[^>]*role="tablist"/);
  assert.match(html, /role="tab"[^>]*>Opening · 0\.5 s</);
  assert.match(html, /role="tab"[^>]*>Second shot · 2 s</);
  const stills = [...html.matchAll(/<img\b[^>]*src="(\/rafii\/studio-examples\/[^"]+\.png)"/g)]
    .map(match => path.basename(match[1]));
  assert.deepEqual(stills, ['original-cut-500ms.png', 'revised-cut-500ms.png', 'original-cut-2000ms.png', 'revised-cut-2000ms.png']);
  const images = stills.map(file => readFileSync(path.join(WEB, 'public/rafii/studio-examples', file)));
  assert.ok(!images[0].equals(images[1]), 'the opening frames should differ');
  assert.ok(images[2].equals(images[3]), 'the second-shot frames should match');
});

function mountPlayer(t) {
  const loader = createLoader({ stubs: {
    [path.join(SRC, 'components/ui/button')]: { Button: props => React.createElement('button', props) }
  } });
  const { SampleCutPlayer } = loader.load('src/app/app/creative/example/sample-cut-player');
  const harness = createHarness(React);
  t.after(() => harness.cleanup());
  harness.render(React.createElement(SampleCutPlayer));
  for (const player of harness.findAll('video')) {
    // The node harness supplies host refs and events. The browser normally supplies these media properties.
    Object.assign(player, { readyState: 1, currentTime: 0, pause: t.mock.fn() });
  }
  return {
    harness,
    video: name => harness.find(`video[aria-label="${name}"]`),
    shot: index => harness.find(node => node.localName === 'button' && node.getAttribute('aria-label')?.startsWith(`Scene ${index},`))
  };
}

test('selecting a shot seeks the active MP4 and playback follows both measured cuts', t => {
  const { harness, video, shot } = mountPlayer(t);
  const first = video('First cut');
  for (const [index, seconds] of [[2, 1.25], [3, 2.75], [1, 0]]) {
    harness.click(shot(index));
    assert.equal(first.currentTime, seconds);
    assert.equal(shot(index).getAttribute('aria-pressed'), 'true');
  }
  for (const [seconds, index] of [[1.249, 1], [1.25, 2], [2.749, 2], [2.75, 3], [4, 3]]) {
    first.currentTime = seconds;
    harness.dispatch(first, 'onTimeUpdate');
    assert.equal(shot(index).getAttribute('aria-pressed'), 'true', `shot at ${seconds} seconds`);
    const display = harness.find('section[aria-label="Cut timeline"]').textContent;
    assert.ok(display.includes(`0:0${seconds} / 0:04`), `time display at ${seconds} seconds`);
  }
});

test('switching cuts preserves the exact playback position even when the target metadata arrives late', t => {
  const { harness, video, shot } = mountPlayer(t);
  const first = video('First cut');
  const revised = video('Revised opening');
  revised.readyState = 0;
  first.currentTime = 0.625;
  harness.dispatch(first, 'onTimeUpdate');
  harness.click(harness.button('Revised opening'));
  assert.equal(first.pause.mock.callCount(), 1);
  assert.equal(revised.currentTime, 0);
  assert.equal(revised.parentNode.getAttribute('hidden'), null);
  assert.equal(first.parentNode.getAttribute('hidden'), '');
  assert.match(harness.container.textContent, /Start with one turn\./);
  first.currentTime = 3;
  harness.dispatch(first, 'onTimeUpdate');
  assert.equal(shot(1).getAttribute('aria-pressed'), 'true');
  revised.readyState = 1;
  harness.dispatch(revised, 'onLoadedMetadata');
  assert.equal(revised.currentTime, 0.625);
  harness.click(shot(3));
  assert.equal(revised.currentTime, 2.75);
  harness.click(harness.button('First cut'));
  assert.equal(first.currentTime, 2.75);
  assert.equal(shot(3).getAttribute('aria-pressed'), 'true');
});
