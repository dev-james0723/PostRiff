// Loopback-only adapter. Workspace authentication and Library operations stay with Rafii.
const { execFile } = require('node:child_process');
const { readFile, stat } = require('node:fs/promises');
const { createReadStream } = require('node:fs');
const path = require('node:path');
const { pipeline } = require('node:stream/promises');

const web = path.resolve(__dirname, '../web');
const sampleDir = path.resolve(__dirname, '../docs/creative-intelligence/examples/timer-study');
const clips = new Set(['original-1', 'original-2', 'original-3', 'revised-intro']);
const actions = new Set(['sample', 'analyze', 'inspect', 'inspect-audio', 'reference-frames', 'blueprint', 'render']);
const files = new Map([
  ['/local-studio', ['studio-editor.html', 'text/html; charset=utf-8']],
  ['/studio-editor.css', ['studio-editor.css', 'text/css; charset=utf-8']],
  ['/studio-theme.css', [path.join(web, 'src/styles/rafii.css'), 'text/css; charset=utf-8']],
  ['/studio-editor.js', ['studio-editor.js', 'text/javascript; charset=utf-8']],
  ['/studio-workspace.js', ['.studio-build/studio-workspace.js', 'text/javascript; charset=utf-8']]
]);
const maxRequest = 45 * 1024 * 1024;

function problem(status, message) {
  return Object.assign(new Error(message), { status });
}

function reply(res, status, type, body, head = false) {
  res.writeHead(status, { 'Content-Type': type, 'Content-Length': Buffer.byteLength(body) });
  res.end(head ? undefined : body);
}

async function bodyOf(req) {
  if (req.headers['content-type']?.split(';')[0].trim().toLowerCase() !== 'application/json') {
    throw problem(415, 'Send a JSON Studio request.');
  }
  if (Number(req.headers['content-length']) > maxRequest) throw problem(413, 'This cut exceeds the local size limit.');
  let size = 0;
  const chunks = [];
  for await (const chunk of req) {
    size += chunk.length;
    if (size > maxRequest) throw problem(413, 'This cut exceeds the local size limit.');
    chunks.push(chunk);
  }
  let body;
  try { body = JSON.parse(Buffer.concat(chunks).toString('utf8')); } catch {}
  if (!body || typeof body !== 'object' || Array.isArray(body)) throw problem(400, 'Send a valid Studio request.');
  return body;
}

function runWorker(body, signal) {
  return new Promise((resolve, reject) => {
    const child = execFile(process.env.RAFII_STUDIO_PYTHON || '/usr/bin/python3',
      [path.join(__dirname, 'studio_media.py')], {
        signal, timeout: body.action === 'render' ? 235000 : 92000,
        encoding: 'buffer', maxBuffer: 65 * 1024 * 1024,
        // The byte-in/byte-out catalog and renderer need no workspace or cloud credentials.
        env: { PATH: process.env.PATH || '/opt/homebrew/bin:/usr/bin:/bin', LANG: 'en_US.UTF-8',
          TMPDIR: require('node:os').tmpdir(), PYTHONDONTWRITEBYTECODE: '1' }
      }, (error, output, diagnostics) => {
        if (!error) return resolve(output);
        let detail;
        try { detail = JSON.parse(diagnostics.toString()); } catch {}
        const status = Number(detail?.status);
        if (Number.isInteger(status) && status >= 400 && status <= 599 && typeof detail?.message === 'string') {
          return reject(problem(status, detail.message));
        }
        reject(problem(error.killed ? 504 : 503, 'The local media worker could not finish. Check the media tools and try again.'));
      });
    child.stdin.on('error', () => {}); // execFile's completion reports an early exit.
    child.stdin.end(JSON.stringify(body));
  });
}

