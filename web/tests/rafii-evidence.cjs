/**
 * Rafii v9 route evidence: every route × viewport × theme against the LOCAL dev harness only.
 * Writes screenshots to docs/design/rafii-v9/evidence/routes/<slug>/<w>x<h>-<theme>.png and a
 * summary.json with console errors, horizontal overflow and axe-core violations per capture.
 *
 *   node web/tests/rafii-evidence.cjs [--routes=home,queue] [--viewports=390x844,1440x1000]
 *                                     [--themes=dark,light] [--browser=chromium|webkit] [--no-axe] [--merge]
 *
 * Identity is the dev harness's synthetic principal (cookies + localStorage), never a real account:
 * the seeded one from evidence/seed.json when present (populated states), else a fresh principal.
 * Auth, invite and marketing routes are captured signed out, as a visitor sees them.
 */
const { chromium, webkit } = require('playwright');
const { randomUUID } = require('node:crypto');
const fs = require('node:fs');
const path = require('node:path');

const base = process.env.RAFII_WEB_URL || 'http://localhost:3100';
if (!['127.0.0.1', 'localhost'].includes(new URL(base).hostname)) throw new Error('Evidence runs against the local harness only.');
const out = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/routes');
const args = Object.fromEntries(process.argv.slice(2).map((a) => a.replace(/^--/, '').split('=')).map(([k, v]) => [k, v ?? true]));

const ALL_VIEWPORTS = ['320x740', '375x812', '390x844', '430x932', '768x1024', '1024x768', '1440x1000', '1920x1080'];
const ROUTES = {
  home: '/app',
  overview: '/app/overview',
  ideas: '/app/ideas',
  automations: '/app/automations',
  calendar: '/app/calendar',
  pipeline: '/app/pipeline',
  library: '/app/library',
  channels: '/app/channels',
  queue: '/app/queue',
  analytics: '/app/analytics',
  inbox: '/app/inbox',
  'workspace-brand': '/app/workspace/brand',
  'workspace-memory': '/app/workspace/memory',
  'workspace-members': '/app/workspace/members',
  'workspace-roles': '/app/workspace/roles',
  'workspace-audit': '/app/workspace/audit',
  'account-profile': '/app/account/profile',
  'account-notifications': '/app/account/notifications',
  'account-billing': '/app/account/billing',
  'account-privacy': '/app/account/privacy',
  'account-models': '/app/account/models',
  'account-api': '/app/account/api',
  'auth-sign-in': '/auth/sign-in',
  'auth-sign-up': '/auth/sign-up',
  'auth-reset': '/auth/reset',
  'auth-verify': '/auth/verify',
  'channels-connect': '/app/channels/connect',
  'not-found': '/app/this-route-does-not-exist',
  marketing: '/',
  pricing: '/pricing',
  'marketing-channels': '/channels',
  docs: '/docs',
  'docs-article': '/docs/getting-started',
  'channel-detail': '/channels/linkedin',
  changelog: '/changelog',
  contact: '/contact',
  'data-deletion': '/data-deletion',
  'privacy-page': '/privacy',
  'security-page': '/security',
  'status-page': '/status',
  terms: '/terms',
  'channels-forwarder': '/channels/connect',
  // An unknown invitation token: the invitation page's own invalid state (no real invitation is needed).
  invite: '/invite/evidence-not-a-real-token'
};
const seedFile = path.resolve(__dirname, '../../docs/design/rafii-v9/evidence/seed.json');
const seed = fs.existsSync(seedFile) ? JSON.parse(fs.readFileSync(seedFile, 'utf8')) : null;
// Routes that need an id are added at run time: --conversation=<id> (default: the seeded one) and --invite=<token>.
const conversation = args.conversation || seed?.conversationId;
if (conversation) ROUTES.conversation = `/app/agent/${encodeURIComponent(String(conversation))}`;
if (args.invite) ROUTES.invite = `/invite/${encodeURIComponent(String(args.invite))}`;

const routes = args.routes ? String(args.routes).split(',').filter((r) => ROUTES[r]) : Object.keys(ROUTES);
const viewports = (args.viewports ? String(args.viewports).split(',') : ALL_VIEWPORTS).map((v) => v.split('x').map(Number));
const themes = args.themes ? String(args.themes).split(',') : ['dark', 'light'];
const engine = args.browser === 'webkit' ? webkit : chromium;
const principal = process.env.RAFII_DEV_PRINCIPAL || seed?.principal || randomUUID();
/** Every onboarding tour marked dismissed and nudged, so tips never cover the page in evidence captures. */
const TOUR_IDS = [...fs.readFileSync(path.resolve(__dirname, '../src/features/onboarding/tours.ts'), 'utf8').matchAll(/^ {2,4}id: '([a-z-]+)'/gm)].map((m) => m[1]);
const TOURS_SEEN = JSON.stringify({ completed: {}, dismissed: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])), nudged: Object.fromEntries(TOUR_IDS.map((id) => [id, 1])) });
/** Seen signed out: auth, invitation and marketing surfaces (a signed-in visit to /auth redirects to the app). */
const SIGNED_OUT = new Set(['auth-sign-in', 'auth-sign-up', 'auth-reset', 'auth-verify', 'invite', 'marketing', 'pricing', 'marketing-channels', 'docs', 'docs-article', 'channel-detail', 'changelog', 'contact', 'data-deletion', 'privacy-page', 'security-page', 'status-page', 'terms', 'channels-forwarder']);
const runAxe = !args['no-axe'];
const axeSource = runAxe ? fs.readFileSync(require.resolve('axe-core/axe.min.js'), 'utf8') : null;

