const test = require('node:test');
const assert = require('node:assert/strict');
const { readFileSync } = require('node:fs');
const { join } = require('node:path');
const { chooseNativeOption } = require('./native-select-picker.cjs');

test('native select chooses option value without clicking a hidden option', async () => {
  const events = [];
  const dialog = {
    getByRole(role, options) {
      assert.equal(role, 'combobox');
      assert.deepEqual(options, { name: 'Draft', exact: true });
      return {
        locator(tag) {
          assert.equal(tag, 'option');
          return {
            filter({ hasText }) {
              assert.equal(hasText, 'A small idea worth a closer look.');
              return {
                async getAttribute(key) {
                  assert.equal(key, 'value');
                  events.push('get-value');
                  return 'synthetic-draft-id';
                },
                async click() { throw Error('HTML option must never be clicked'); }
              };
            }
          };
        },
        async selectOption(value) {
          events.push('native-select');
          assert.equal(value, 'synthetic-draft-id');
        }
      };
    }
  };
  assert.equal(await chooseNativeOption(dialog, 'Draft', 'A small idea worth a closer look.'), 'synthetic-draft-id');
  assert.deepEqual(events, ['get-value', 'native-select']);
});

test('a missing native option value fails closed without selecting', async () => {
  const dialog = {
    getByRole() {
      return {
        locator() { return { filter() { return { getAttribute: async () => null }; } }; },
        selectOption() { throw Error('No selection permitted'); }
      };
    }
  };
  await assert.rejects(chooseNativeOption(dialog, 'Account', 'missing'), /option value/i);
});

test('Cloud E2E uses native selection for Draft and Account, custom click for Publish as', () => {
  const browser = readFileSync(join(__dirname, 'official-social-browser.cjs'), 'utf8');
  const dialog = readFileSync(join(__dirname, '../src/features/queue/schedule-dialog.tsx'), 'utf8');
  assert.match(dialog, /<NativeSelect id='schedule-draft'/);
  assert.match(dialog, /<NativeSelect id='schedule-channel'/);
  assert.match(browser, /chooseNativeOption\(composer,\s*'Draft'/);
  assert.match(browser, /chooseNativeOption\(composer,\s*'Account'/);
  assert.doesNotMatch(browser, /getByRole\('option'\)\.filter\([^;]+\.click\(\)/);
  assert.match(browser, /getByRole\('option',\s*\{name:'LinkedIn fixture member/);
});
