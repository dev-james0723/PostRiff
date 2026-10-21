/** Hosted-build entrypoint. A deployment still needs explicit approval. */
const path = require('node:path');
const {execFileSync} = require('node:child_process');
const here = __dirname;
const publicNames = [
  'VERCEL', 'VERCEL_ENV', 'VERCEL_URL', 'VERCEL_PROJECT_ID', 'VERCEL_DEPLOYMENT_ID',
  'RAFII_A7A0_EXPECTED_PROJECT_ID', 'RAFII_A7A0_SOURCE_SHA',
  'RAFII_A7A0_APPLICATION_ID', 'RAFII_A7A0_PUBLIC_KEY_HEX', 'RAFII_A7A0_EXPECTED_ORIGIN'
];
const base = {};
for (const name of ['PATH', 'HOME', 'TMPDIR', 'LANG', 'LC_ALL']) {
  if (process.env[name] !== undefined) base[name] = process.env[name];
}
const context = {...base};
for (const name of publicNames) {
  if (process.env[name] !== undefined) context[name] = process.env[name];
}
const packaging = path.join(here, 'package_output.py');
execFileSync('python3', [packaging, '--check-context'], {env: context, stdio: 'inherit'});
// The builder gets no application values, OIDC tokens or hosted account credentials.
execFileSync(process.execPath, [path.join(here, 'build-archive.cjs')], {
  cwd: here, stdio: 'inherit',
  env: {...base, GITHUB_SHA: context.RAFII_A7A0_SOURCE_SHA,
    VERCEL_BUILDER_MODULES: process.env.VERCEL_BUILDER_MODULES || path.join(here, 'node_modules'),
    VERCEL_TELEMETRY_DISABLED: '1', DO_NOT_TRACK: '1'}
});
execFileSync('python3', [packaging,
  '--evidence', path.join(here, 'evidence'),
  '--output', path.join(here, '.vercel/output'),
  '--manifest', path.join(here, 'FROZEN-SOURCES.json')
], {cwd: here, env: context, stdio: 'inherit'});
