/**
 * Render harness for journey components (not a test file): real component code, real copy/format/views, with test
 * doubles of exactly two seams — lane C's OpenUI facade (reactive store + streaming flag) and lane D's bridge context
 * (query status + action bridge that records requests). Rendering is react-dom/server (no DOM); interaction checks call
 * the handlers captured during render, which are the same closures a click would run.
 */
const path = require('node:path');
const { SRC, createLoader, pkg } = require('./_load.cjs');

const GENUI = path.join(SRC, 'features/agent/generative-ui');

function makeEnvironment({ streaming = false, store = {}, manifestActions = [], writes = true, statuses = {} } = {}) {
  const env = {
    streaming,
    store: new Map(Object.entries(store)),
    sets: [],
    requests: [],
    statuses: { ...statuses },
    actionState: { phase: 'idle', request: null, activation: null, result: null, error: null },
  };
  const actions = new Map(manifestActions.map((a) => [a.actionId, a]));
  const listeners = new Set();
  env.actionBridge = {
    writesEnabled: (id) => writes && actions.has(id),
    binding: (id) => actions.get(id),
    request: (request) => env.requests.push(request),
    confirm: async () => null,
    cancel: () => undefined,
    state: () => env.actionState,
    subscribe: (l) => (listeners.add(l), () => listeners.delete(l)),
    dispose: () => undefined,
  };
  env.queryBridge = {
    toolProvider: () => null,
    read: async () => {
      throw new Error('journey components never read directly in these tests');
    },
    status: (name) => env.statuses[name],
    subscribe: () => () => undefined,
    setActive: () => undefined,
    invalidate: () => undefined,
    dispose: () => undefined,
  };
  const openui = {
    useIsStreaming: () => env.streaming,
    useStateField: (name, value) => {
      if (value && typeof value === 'object' && value.__reactive === 'assign') {
        return { name, value: env.store.get(value.target), setValue: (v) => env.sets.push([value.target, v]), isReactive: true };
      }
      return { name, value: env.store.has(name) ? env.store.get(name) : value, setValue: (v) => env.sets.push([name, v]), isReactive: false };
    },
  };
  const context = {
    useRafiiActionBridge: () => env.actionBridge,
    useRafiiQueryBridge: () => env.queryBridge,
    useRafiiActionState: () => env.actionState,
    useBindingStatus: (name) => env.statuses[name],
    useUiBridges: () => ({ query: env.queryBridge, action: env.actionBridge, onContinue: () => undefined }),
    UiBridgesProvider: ({ children }) => children,
  };
  // The app Button, recording its props so a test can run the exact click handler a person would trigger.
  env.buttons = [];
  const button = {
    Button: (props) => {
      env.buttons.push(props);
      const React = pkg('react');
      return React.createElement('button', { type: props.type ?? 'button', disabled: props.disabled, 'aria-busy': props['aria-busy'] }, props.children);
    },
  };
  env.selections = [];
  const selection = { useRecordSelection: () => (listId, items, visible) => env.selections.push({ listId, items, visible }) };
  const loader = createLoader({
    stubs: {
      [path.join(GENUI, 'state/selection')]: selection,
      [path.join(GENUI, 'core/openui')]: openui,
      [path.join(GENUI, 'bridges/context')]: context,
      [path.join(SRC, 'components/ui/button')]: button,
    },
  });
  env.load = (rel) => loader.loadPath(path.join(GENUI, rel));
  return env;
}

/** `$var` passed to a reactive prop, as OpenUI evaluates it. */
const bound = (target) => ({ __reactive: 'assign', target, expr: { k: 'Ref', n: '$value' } });

/** Render one journey component inside lane C's real locale context (locale: 'en' | 'zh-Hant-HK' | 'zh-Hans-CN' | …). */
function render(env, Component, props, { locale = 'en', timeZone = 'Asia/Hong_Kong', statementId = 's1' } = {}) {
  const React = pkg('react');
  const { renderToStaticMarkup } = pkg('react-dom/server');
  const { GenUiLocaleProvider, createGenUiLocale } = env.load('core/locale');
  const element = React.createElement(
    GenUiLocaleProvider,
    { value: createGenUiLocale({ locale, timeZone }) },
    React.createElement(Component, { props, renderNode: () => null, statementId }),
  );
  return renderToStaticMarkup(element);
}

/** UiQueryResultV1 envelope. */
function envelope(state, data, extra = {}) {
  return {
    state,
    data,
    asOf: '2026-10-08T14:00:00Z',
    sourceRefs: [],
    revision: '7',
    nextCursor: null,
    coverage: { known: null, total: null, note: null },
    warnings: [],
    ...extra,
  };
}

/** Visible text of static markup (tags removed, entities decoded, whitespace collapsed). */
function textOf(html) {
  return html
    .replace(/<[^>]+>/g, ' ')
    .replace(/&amp;/g, '&')
    .replace(/&lt;/g, '<')
    .replace(/&gt;/g, '>')
    .replace(/&quot;/g, '"')
    .replace(/&#x27;/g, "'")
    .replace(/\s+/g, ' ')
    .trim();
}

module.exports = { makeEnvironment, bound, render, envelope, textOf, GENUI };
