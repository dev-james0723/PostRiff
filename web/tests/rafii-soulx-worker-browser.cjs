/** Real HTTP/WebSocket browser-to-worker protocol with a fake inference engine; no CUDA or GPT Live. */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const http = require('node:http');
const net = require('node:net');
const path = require('node:path');
const { spawn } = require('node:child_process');
const ts = require('typescript');
const { chromium, webkit } = require('playwright');

const root = path.resolve(__dirname, '../..');
const python = process.env.RAFII_TEST_PYTHON || 'python3';
const source = fs.readFileSync(path.join(__dirname, '../src/lib/agent-runtime/soulx-renderer.ts'), 'utf8');
const rendererJs = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;

async function freePort() {
  const server = net.createServer();
  await new Promise((resolve) => server.listen(0, '127.0.0.1', resolve));
  const port = server.address().port;
  await new Promise((resolve) => server.close(resolve));
  return port;
}

(async () => {
  const pageServer = http.createServer((_request, response) => { response.writeHead(200, { 'content-type': 'text/html' }); response.end('<title>Rafii worker protocol</title>'); });
  await new Promise((resolve) => pageServer.listen(0, '127.0.0.1', resolve));
  const origin = `http://127.0.0.1:${pageServer.address().port}`;
  const workerPort = await freePort();
  const workerUrl = `http://127.0.0.1:${workerPort}`;
  const worker = spawn(python, ['-c', 'import uvicorn; from tests.test_rafii_soulx_worker_protocol import FakeEngine, worker; uvicorn.run(worker.create_app(FakeEngine()), host="127.0.0.1", port=' + workerPort + ', log_level="error")'],
    { cwd: root, env: { ...process.env, SOULX_ALLOWED_ORIGINS: origin }, stdio: ['ignore', 'ignore', 'pipe'] });
  let workerErrors = '';
  worker.stderr.on('data', (chunk) => { workerErrors = (workerErrors + chunk).slice(-3000); });
  try {
    const deadline = Date.now() + 10000;
    for (;;) {
      if (worker.exitCode !== null) throw new Error('Fake worker exited: ' + workerErrors);
      try { if ((await fetch(workerUrl + '/health')).ok) break; } catch {}
      if (Date.now() > deadline) throw new Error('Fake worker did not become ready: ' + workerErrors);
      await new Promise((resolve) => setTimeout(resolve, 100));
    }
    for (const [name, engine] of Object.entries({ chromium, webkit })) {
      const browser = await engine.launch({ headless: true });
      try {
        const page = await browser.newPage();
        await page.goto(origin);
        await page.evaluate(({ code, url }) => {
          const exports = {};
          new Function('exports', code)(exports);
          window.frames = []; window.metrics = [];
          window.client = new exports.SoulXRenderer(url);
          void window.client.startSession((frame) => window.frames.push(frame), () => {}, (metric) => window.metrics.push(metric));
        }, { code: rendererJs, url: workerUrl });
        try { await page.waitForFunction(() => window.metrics.some((metric) => metric.connection === 'connected'), undefined, { timeout: 12000 }); }
        catch (error) { console.error(name, await page.evaluate(() => window.metrics.slice(-6)), workerErrors); throw error; }
        await page.evaluate(() => window.client.pushAudio(Int16Array.from({ length: 160 }, () => 8000), 0));
        await page.waitForFunction(() => window.frames.length >= 1);
        const first = await page.evaluate(() => window.frames[0]);
        assert.equal(first.generation, 0);
        assert.equal(typeof first.sourcePcmSentAt, 'number');
        await page.evaluate(() => { window.client.interrupt(1); window.client.pushAudio(Int16Array.from({ length: 160 }, () => 8000), 1); });
        await page.waitForFunction(() => window.frames.some((frame) => frame.generation === 1));
        const result = await page.evaluate(() => ({ cancelAck: window.metrics.some((metric) => typeof metric.cancellationAcknowledgedAt === 'number'),
          frameCount: window.frames.length, generation: window.frames.at(-1).generation }));
        assert.equal(result.cancelAck, true);
        assert.equal(result.generation, 1);
        await page.evaluate(() => window.client.endSession());
        console.log(`PASS ${name}: real HTTP/WebSocket, fake inference, ${result.frameCount} frames, cancellation ack`);
      } finally { await browser.close(); }
    }
  } finally {
    worker.kill('SIGTERM');
    pageServer.close();
  }
})().catch((error) => { console.error(error); process.exitCode = 1; });
