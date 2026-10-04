const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const source = fs.readFileSync(path.resolve(__dirname, '../src/components/motion/radio.tsx'), 'utf8');

test('custom radio buttons expose an accessible name', () => {
  assert.match(source, /'aria-label'\?: string/);
  assert.match(source, /aria-label=\{ariaLabel \?\? \(typeof label === 'string' \? label : undefined\)\}/);
});
