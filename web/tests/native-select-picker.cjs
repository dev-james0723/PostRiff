/** Select an actual HTML <option> through its owning <select>.
 * Playwright cannot click a hidden platform-native option. Reads never dispatch.
 */
const assert = require('node:assert/strict');

async function chooseNativeOption(dialog, name, text) {
  const control = dialog.getByRole('combobox', { name, exact: true });
  const value = await control.locator('option').filter({ hasText: text }).getAttribute('value');
  assert.ok(typeof value === 'string' && value !== '', 'Native option value is missing');
  await control.selectOption(value);
  return value;
}

module.exports = { chooseNativeOption };
