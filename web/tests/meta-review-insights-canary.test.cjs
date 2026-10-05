const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const client = fs.readFileSync(path.resolve(__dirname, '../src/lib/api/client.ts'), 'utf8');
const card = fs.readFileSync(path.resolve(__dirname, '../src/features/channels/channel-card.tsx'), 'utf8');

test('Meta review canary uses the guarded native insights endpoint', () => {
  assert.match(client, /insightsCanary:/);
  assert.match(client, /channels\/\$\{encodeURIComponent\(id\)\}\/insights-canary/);
  assert.match(client, /confirmed: true/);
});

test('Meta review canary control stays hidden unless explicitly requested', () => {
  assert.match(card, /params\.get\('metaReview'\) === '1'/);
  assert.match(card, /channel\.platform === 'Instagram'/);
  assert.match(card, /channel\.capabilities\.analytics\?\.level === 'Direct'/);
  assert.match(card, /Run analytics test/);
});
