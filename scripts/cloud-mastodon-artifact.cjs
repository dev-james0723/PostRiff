/** Cloud-only upload of an explicit synthetic evidence whitelist. */
'use strict';
const { lstatSync, readFileSync, writeFileSync, realpathSync } = require('node:fs');
const { resolve, dirname } = require('node:path');
const { createHash } = require('node:crypto');
const assert = require('node:assert/strict');
(async () => {
  assert.equal(process.platform, 'linux'); assert.ok(['true', '1'].includes(process.env.CI));
  const root = realpathSync(process.argv[2]), clientRoot = realpathSync(process.argv[3]);
  assert.ok(root.endsWith('/.jcb-artifacts/mastodon-browser'));
  const exitCode = Number(process.argv[4]); assert.ok(Number.isInteger(exitCode));
  const names = ['CLOUD-SYNTHETIC-browser.json', 'CLOUD-SYNTHETIC-failure.png',
    ...['channels', 'profile'].flatMap(surface => [1440, 390, 320].map(w => `CLOUD-SYNTHETIC-${surface}-${w}.png`)),
    ...['thread', 'images', 'audio', 'native'].flatMap(kind => [1440, 390, 320].map(w => `CLOUD-SYNTHETIC-queue-${kind}-${w}.png`))];
  const files = [], entries = [];
  for (const name of names) {
    const path = resolve(root, name); let stat;
    try { stat = lstatSync(path); } catch (error) { if (error.code === 'ENOENT') continue; throw error; }
    assert.ok(stat.isFile() && !stat.isSymbolicLink() && dirname(realpathSync(path)) === root && stat.size <= 1024 * 1024);
    files.push(path); entries.push({ name, bytes: stat.size, sha256: createHash('sha256').update(readFileSync(path)).digest('hex') });
  }
  if (exitCode === 0) {
    assert.equal(entries.length, 19);
    const proof = JSON.parse(readFileSync(resolve(root, 'CLOUD-SYNTHETIC-browser.json'), 'utf8'));
    assert.equal(proof.status, 'PASS'); assert.equal(proof.realMastodonAcceptance, false);
    assert.deepEqual(proof.queueChecks.map(row => row.width), [1440, 390, 320]);
  }
  assert.ok(entries.length > 0);
  const manifest = resolve(root, 'CLOUD-SYNTHETIC-manifest.json');
  writeFileSync(manifest, JSON.stringify({ execution: 'CLOUD SYNTHETIC', validationExitCode: exitCode, entries }, null, 2)); files.push(manifest);
  const { DefaultArtifactClient } = require(resolve(clientRoot, 'node_modules/@actions/artifact'));
  const result = await new DefaultArtifactClient().uploadArtifact('rafii-mastodon-synthetic-browser', files, root, { retentionDays: 7, compressionLevel: 0 });
  console.log(JSON.stringify({ marker: 'RAFII_MASTODON_ARTIFACT', id: result.id, bytes: result.size, files: files.length, validationExitCode: exitCode }));
})().catch(error => { console.error(JSON.stringify({ marker: 'RAFII_MASTODON_ARTIFACT_FAILED', errorType: error.name, code: error.code ?? null })); process.exitCode = 1; });