async function mediaFile(req, res, file) {
  const size = (await stat(file)).size;
  const range = req.headers.range;
  let start = 0, end = size - 1;
  res.setHeader('Accept-Ranges', 'bytes');
  if (range) {
    const match = /^bytes=(\d*)-(\d*)$/.exec(range);
    if (match && (match[1] || match[2])) {
      start = match[1] ? Number(match[1]) : Math.max(0, size - Number(match[2]));
      end = match[1] && match[2] ? Math.min(end, Number(match[2])) : end;
    } else start = size;
    if (!Number.isSafeInteger(start) || start > end) {
      res.writeHead(416, { 'Content-Range': 'bytes */' + size }); res.end(); return;
    }
    res.setHeader('Content-Range', 'bytes ' + start + '-' + end + '/' + size);
  }
  res.writeHead(range ? 206 : 200, { 'Content-Type': 'video/mp4', 'Content-Length': end - start + 1 });
  if (req.method === 'HEAD') { res.end(); return; }
  await pipeline(createReadStream(file, { start, end }), res);
}

function studioRoutes(port, worker = runWorker) {
  let busy = false;
  const authorities = new Set(['localhost:' + port, '127.0.0.1:' + port]);
  return async function handle(req, res, route) {
    const isApi = route.startsWith('/studio-api/');
    const isClip = route.startsWith('/studio-clips/');
    if (!isApi && !isClip && !files.has(route)) return false;
    const host = req.headers.host;
    const head = req.method === 'HEAD';
    res.setHeader('Cache-Control', 'no-store');
    res.setHeader('X-Content-Type-Options', 'nosniff');
    res.setHeader('Referrer-Policy', 'no-referrer');
    res.setHeader('Cross-Origin-Resource-Policy', 'same-origin');
    try {
      if (!authorities.has(host) || !['127.0.0.1', '::1', '::ffff:127.0.0.1'].includes(req.socket.remoteAddress)) {
        throw problem(403, 'Open the editor on this Mac.');
      }
      if (isApi) {
        if (req.method !== 'POST') { res.setHeader('Allow', 'POST'); throw problem(405, 'Use POST.'); }
        if (req.headers.origin !== 'http://' + host || req.headers['sec-fetch-site'] === 'cross-site') {
          throw problem(403, 'Use the Studio page on this Mac.');
        }
        const action = route.slice('/studio-api/'.length);
        if (!actions.has(action)) throw problem(404, 'Unknown Studio operation.');
        if (busy) throw problem(429, 'A media task is running. Try again when it finishes.');
        busy = true;
        const controller = new AbortController();
        const stop = () => { if (!res.writableEnded) controller.abort(); };
        res.once('close', stop);
        try {
          const body = await bodyOf(req);
          if (action !== 'sample' && (action !== 'render' || Object.keys(body.uploads || {}).length || body.soundtrack)
              && body.rightsConfirmed !== true) throw problem(403, 'Confirm permission for this media first.');
          body.action = action;
          const output = await worker(body, controller.signal);
          if (!res.destroyed) reply(res, 200, action === 'render' ? 'video/mp4' : 'application/json', output);
        } finally { busy = false; res.off('close', stop); }
      } else {
        if (!head && req.method !== 'GET') { res.setHeader('Allow', 'GET, HEAD'); throw problem(405, 'Use GET.'); }
        if (isClip) {
          const id = route.slice('/studio-clips/'.length);
          if (!clips.has(id)) throw problem(404, 'This clip is unavailable.');
          await mediaFile(req, res, path.join(sampleDir, id + '.mp4'));
        } else {
          const [file, type] = files.get(route);
          if (type.startsWith('text/html')) {
            res.setHeader('X-Rafii-Studio-View', 'local-edit');
            res.setHeader('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' blob: data:; media-src 'self' blob:; connect-src 'self' https://oxacvkhpfgytkepxcaqh.supabase.co https://oxacvkhpfgytkepxcaqh.storage.supabase.co; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'");
          }
          reply(res, 200, type, await readFile(path.resolve(__dirname, file)), head);
        }
      }
    } catch (error) {
      if (!res.headersSent && !res.destroyed) {
        const status = error.status || (error.code === 'ENOENT' ? 404 : 500);
        reply(res, status, 'application/json', JSON.stringify({ message: error.status ? error.message : 'Studio resource unavailable.' }), head);
      }
    }
    return true;
  };
}
module.exports = { studioRoutes };