(async () => {
  // A locally installed build may be named explicitly (RAFII_CHROMIUM_PATH / RAFII_WEBKIT_PATH); nothing is downloaded.
  const executablePath = (engine === webkit ? process.env.RAFII_WEBKIT_PATH : process.env.RAFII_CHROMIUM_PATH) || undefined;
  const browser = await engine.launch({ headless: true, executablePath });
  const summary = { base, browser: args.browser || 'chromium', principal, startedAt: new Date().toISOString(), captures: [] };
  try {
    for (const theme of themes) {
      for (const [width, height] of viewports) {
        const contexts = {};
        for (const signedIn of [true, false]) {
          const context = await browser.newContext({ viewport: { width, height }, deviceScaleFactor: 1, colorScheme: theme === 'dark' ? 'dark' : 'light' });
          await context.addCookies([
            ...(signedIn ? [{ name: 'postriff_dev', value: '1', url: base }, { name: 'postriff_dev_principal', value: principal, url: base }] : []),
            { name: 'active_theme', value: 'rafii', url: base }
          ]);
          await context.addInitScript(({ id, theme, signedIn, tours }) => {
            if (signedIn) localStorage.setItem('postriff-dev-principal', id);
            localStorage.setItem('theme', theme);
            localStorage.setItem('postriff-onboarding', tours);
          }, { id: principal, theme, signedIn, tours: TOURS_SEEN });
          // The browser reaches only the harness origin (the harness itself must run with POSTRIFF_RESEARCH=0).
          await context.route('**/*', (route) => (new URL(route.request().url()).origin === new URL(base).origin ? route.continue() : route.abort()));
          contexts[signedIn ? 'in' : 'out'] = context;
        }
        for (const slug of routes) {
          const context = contexts[SIGNED_OUT.has(slug) ? 'out' : 'in'];
          const page = await context.newPage();
          const errors = [];
          page.on('pageerror', (e) => errors.push(`pageerror: ${e.message}`));
          page.on('console', (m) => m.type() === 'error' && !/net::ERR_FAILED/.test(m.text()) && errors.push(`console: ${m.text().slice(0, 300)}`));
          const capture = { route: slug, path: ROUTES[slug], viewport: `${width}x${height}`, theme, signedIn: !SIGNED_OUT.has(slug), errors, overflow: null, axe: null, file: null };
          try {
            await page.goto(base + ROUTES[slug], { waitUntil: 'networkidle', timeout: 60000 });
            // Enter the dev workspace if the gate is showing (first visit per principal).
            const enter = page.getByRole('button', { name: 'Enter dev workspace' });
            if (await enter.count()) {
              await enter.click();
              await page.waitForLoadState('networkidle');
            }
            const welcome = page.getByRole('button', { name: 'Not now', exact: true });
            if (await welcome.count()) await welcome.click().catch(() => {});
            await page.waitForTimeout(600);
            capture.overflow = await page.evaluate(() => ({ scrollWidth: document.documentElement.scrollWidth, innerWidth: innerWidth, horizontal: document.documentElement.scrollWidth > innerWidth + 1 }));
            const dir = path.join(out, slug);
            fs.mkdirSync(dir, { recursive: true });
            capture.file = path.relative(path.resolve(__dirname, '../../docs/design/rafii-v9/evidence'), path.join(dir, `${width}x${height}-${theme}.png`));
            await page.screenshot({ path: path.join(dir, `${width}x${height}-${theme}.png`), fullPage: false });
            if (runAxe) {
              await page.addScriptTag({ content: axeSource });
              capture.axe = await page.evaluate(async () => {
                const result = await window.axe.run(document, { runOnly: ['wcag2a', 'wcag2aa'], resultTypes: ['violations'] });
                return result.violations.map((v) => ({ id: v.id, impact: v.impact, nodes: v.nodes.length, help: v.help }));
              });
            }
          } catch (error) {
            capture.errors.push(`capture: ${error.message}`);
          }
          summary.captures.push(capture);
          await page.close();
          process.stdout.write(`${slug} ${width}x${height} ${theme}: ${capture.errors.length ? 'errors ' + capture.errors.length : 'ok'}${capture.overflow?.horizontal ? ' OVERFLOW' : ''}${capture.axe?.length ? ' axe ' + capture.axe.length : ''}\n`);
        }
        await contexts.in.close();
        await contexts.out.close();
      }
    }
  } finally {
    await browser.close();
  }
  summary.finishedAt = new Date().toISOString();
  fs.mkdirSync(out, { recursive: true });
  const file = path.join(out, args.browser === 'webkit' ? 'summary-webkit.json' : 'summary.json');
  // --merge: a partial re-run replaces only its own captures (same route, viewport and theme) in the existing summary.
  if (args.merge && fs.existsSync(file)) {
    const previous = JSON.parse(fs.readFileSync(file, 'utf8'));
    const key = (c) => `${c.route}|${c.viewport}|${c.theme}`;
    const fresh = new Set(summary.captures.map(key));
    summary.captures = [...previous.captures.filter((c) => !fresh.has(key(c))), ...summary.captures];
    summary.startedAt = previous.startedAt;
    summary.mergedRuns = [...(previous.mergedRuns ?? []), { at: new Date().toISOString(), captures: fresh.size }];
  }
  fs.writeFileSync(file, JSON.stringify(summary, null, 2));
  const bad = summary.captures.filter((c) => c.errors.length || c.overflow?.horizontal || (c.axe && c.axe.length));
  console.log(`\n${summary.captures.length} captures, ${bad.length} with findings → ${file}`);
})();
