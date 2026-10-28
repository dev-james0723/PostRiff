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
  assert.match(composer, /onInput=\{\(event\) => \{ handlers\?\.onInput\?\.\(event\); updateText\(event\); \}\}/, 'native input keeps the attachment handler first, then adopts controlled text');
  assert.doesNotMatch(composer, /\{\.\.\.textareaHandlers\}/, 'handlers are composed, never spread');
  const context = composer.indexOf('Context\n');
  assert.ok(composer.indexOf('{addButton}') > context && context > 0, '＋ sits in the Context row');
});

test('Home mounts the shared slash menu and agent commands open a real Agent Runtime conversation', () => {
  assert.match(composer, /<SlashCommandMenu/);
  assert.match(composer, /slash\.onPick\(command, args, pick\)/);
  assert.match(view, /const slash = parseSlash\(text\.trim\(\)\)/);
  assert.match(view, /currentSlash\?\.command\.kind === 'agent'/);
  assert.match(view, /await agent\.api\.turn\(workspaceId/);
  assert.match(view, /command: commandPayload\(currentSlash\)/);
  assert.match(view, /label: slash \? 'Run command'/);
  assert.match(view, /router\.push\(`\/app\/agent\/\$\{encodeURIComponent\(result\.conversationId\)\}`\)/);
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


// Replay the actual components' composed handlers without a DOM. The cloud
// connections browser separately covers React's value tracker and real Home UI.
function composerField(component) {
  const ts = require('typescript');
  const file = path.join(AGENT, 'home', component);
  const source = fs.readFileSync(file, 'utf8');
  const jsx = (type, props) => ({type, props});
  const React = {useRef: value => ({current: value}), useState: value => [value, () => {}],
    useId: () => 'input-regression', useCallback: fn => fn, forwardRef: fn => fn};
  const mod = {exports: {}};
  const imports = {
    react: React, 'react/jsx-runtime': {jsx, jsxs: jsx},
    '@/components/icons': {Icons: new Proxy({}, {get: (_, key) => key})},
    '@/components/ui/button': {Button: 'button'},
    '@/components/rafii': new Proxy({}, {get: (_, key) => key}),
    '@/lib/utils': {cn: (...values) => values.filter(Boolean).join(' ')},
    '@/lib/ime': {isImeEvent: event => Boolean(event.isComposing || event.nativeEvent?.isComposing || event.keyCode === 229 || event.nativeEvent?.keyCode === 229)},
    '@/features/rafii-commands/command-menu': {SlashCommandMenu: 'slash-menu'},
    './idea-composer': {IDEA_MAX: 20000}
  };
  const code = ts.transpileModule(source, {fileName: file, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX
  }}).outputText;
  new Function('require', 'module', 'exports', code)(name => {
    assert.ok(Object.hasOwn(imports, name), `unexpected component dependency ${name}`);
    return imports[name];
  }, mod, mod.exports);
  const render = component === 'idea-composer.tsx' ? mod.exports.IdeaComposer : mod.exports.ExpandedIdeaDialog;
  const calls = [], attachments = [];
  const handlers = {onInput: () => {attachments.push('input'); calls.push('attachment');},
    onCompositionStart: () => attachments.push('composition-start'), onCompositionEnd: () => attachments.push('composition-end')};
  const tree = render({value: '', onChange: value => calls.push(value), placeholder: '',
    onExpand() {}, contextCount: 0, onOpenContext() {}, contentType: {}, channels: {},
    generate: {disabled: false, onClick: () => calls.push('generate')}, open: true, onOpenChange() {}, textareaHandlers: handlers}, null);
  const find = node => Array.isArray(node) ? node.map(find).find(Boolean)
    : node && (node.type === 'textarea' ? node.props : find(node.props?.children));
  return {field: find(tree), calls, attachments};
}

for (const component of ['idea-composer.tsx', 'expanded-idea-dialog.tsx']) {
  test(`${component}: native input preserves exact text, composes attachments and reports one edit across both React handlers`, () => {
    const {field, calls, attachments} = composerField(component);
    assert.ok(field, 'test the actual component textarea');
    const text = '  原文 café e\u0301 👩🏽‍💻\n\nkeep  spaces\t\n  ';
    const nativeEvent = {};
    const event = {currentTarget: {value: text, selectionStart: text.length}, nativeEvent};
    field.onInput(event);
    assert.deepEqual(calls, ['attachment', text]);
    field.onChange(event);
    assert.deepEqual(calls, ['attachment', text], 'one native event produces one text callback');
    field.onChange({currentTarget: {value: text + 'typed', selectionStart: text.length + 5}, nativeEvent: {}});
    assert.equal(calls.at(-1), text + 'typed', 'ordinary onChange remains functional');
    field.onCompositionStart(); field.onCompositionEnd();
    assert.deepEqual(attachments, ['input', 'composition-start', 'composition-end']);
    if (component === 'idea-composer.tsx') {
      field.onKeyDown({key: 'Enter', metaKey: true, nativeEvent: {isComposing: true}, preventDefault() {throw new Error('IME submit prevented at the wrong layer');}});
      assert.equal(calls.includes('generate'), false, 'IME commit cannot generate');
    }
  });
}
