/** Isolated builder execution in free CI; no Vercel API, project or deployment. */
const fs = require('node:fs');
const path = require('node:path');
const crypto = require('node:crypto');
const assert = require('node:assert/strict');
const here = __dirname;
const frozen = path.join(here, 'frozen');
const out = path.join(here, 'evidence');
const modules = process.env.VERCEL_BUILDER_MODULES;
assert(modules, 'Explicit isolated builder dependency directory required');
const source = process.env.GITHUB_SHA;
assert.match(source, /^[0-9a-f]{40}$/);
(async () => {
  assert.equal(require(path.join(modules, 'vercel/package.json')).version, '59.23.2');
  assert.equal(require(path.join(modules, '@vercel/python/package.json')).version, '14.2.0');
  const keep = new Set(['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL']);
  for (const key of Object.keys(process.env)) if (!keep.has(key)) delete process.env[key];
  process.env.VERCEL_TELEMETRY_DISABLED = '1';
  const utils = require(path.join(modules, '@vercel/build-utils'));
  const inputs = ['.python-version', 'requirements.txt', 'vercel.json',
    'a7a0_ping_core.py', 'api/discord/interactions.py'];
  const manifest = JSON.parse(fs.readFileSync(path.join(here, 'FROZEN-SOURCES.json'), 'utf8'));
  for (const name of inputs) {
    assert.equal(crypto.createHash('sha256').update(fs.readFileSync(path.join(frozen, name))).digest('hex'), manifest.files[name]);
  }
  const selected = Object.fromEntries(inputs.map(name =>
    [name, new utils.FileFsRef({fsPath: path.join(frozen, name)})]));
  fs.mkdirSync(out, {recursive: true});
  const work = fs.mkdtempSync(path.join(out, 'builder-'));
  const config = JSON.parse(fs.readFileSync(path.join(frozen, 'vercel.json'), 'utf8'));
  const result = await require(path.join(modules, '@vercel/python')).build({
    workPath: work, repoRootPath: work, files: selected,
    entrypoint: 'api/discord/interactions.py', meta: {isDev: false},
    config: {functions: config.functions}
  });
  assert.equal(result.resultVersion, 3);
  const artifact = result.result.output;
  assert.equal(artifact.runtime, 'python3.12');
  const names = Object.keys(artifact.files);
  for (const name of ['a7a0_ping_core.py', 'api/discord/interactions.py']) assert(names.includes(name), name);
  const forbidden = /(^|\/)(\.env[^/]*|\.git|\.codex|\.token-pilot|\.agents|node_modules|postriff_[^/]*|psycopg[^/]*)(\/|$)/;
  assert.deepEqual(names.filter(name => forbidden.test(name)), []);
  assert(!names.some(name => name.startsWith('tests/') || name.startsWith('evidence/')));
  const zip = await artifact.createZip();
  fs.writeFileSync(path.join(out, 'function.zip'), zip);
  const record = {status: 'PASS', execution: 'offline builder on GitHub standard runner',
    source, builderVersion: '14.2.0', cliPackageVersion: '59.23.2',
    runtime: artifact.runtime, architecture: artifact.architecture,
    handler: artifact.handler, environmentKeys: Object.keys(artifact.environment || {}).sort(),
    supportsResponseStreaming: artifact.supportsResponseStreaming ?? null,
    selectedInputs: inputs, fileCount: names.length, files: names.sort(),
    bytes: zip.length, sha256: crypto.createHash('sha256').update(zip).digest('hex'),
    deployment: 'NOT_RUN', liveDiscord: 'NOT_RUN'};
  fs.writeFileSync(path.join(out, 'builder-result.json'), JSON.stringify(record, null, 2) + '\n');
  console.log(JSON.stringify({...record, files: undefined}));
})().catch(error => { console.error(error); process.exitCode = 1; });
