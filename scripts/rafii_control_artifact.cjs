/** Actual local Python function archive of an allowlisted Control candidate. No deployment. */
const fs = require('node:fs'), path = require('node:path'), os = require('node:os');
const assert = require('node:assert/strict'), crypto = require('node:crypto');
const { spawnSync } = require('node:child_process');
const root = path.resolve(__dirname, '..');
const modules = process.env.VERCEL_BUILDER_MODULES || path.join(root, '.codex/consumer-ready/vercel/node_modules');
const python = process.env.CONTROL_BUILD_PYTHON || path.join(root, '.control-venv/bin/python');

(async () => {
  const cliVersion = require(path.join(modules, 'vercel/package.json')).version;
  const builderVersion = require(path.join(modules, '@vercel/python/package.json')).version;
  assert.equal(cliVersion, '59.23.2'); assert.equal(builderVersion, '14.2.0');
  const candidate = path.join(fs.mkdtempSync(path.join(os.tmpdir(), 'rafii-control-artifact-')), 'candidate');
  const packaged = spawnSync(python, [path.join(root, 'scripts/rafii_control_package.py'), '--output', candidate], { encoding: 'utf8', env: { PATH: process.env.PATH, PYTHONDONTWRITEBYTECODE: '1' } });
  assert.equal(packaged.status, 0, packaged.stderr);
  const utils = require(path.join(modules, '@vercel/build-utils'));
  const files = {};
  function walk(dir, prefix = '') {
    for (const entry of fs.readdirSync(dir, { withFileTypes: true })) {
      const name = prefix + entry.name;
      assert(!entry.isSymbolicLink(), 'Symlink in candidate');
      if (entry.isDirectory()) walk(path.join(dir, entry.name), name + '/');
      else files[name] = new utils.FileFsRef({ fsPath: path.join(dir, entry.name) });
    }
  }
  walk(candidate);
  const sourceManifest = JSON.parse(fs.readFileSync(path.join(candidate, 'source-manifest.json'), 'utf8'));
  const functions = JSON.parse(fs.readFileSync(path.join(candidate, 'vercel.json'), 'utf8')).services.control_api.functions;
  const keep = new Set(['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL']);
  for (const key of Object.keys(process.env)) if (!keep.has(key)) delete process.env[key];
  process.env.VERCEL_TELEMETRY_DISABLED = '1';
  const result = await require(path.join(modules, '@vercel/python')).build({ workPath: candidate, repoRootPath: candidate, files, entrypoint: 'api/control.py', meta: { isDev: false }, config: { functions } });
  assert.equal(result.resultVersion, 3);
  const artifact = result.result.output, names = Object.keys(artifact.files);
  for (const required of ['api/control.py', 'src/rafii_control/hosted.py', 'src/postriff_phase2/locale_catalogue.json']) assert(names.includes(required), required);
  assert(names.some(name => name.endsWith('/contracts/metric-query.schema.json')));
  const forbidden = /(^|\/)(\.env[^/]*|broker\.key|\.git|\.agents|\.claude|\.token-pilot|node_modules|\.next)(\/|$)/;
  assert.deepEqual(names.filter(name => forbidden.test(name)), []);
  assert.deepEqual(names.filter(name => !name.startsWith('_vendor/') && /^(tests\/|control-web\/|api\/index\.py|src\/postriff_phase2\/hosted_app\.py)/.test(name)), []);
  const zip = await artifact.createZip(), filename = path.join(candidate, 'function.zip');
  fs.writeFileSync(filename, zip);
  const record = { status: 'PASS', execution: 'actual local separate Control Python archive; not deployed or invoked on Vercel', cliVersion, builderVersion, runtime: artifact.runtime, architecture: artifact.architecture, bytes: zip.length, sha256: crypto.createHash('sha256').update(zip).digest('hex'), archive: filename, files: names.length, sourceManifest };
  fs.writeFileSync(path.join(root, 'docs/rafii-control-v2/evidence/control-artifact.json'), JSON.stringify(record, null, 2) + '\n');
  console.log(JSON.stringify({ ...record, sourceManifest: Object.keys(sourceManifest).length }));
})().catch(error => { console.error(error); process.exitCode = 1; });
