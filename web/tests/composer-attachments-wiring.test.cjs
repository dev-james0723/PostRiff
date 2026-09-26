/**
 * Conversation wiring for chat attachments (chat-context SPEC §4.7, §11.2; PLAN S29), checked in the source:
 * the composer mounts the bar between the text and "Draft for", composes the textarea handlers, keeps its
 * accessible name, guards ⌘/Ctrl+Enter against IME and waits for uploads; the conversation sends the same chip
 * fields to the estimate and the turn, none with quick replies, clears only what went out, and shows the report.
 *
 *   node --test web/tests/composer-attachments-wiring.test.cjs
 */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const AGENT = path.join(__dirname, '..', 'src', 'features', 'agent');
const composer = fs.readFileSync(path.join(AGENT, 'composer.tsx'), 'utf8');
const view = fs.readFileSync(path.join(AGENT, 'conversation-view.tsx'), 'utf8');

test('the composer mounts the bar between the textarea and "Draft for"', () => {
  const textarea = composer.indexOf('<Textarea');
  const bar = composer.search(/<AttachmentBar\s+attachments=/);
  const draftFor = composer.indexOf("aria-label='Draft for'");
  assert.ok(textarea > 0 && bar > textarea && draftFor > bar, 'Textarea → AttachmentBar → Draft for');
  assert.match(composer, /<MentionList/);
  assert.match(composer, /aria-label='Message'/);
});

test('textarea handlers are composed explicitly, never spread over the composer’s own', () => {
  assert.match(composer, /onInput=\{\(event\) => attachments\?\.textareaProps\.onInput\(event\)\}/);
  assert.match(composer, /onSelect=\{\(event\) => attachments\?\.textareaProps\.onSelect\(event\)\}/);
  assert.match(composer, /onCompositionStart=\{\(\) => attachments\?\.textareaProps\.onCompositionStart\(\)\}/);
  assert.match(composer, /onCompositionEnd=\{\(\) => attachments\?\.textareaProps\.onCompositionEnd\(\)\}/);
  assert.doesNotMatch(composer, /\{\.\.\.attachments\.textareaProps\}/);
  assert.match(composer, /if \(attachments\?\.textareaProps\.onKeyDown\(event\)\) return;/, 'the list’s keys run first');
  assert.match(composer, /mentionTextareaProps\(/);
});

test('⌘/Ctrl+Enter respects IME, and send waits for uploads', () => {
  assert.match(composer, /!isImeEvent\(event\)\s*&&\s*!attachments\?\.ime\.composing\(event\)/);
  assert.match(composer, /!attachments\?\.blockers\.length/);
  assert.match(
    composer,
    /attachments\.blockerMessage\s*\?\?\s*attachments\.readingMessage\s*\?\?\s*attachments\.imageGenerationNotice/
  );
});

test('the conversation sends one set of chip fields to the estimate and the turn, none with quick replies', () => {
  assert.match(view, /\.\.\.\(chips && attachmentsOn \? attachments\.fields : \{\}\)/);
  assert.match(view, /const estimateRequest = creditRequestFor\(turnPayload\(text\.trim\(\)\)\)/);
  assert.match(view, /const withChips = override === undefined;/);
  assert.match(view, /turnPayload\(body, withChips\)/);
  assert.match(view, /onQuickReply=\{[^}]*sendTurn\(reply\)/);
  assert.match(view, /imageGeneration: imageRequested,/, 'image turns send no chips (the hook drops them)');
});

test('reads settle before sending, only sent chips are cleared, and the report shows under each answer', () => {
  assert.match(view, /await attachments\.settleReads\(\)/);
  assert.match(view, /attachments\.clearSent\(sent\)/);
  assert.match(view, /<UsedThisTime report=\{reportFrom\(\{ references: /);
  assert.match(view, /onDestination: pickDestination/);
  assert.match(view, /languages\.toggle\(\{ platform: channel\.platform as DraftPlatform, channelId: id \}\)/);
  assert.match(view, /models\.data\?\.attachments\?\.enabled/, 'the bar follows the server flag');
});
