/**
 * The web kit groups native-currency metrics by currency (the server refuses them otherwise). This keeps the kit's list
 * (src/features/founder/customers/kit/metric-policy.ts) equal to the catalog, including slice catalogs in metrics.d.
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const pack = path.resolve(__dirname, '../../src/rafii_control/pack/catalogs');

function catalog() {
  const rows = JSON.parse(fs.readFileSync(path.join(pack, 'metrics.json'), 'utf8'));
  const extra = path.join(pack, 'metrics.d');
  if (fs.existsSync(extra)) for (const name of fs.readdirSync(extra).filter((file) => file.endsWith('.json')).sort()) rows.push(...JSON.parse(fs.readFileSync(path.join(extra, name), 'utf8')));
  const byId = new Map();
  for (const row of rows) if (!byId.has(row.id) || row.status === 'activated_v1') byId.set(row.id, row);
  return byId;
}

test('the kit lists exactly the catalog metrics that keep currencies separate', () => {
  const source = fs.readFileSync(path.resolve(__dirname, '../src/features/founder/customers/kit/metric-policy.ts'), 'utf8');
  const listed = [...source.matchAll(/^\s+'([a-z0-9_]+)',?$/gm)].map((match) => match[1]).sort();
  const expected = [...catalog().values()].filter((row) => row.currency_policy === 'native_currency_separate').map((row) => row.id).sort();
  assert.deepEqual(listed, expected);
});
