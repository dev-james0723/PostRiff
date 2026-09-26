/**
 * The `@` trigger and query (chat-context SPEC §4.3): when the list opens, where the query ends, and that a dismissed
 * anchor never reopens.
 *
 *   node --test web/tests/mention.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function load(file) {
  const source = fs.readFileSync(file, 'utf8');
  assert.doesNotMatch(source, /from '@\//);
  const { outputText } = ts.transpileModule(source, {
    fileName: file,
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 }
  });
  const mod = { exports: {} };
  new Function('require', 'module', 'exports', outputText)(require, mod, mod.exports);
  return mod.exports;
}
const M = load(path.join(__dirname, '..', 'src', 'features', 'agent', 'attachments', 'mention.ts'));
const typed = (value, data = value.slice(-1), inputType = 'insertText') =>
  M.triggerFrom(inputType, data, value, value.length);

test('opens after start, whitespace, CJK and punctuation', () => {
  assert.equal(typed('@'), 0);
  assert.equal(typed('Write like @'), 11);
  assert.equal(typed('改@'), 1);
  assert.equal(typed('用，@'), 2);
  assert.equal(typed('（@'), 1);
  assert.equal(typed('hello　＠'), 6);
  assert.equal(
    M.triggerFrom('insertCompositionText', '＠', '改＠', 2),
    1,
    'IME full-width at sign'
  );
});

test('never inside words, emails, paths, URLs or handles', () => {
  for (const value of [
    'name@',
    'mail_@',
    'x9@',
    'a/@',
    'a:@',
    'a.@',
    'threads.com/@',
    'https://x.com/@',
    'www.youtube.com/@'
  ]) {
    assert.equal(typed(value), null, value);
  }
});

test('never on paste, drop or replacement text', () => {
  for (const inputType of [
    'insertFromPaste',
    'insertFromDrop',
    'insertReplacementText',
    'deleteContentBackward'
  ]) {
    assert.equal(M.triggerFrom(inputType, '@', 'a @', 3), null, inputType);
  }
  assert.equal(
    M.triggerFrom('insertText', 'x', 'a @x', 4),
    null,
    'typing after an existing @ does not reopen'
  );
});

test('the query ends at whitespace, @, newlines, CJK or ASCII punctuation, or 40 code points', () => {
  assert.deepEqual(M.queryAt('改@帖子', 1, 4), { query: '帖子', ended: false });
  assert.deepEqual(M.queryAt('@spring_concert-2027.v2', 0, 23), {
    query: 'spring_concert-2027.v2',
    ended: false
  });
  for (const value of [
    '@spr ing',
    '@spr　x',
    '@spr@x',
    '@spr\nx',
    '@春，x',
    '@spr!x',
    '@spr,x',
    '@spr)x'
  ]) {
    assert.equal(M.queryAt(value, 0, value.length).ended, true, JSON.stringify(value));
  }
  const long = '@' + 'a'.repeat(41);
  assert.deepEqual(M.queryAt(long, 0, long.length), { query: 'a'.repeat(40), ended: true });
  assert.equal(
    M.queryAt('@' + '🎹'.repeat(40), 0, 81).ended,
    false,
    'code points, not UTF-16 units'
  );
});

test('the reducer: typing refilters, a terminator closes, a dismissed anchor never reopens', () => {
  let s = M.CLOSED;
  s = M.reduceMention(s, {
    type: 'input',
    inputType: 'insertText',
    data: '@',
    value: 'Hi @',
    caret: 4
  });
  assert.equal(s.anchor, 3);
  s = M.reduceMention(s, {
    type: 'input',
    inputType: 'insertCompositionText',
    data: 'spr',
    value: 'Hi @spr',
    caret: 7
  });
  assert.deepEqual([s.anchor, s.query], [3, 'spr']);
  s = M.reduceMention(s, { type: 'dismiss' });
  assert.equal(s.anchor, null);
  s = M.reduceMention(s, {
    type: 'input',
    inputType: 'insertText',
    data: 'i',
    value: 'Hi @spri',
    caret: 8
  });
  assert.equal(s.anchor, null, 'typing on does not reopen a dismissed anchor');
  s = M.reduceMention(s, {
    type: 'input',
    inputType: 'insertText',
    data: '@',
    value: 'Hi @spri @',
    caret: 10
  });
  assert.equal(s.anchor, 9, 'a new @ opens again');
  s = M.reduceMention(s, {
    type: 'input',
    inputType: 'insertText',
    data: ' ',
    value: 'Hi @spri @ ',
    caret: 11
  });
  assert.equal(s.anchor, null, 'whitespace ends the query and closes the list');
  let t = M.reduceMention(M.CLOSED, {
    type: 'input',
    inputType: 'insertText',
    data: '@',
    value: '@',
    caret: 1
  });
  t = M.reduceMention(t, { type: 'selection', value: '@', caret: 0 });
  assert.equal(t.anchor, null, 'moving the caret out closes it');
  t = M.reduceMention(
    M.reduceMention(M.CLOSED, {
      type: 'input',
      inputType: 'insertText',
      data: '@',
      value: '@',
      caret: 1
    }),
    { type: 'picked' }
  );
  assert.equal(t.anchor, null);
});
