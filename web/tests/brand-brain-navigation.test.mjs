import test from 'node:test';
import assert from 'node:assert/strict';
import { departureHref } from '../src/features/workspace/brand/brain-navigation.ts';

test('unsaved writing navigation guard only proposes a sanitized same-origin route departure', () => {
  const here = 'https://rafii.example/app/workspace/brand';
  assert.equal(departureHref('/app/ideas?q=plan#draft', here), '/app/ideas?q=plan#draft');
  assert.equal(departureHref('#samples', here), null);
  assert.equal(departureHref('?section=voice', here), null);
  assert.equal(departureHref('https://elsewhere.example/app', here), null);
  assert.equal(departureHref('javascript:alert(1)', here), null);
  assert.equal(departureHref('/app/ideas', here, '_blank'), null);
  assert.equal(departureHref('/export.zip', here, '', true), null);
});
