/** Actual FounderChat handlers and store; local hook doubles exercise a delayed session without a provider. */
const test = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');

function fixture() {
  let session;
  let stateIndex = 0;
  const calls = [];
  const text = 'Summarise the three things that need me today.';
  const react = {
    useCallback: (fn) => fn,
    useEffect: () => {},
    useMemo: (fn) => fn(),
    useRef: (value) => ({ current: value }),
    useState: (value) => [stateIndex++ === 0 ? text : value, () => {}],
    useSyncExternalStore: (_subscribe, read) => read()
  };
  function load(file, dependencies) {
    const source = fs.readFileSync(path.join(__dirname, '../src/features/founder/agent', file), 'utf8');
    const { outputText } = ts.transpileModule(source, {
      fileName: file, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX }
    });
    const mod = { exports: {} };
    new Function('require', 'module', 'exports', outputText)((name) => {
      assert.ok(name in dependencies, `unexpected dependency: ${name}`);
      return dependencies[name];
    }, mod, mod.exports);
    return mod.exports;
  }
  const store = load('store.ts', { react });
  const element = (type, props) => ({ type, props });
  const { FounderChat } = load('chat.tsx', {
    react,
    'react/jsx-runtime': { jsx: element, jsxs: element },
    'next/navigation': { usePathname: () => '/founder' },
    '@tabler/icons-react': { IconMicrophone: 'microphone' },
    '@/components/agents/loading-states/thinking-shimmer': { ThinkingShimmer: 'shimmer' },
    '@/components/icons': { Icons: new Proxy({}, { get: (_target, name) => String(name) }) },
    '@/components/ui/button': { Button: 'button' },
    '@/config/founder-nav': { FOUNDER_SECTIONS: { overview: { title: 'Overview' } }, isFounderSectionId: () => true },
    '@/features/founder/shell/founder-session': { useFounderSession: () => session },
    '@/features/site-agent/rafii-avatar': { RafiiAvatar: 'avatar' },
    '@/lib/founder/api': { randomKey: () => 'synthetic-session-turn' },
    '@/lib/founder/errors': { describeFounderError: (error) => String(error), isFounderApiError: () => false },
    '@/lib/founder/page-context': {
      currentFounderPageContext: (route, mode, environment) => ({ route, mode, environment }),
      sectionFromPathname: () => 'overview', useRegisteredFounderContext: () => null
    },
    '@/lib/ime': { createImeGuard: () => ({ composing: () => false }) },
    '@/lib/rafii/motion': { useMotionPreference: () => ({ reduced: true }) },
    '@/lib/utils': { cn: (...values) => values.filter(Boolean).join(' ') },
    './answer': { FounderAnswer: 'answer' },
    './prompts': { suggestedPrompts: () => ['Read today’s records'] },
    './store': store,
    './voice': { FounderVoice: 'voice' }
  });
  function render(status, environment, mode = 'demo') {
    session = { sessionStatus: status, environment, mode, retrySession: () => {}, api: {
      agentTurn: async (body) => {
        calls.push(body);
        return { data: { conversationId: 'synthetic-conversation', status: 'completed', result: { answerText: 'Actual fixture answer' } } };
      }
    } };
    stateIndex = 0;
    return FounderChat({ onClose: () => {} });
  }
  return { render, calls, store: store.founderPanelStore, text };
}

function find(node, predicate) {
  if (Array.isArray(node)) return node.flatMap((child) => find(child, predicate));
  if (!node || typeof node !== 'object') return [];
  return [...(predicate(node) ? [node] : []), ...find(node.props?.children, predicate)];
}
const tick = () => new Promise((resolve) => setImmediate(resolve));

for (const [status, environment] of [['loading', null], ['error', null], ['ready', null]]) {
  test(`${status}/${environment}: typed, Enter and suggested sends cannot start a turn before its environment is known`, async () => {
    const f = fixture();
    const view = f.render(status, environment);
    const send = find(view, (node) => node.props?.['aria-label'] === 'Send')[0];
    const suggestions = find(view, (node) => node.props?.['aria-label'] === 'Suggested questions')[0];
    assert.equal(send.props.disabled, true);
    assert.ok(find(suggestions, (node) => node.type === 'button').every((node) => node.props.disabled));
    find(view, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} });
    find(view, (node) => node.type === 'textarea')[0].props.onKeyDown({ key: 'Enter', nativeEvent: {}, preventDefault() {} });
    find(suggestions, (node) => node.type === 'button')[0].props.onClick();
    await tick();
    assert.equal(f.calls.length, 0);
    assert.deepEqual(f.store.thread('demo:unknown'), []);
    assert.deepEqual(f.store.get().busy, {});
  });
}

test('a delayed session preserves the typed question and sends once into the known Demo environment', async () => {
  const f = fixture();
  const pending = f.render('loading', null);
  find(pending, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} });
  await tick();
  const ready = f.render('ready', 'local');
  assert.equal(find(ready, (node) => node.props?.['aria-label'] === 'Send')[0].props.disabled, false);
  assert.equal(find(ready, (node) => node.type === 'textarea')[0].props.value, f.text);
  find(ready, (node) => node.type === 'form')[0].props.onSubmit({ preventDefault() {} });
  await tick();
  assert.equal(f.calls.length, 1);
  assert.equal(f.calls[0].mode, 'demo');
  assert.equal(f.calls[0].pageContext.environment, 'local');
  assert.equal(f.store.thread('demo:local').length, 2);
  assert.equal(f.store.thread('demo:local')[1].response.result.answerText, 'Actual fixture answer');
  assert.deepEqual(f.store.thread('demo:unknown'), []);
  assert.deepEqual(f.store.thread('live:local'), []);
  assert.equal(f.store.get().busy['demo:local'], false);
});
