/**
 * Home wiring for chat attachments (chat-context SPEC §11.2, §4.9 item 8; PLAN S30), checked in the source: the idea
 * composer takes the chip row, the ＋ button and composed textarea handlers (⌘+Enter IME-guarded); estimate, quote and
 * submit carry the same chip fields; sources, templates and accounts route to the Context Pocket, this message's
 * template and destinations; the Expand dialog shares the handlers with an inline `@` list.
 *
 *   node --test web/tests/home-attachments-wiring.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const AGENT = path.join(__dirname, '..', 'src', 'features', 'agent');
const read = (...parts) => fs.readFileSync(path.join(AGENT, ...parts), 'utf8');
const composer = read('home', 'idea-composer.tsx');
const view = read('home-view.tsx');
const generation = read('home', 'use-home-generation.ts');
const expand = read('home', 'expanded-idea-dialog.tsx');
const library = read('content-library-dialog.tsx');

test('the idea composer takes the chip row, the ＋ button and composed handlers', () => {
  assert.match(composer, /attachmentsRow\?: ReactNode;/);
  assert.match(composer, /addButton\?: ReactNode;/);
  assert.match(composer, /textareaHandlers\?: TextareaHandlers;/);
  assert.match(composer, /if \(handlers\?\.onKeyDown\?\.\(event\)\) return;/, 'the list’s keys run first');
  assert.match(composer, /!isImeEvent\(event\) && !handlers\?\.composing\?\.\(event\)/, '⌘+Enter never fires mid-composition');
  assert.match(composer, /onInput=\{\(event\) => handlers\?\.onInput\?\.\(event\)\}/);
  assert.doesNotMatch(composer, /\{\.\.\.textareaHandlers\}/, 'handlers are composed, never spread');
  const context = composer.indexOf('Context\n');
  assert.ok(composer.indexOf('{addButton}') > context && context > 0, '＋ sits in the Context row');
});

test('estimate, quote and submit carry the same chip fields; answerAutomation is unchanged', () => {
  assert.match(generation, /\.\.\.\(request\.references\?\.length \? \{ references: request\.references \} : \{\}\)/);
  assert.match(generation, /\.\.\.\(request\.attachments\?\.length \? \{ attachments: request\.attachments \} : \{\}\)/);
  assert.match(view, /creditRequestFor\(quickStartPayload\(\{ text: text\.trim\(\),.*sourceIds: included, \.\.\.chipFields \}\)\)/);
  assert.match(view, /maxMilliCredits: creditMode \? maximum : null, \.\.\.chipFields \}, current\)/);
  assert.doesNotMatch(view, /answerAutomation\([^)]*chipFields/);
  assert.match(view, /!\(attachmentsOn && attachments\.blockers\.length\)/, 'Generate waits for uploads');
  assert.match(view, /attachments\.clearSent\(sent\)/);
});

test('Home routes sources, templates and accounts instead of making chips', () => {
  assert.match(view, /if \(item\.kind === 'source'\) \{\s*setIncluded/);
  assert.match(view, /if \(item\.kind === 'template'\) \{\s*setMessageTemplate/);
  assert.match(view, /destinations\.commit\(\{ accountIds: /);
  assert.match(view, /route: routeItem/);
  assert.match(view, /detail: messageTemplate \? 'This message only'/);
  assert.match(library, /Template for this message: \{messageTemplate\.name\}/);
  assert.match(library, />\s*Remove\s*</);
});

test('the Expand dialog shares the handlers, shows a compact chip strip and keeps the @ list inside', () => {
  assert.match(expand, /textareaHandlers\?: TextareaHandlers/);
  assert.match(expand, /onKeyDown=\{\(event\) => void handlers\?\.onKeyDown\?\.\(event\)\}/);
  assert.match(expand, /\{mentionList\}/);
  assert.match(expand, /\{chipStrip\}/);
  assert.match(view, /mentionList=\{dialog === 'expand' \? mentionList\(true\) : undefined\}/);
  assert.match(view, /\{dialog !== 'expand' && mentionList\(false\)\}/);
});
