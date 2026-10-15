/**
 * Guard the production acceptance control that bridges the already-secured Live rename endpoint into
 * the consolidated Founder UI. The backend remains the authority; this test prevents the UI from
 * silently dropping the only approved Live mutation again.
 *
 *   node --test web/tests/founder-live-rename-ui.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const file = path.join(__dirname, '..', 'src', 'features', 'founder', 'customers', 'workspaces-tab.tsx');
const source = fs.readFileSync(file, 'utf8');

test('Live workspace rename is visible only for server-approved rows and uses the guarded mutation hook', () => {
  assert.match(source, /mode === 'live'/);
  assert.match(source, /row\.original\.renameAllowed === true/);
  assert.match(source, /useRenameLiveWorkspace/);
  assert.match(source, /Rename approved test workspace/);
  assert.match(source, /exact, expiring rename grant/);
});

test('the acceptance dialog keeps original-name restoration explicit and blocks a no-op save', () => {
  assert.match(source, /Original name:/);
  assert.match(source, /restore the original name after verification/i);
  assert.match(source, /trimmedName !== originalName/);
  assert.match(source, /editingRevision !== null/);
});
