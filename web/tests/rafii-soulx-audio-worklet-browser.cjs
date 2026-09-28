/** Synthetic media-track check of the real audio worklet in Chromium and WebKit. No GPT Live or SoulX calls. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const path = require('node:path');
const { chromium, webkit } = require('playwright');

const worklet = fs.readFileSync(path.join(__dirname, '../public/raffi/avatar-audio-tap.js'));
const server = http.createServer((request, response) => {
  if (request.url === '/raffi/avatar-audio-tap.js') {
    response.writeHead(200, { 'content-type': 'text/javascript' });
    response.end(worklet);
  } else {
    response.writeHead(200, { 'content-type': 'text/html' });
    response.end('<button id="start">Start synthetic track</button><audio id="speaker"></audio>');
  }
});

(async () => {
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const url = `http://127.0.0.1:${server.address().port}`;
  try {
    for (const [name, engine] of Object.entries({ chromium, webkit })) {
      const browser = await engine.launch({ headless: true });
      try {
        const page = await browser.newPage();
        await page.goto(url);
        await page.evaluate(() => {
          window.captured = [];
          document.querySelector('#start').onclick = async () => {
            const context = new AudioContext();
            await context.resume();
            const oscillator = context.createOscillator();
            oscillator.frequency.value = 440;
            const destination = context.createMediaStreamDestination();
            oscillator.connect(destination);
            oscillator.start();
            const speaker = document.querySelector('#speaker');
            speaker.srcObject = destination.stream;
            await speaker.play();
            await context.audioWorklet.addModule('/raffi/avatar-audio-tap.js');
            const source = context.createMediaStreamSource(destination.stream);
            const tap = new AudioWorkletNode(context, 'rafii-avatar-audio-tap');
            const silent = context.createGain(); silent.gain.value = 0;
            tap.port.addEventListener('message', (event) => window.captured.push(event.data));
            tap.port.start();
            source.connect(tap); tap.connect(silent); silent.connect(context.destination);
            window.media = { context, oscillator, speaker, destination, tap };
          };
        });
        await page.locator('#start').click();
        await page.waitForFunction(() => window.captured.some((packet) =>
          [...packet].reduce((sum, value) => sum + Math.abs(value), 0) / packet.length > 0.01), { timeout: 10000 });
        const result = await page.evaluate(() => ({
          playing: !window.media.speaker.paused && !window.media.speaker.muted,
          sameStream: window.media.speaker.srcObject === window.media.destination.stream,
          packets: window.captured.length,
          samples: window.captured.at(-1).length,
          energy: [...window.captured.at(-1)].reduce((sum, value) => sum + Math.abs(value), 0) / window.captured.at(-1).length,
          rate: window.media.context.sampleRate
        }));
        assert.equal(result.playing, true, `${name}: normal speaker path remains active`);
        assert.equal(result.sameStream, true, `${name}: tap reads same media stream`);
        assert.ok(result.energy > 0.01, `${name}: tap captured real samples`);
        assert.ok(result.samples >= 2048, `${name}: packet buffering`);
        console.log(`PASS ${name}: ${result.packets} packets, ${result.samples} samples, ${result.rate} Hz, original speaker path active`);
        await page.evaluate(async () => { window.media.oscillator.stop(); await window.media.context.close(); });
      } finally { await browser.close(); }
    }
  } finally { server.close(); }
})().catch((error) => { console.error(error); process.exitCode = 1; server.close(); });
