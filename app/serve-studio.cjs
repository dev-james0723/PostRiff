// Local launcher only. The authenticated workspace uses the standard Rafii Next app.
const { createServer } = require('node:http');
const { createRequire } = require('node:module');
const path = require('node:path');
const { studioRoutes } = require('./studio-http.cjs');

const localWorkspace = process.env.RAFII_STUDIO_LOCAL === '1';
const web = localWorkspace ? path.resolve(__dirname, '../web') : path.join(__dirname, '.supabase-site');
const next = createRequire(path.join(web, 'package.json'))('next');
const site = new URL(process.env.NEXT_PUBLIC_APP_URL);
const port = Number(site.port);
const app = next({ dev: false, dir: web, hostname: site.hostname, port });

async function workspaceReady() {
  try {
    const response = await fetch('http://127.0.0.1:4331/api/auth/config', {
      signal: AbortSignal.timeout(2000), redirect: 'error'
    });
    if (!response.ok) return false;
    const config = await response.json();
    return config.provider === 'dev' && config.execution === 'dev-synthetic';
  } catch { return false; }
}

async function start() {
  await app.prepare();
  const handleNext = app.getRequestHandler();
  const handleStudio = studioRoutes(port);
  const server = createServer(async (req, res) => {
    const [route, query = ''] = req.url.split('?');
    if (await handleStudio(req, res, route)) return;
    if (localWorkspace && (req.method === 'GET' || req.method === 'HEAD') &&
        /^\/app\/creative\/?$/.test(route) && !query && !req.headers.rsc && !(await workspaceReady())) {
      await handleStudio(req, res, '/local-studio');
      return;
    }
    await handleNext(req, res);
  });
  server.requestTimeout = 30000;
  server.listen(port, '127.0.0.1');
}

start().catch((error) => {
  console.error(error);
  process.exit(1);
});
