/**
 * A small client renderer for node --test (not a test file itself; this repo has no jsdom and adds no test dependency).
 *
 * It runs function components exactly as written, with React's own element objects and React's own hook entry points, by
 * installing a hooks dispatcher of its own for the duration of each component call (state, reducer, ref, memo, callback,
 * effect, layout effect, id, context, external store). Host elements become plain nodes with a parent chain, and a fake
 * `document` tracks `activeElement` the way a browser does: `focus()` on a node that is not focusable or not connected does
 * nothing, and removing the focused node moves focus to <body>. Refs attach before effects run; effects run children first,
 * layout before passive; updates during render re-run that component; updates from handlers are batched. Events bubble
 * through host ancestors like React's synthetic events (`stopPropagation` stops them; `preventDefault` is recorded).
 *
 * `shallow(type)`: component types it rejects are kept as opaque elements (never called), so one component's own hooks and
 * effects can be tested without rendering its children; `findElement` searches those element trees.
 *
 *   const h = createHarness(React, { window: { matchMedia: () => ({ matches: true }) } });
 *   h.render(React.createElement(EditView, props));
 *   h.click(h.button('Cancel'));   h.keyDown(input, 'Escape');   h.document.activeElement
 *   h.cleanup();
 *
 * Not a browser: no layout, no CSS, no default actions beyond a submit button submitting its form. The real-browser checks
 * stay in agent-ui-e2e.
 */
'use strict';

const ELEMENT_TYPES = new Set([Symbol.for('react.transitional.element'), Symbol.for('react.element')]);
const CONTEXT = Symbol.for('react.context');
const PROVIDER = Symbol.for('react.provider');
const CONSUMER = Symbol.for('react.consumer');
const MEMO = Symbol.for('react.memo');
const FORWARD_REF = Symbol.for('react.forward_ref');
const PASS_THROUGH = new Set([Symbol.for('react.fragment'), Symbol.for('react.suspense'), Symbol.for('react.strict_mode'), Symbol.for('react.profiler')]);
const FOCUSABLE = new Set(['button', 'input', 'select', 'textarea']);
const MAX_PASSES = 50;

const isElement = (value) => !!value && typeof value === 'object' && ELEMENT_TYPES.has(value.$$typeof);

class FakeText {
  constructor(text) {
    this.nodeType = 3;
    this.text = String(text);
    this.parentNode = null;
  }
  get textContent() {
    return this.text;
  }
}

function matches(node, test) {
  if (!node || node.nodeType !== 1) return false;
  if (typeof test === 'function') return Boolean(test(node));
  const parsed = /^([a-z][a-z0-9-]*)?(?:\[([a-zA-Z_:][-a-zA-Z0-9_:.]*)(?:="([^"]*)")?\])?$/.exec(String(test));
  if (!parsed) throw new Error(`harness: unsupported selector ${test}`);
  const [, tag, attr, value] = parsed;
  if (tag && node.localName !== tag) return false;
  if (attr) {
    const actual = node.getAttribute(attr);
    if (actual === null) return false;
    if (value !== undefined && actual !== value) return false;
  }
  return true;
}

class FakeNode {
  constructor(doc, tag) {
    this.ownerDocument = doc;
    this.nodeType = 1;
    this.localName = tag;
    this.tagName = tag.toUpperCase();
    this.props = {};
    this.childNodes = [];
    this.parentNode = null;
    this.value = undefined;
    this.focusOptions = null;
  }
  get isConnected() {
    for (let node = this; node; node = node.parentNode) if (node === this.ownerDocument.body) return true;
    return false;
  }
  get disabled() {
    return Boolean(this.props.disabled);
  }
  get tabIndex() {
    if (typeof this.props.tabIndex === 'number') return this.props.tabIndex;
    return this.focusable() ? 0 : -1;
  }
  focusable() {
    if (FOCUSABLE.has(this.localName)) return !this.disabled;
    if (this.localName === 'a' && this.props.href) return true;
    return typeof this.props.tabIndex === 'number';
  }
  focus(options) {
    if (!this.isConnected || !this.focusable()) return;   // a browser ignores focus() on these
    this.ownerDocument.activeElement = this;
    this.focusOptions = options ?? null;
  }
  blur() {
    if (this.ownerDocument.activeElement === this) this.ownerDocument.activeElement = this.ownerDocument.body;
  }
  contains(other) {
    for (let node = other; node; node = node.parentNode) if (node === this) return true;
    return false;
  }
  getAttribute(name) {
    const key = name === 'class' ? 'className' : name === 'for' ? 'htmlFor' : name === 'tabindex' ? 'tabIndex' : name;
    const value = this.props[key];
    if (value === undefined || value === null || typeof value === 'function' || (typeof value === 'object')) return null;
    if (value === false && !/^(aria|data)-/.test(name)) return null;
    if (value === true && !/^(aria|data)-/.test(name)) return '';
    return String(value);
  }
  get textContent() {
    return this.childNodes.map((child) => child.textContent).join('');
  }
  matches(test) {
    return matches(this, test);
  }
  closest(test) {
    for (let node = this; node && node.nodeType === 1; node = node.parentNode) if (matches(node, test)) return node;
    return null;
  }
}

function createDocument() {
  const doc = { activeElement: null, visibilityState: 'visible', hidden: false, listeners: [] };
  doc.body = new FakeNode(doc, 'body');
  doc.documentElement = doc.body;
  doc.activeElement = doc.body;
  doc.addEventListener = (type, fn) => doc.listeners.push({ type, fn });
  doc.removeEventListener = (type, fn) => {
    doc.listeners = doc.listeners.filter((entry) => entry.type !== type || entry.fn !== fn);
  };
  return doc;
}

function createHarness(React, options = {}) {
  const internals = React.__CLIENT_INTERNALS_DO_NOT_USE_OR_WARN_USERS_THEY_CANNOT_UPGRADE;
  if (!internals || !('H' in internals)) throw new Error('harness: React client internals not found (React 19 expected)');
  const shallow = typeof options.shallow === 'function' ? options.shallow : null;
  const doc = createDocument();
  const container = new FakeNode(doc, 'div');
  container.parentNode = doc.body;
  doc.body.childNodes = [container];

  // The globals the components read (document always; window only when the test provides one), restored by cleanup().
  const saved = [];
  const install = (name, value) => {
    saved.push([name, Object.getOwnPropertyDescriptor(globalThis, name)]);
    Object.defineProperty(globalThis, name, { value, configurable: true, writable: true });
  };
  install('document', doc);
  if (options.window) install('window', { document: doc, ...options.window });

  let root = null;
  let rootElement = null;
  let rendering = null;
  let batching = 0;
  let working = false;
  let dirty = false;
  let ids = 0;
  let refChanges = [];

  // --- hooks ---------------------------------------------------------------------------------------------------------------
  function slot(make) {
    const inst = rendering;
    if (!inst) throw new Error('harness: a hook was called outside a component');
    const index = inst.hookIndex;
    inst.hookIndex += 1;
    if (inst.hooks.length <= index) inst.hooks.push(make());
    return inst.hooks[index];
  }
  const depsChanged = (prev, next) => !prev || !next || prev.length !== next.length || prev.some((value, i) => !Object.is(value, next[i]));
  function setHookState(inst, hook, next) {
    if (Object.is(hook.state, next)) return;
    hook.state = next;
    if (!inst.mounted) return;
    if (rendering === inst) {
      inst.renderAgain = true;
      return;
    }
    schedule();
  }
  function readContext(context) {
    for (let inst = rendering; inst; inst = inst.parent) if (inst.kind === 'provider' && inst.context === context) return inst.value;
    return context._currentValue;
  }
  function effect(kind, create, deps) {
    const inst = rendering;
    const hook = slot(() => ({ kind, deps: undefined, destroy: undefined, mountedOnce: false, queued: false, create: null, nextDeps: undefined }));
    if (!hook.mountedOnce || !deps || depsChanged(hook.deps, deps)) {
      hook.create = create;
      hook.nextDeps = deps;
      hook.queued = true;
      inst.hasQueued = true;
    }
  }
  const basicReducer = (state, action) => (typeof action === 'function' ? action(state) : action);
  const dispatcher = {
    readContext,
    useContext: readContext,
    use(usable) {
      if (usable && usable.$$typeof === CONTEXT) return readContext(usable);
      throw new Error('harness: use() of a promise is not supported');
    },
    useReducer(reducer, initialArg, init) {
      const inst = rendering;
      const hook = slot(() => ({ state: init ? init(initialArg) : initialArg, reducer, dispatch: null }));
      hook.reducer = reducer;
      if (!hook.dispatch) hook.dispatch = (action) => setHookState(inst, hook, hook.reducer(hook.state, action));
      return [hook.state, hook.dispatch];
    },
    useState(initial) {
      return dispatcher.useReducer(basicReducer, initial, typeof initial === 'function' ? (make) => make() : undefined);
    },
    useRef(initial) {
      return slot(() => ({ current: initial }));
    },
    useMemo(make, deps) {
      const hook = slot(() => ({ deps: undefined, value: undefined, ready: false }));
      if (!hook.ready || !deps || depsChanged(hook.deps, deps)) {
        hook.value = make();
        hook.deps = deps;
        hook.ready = true;
      }
      return hook.value;
    },
    useCallback(fn, deps) {
      return dispatcher.useMemo(() => fn, deps);
    },
    useEffect(create, deps) {
      effect('passive', create, deps);
    },
    useLayoutEffect(create, deps) {
      effect('layout', create, deps);
    },
    useInsertionEffect(create, deps) {
      effect('layout', create, deps);
    },
    useImperativeHandle(ref, make, deps) {
      effect('layout', () => {
        const value = make();
        if (typeof ref === 'function') {
          ref(value);
          return () => ref(null);
        }
        if (ref) {
          ref.current = value;
          return () => {
            ref.current = null;
          };
        }
        return undefined;
      }, deps);
    },
    useId() {
      return slot(() => ({ id: `«h${(ids += 1).toString(36)}»` })).id;
    },
    useSyncExternalStore(subscribe, getSnapshot) {
      const value = getSnapshot();
      const hook = slot(() => ({ value, getSnapshot }));
      hook.value = value;
      hook.getSnapshot = getSnapshot;
      effect('passive', () => {
        const check = () => {
          if (!Object.is(hook.getSnapshot(), hook.value)) schedule();
        };
        const unsubscribe = subscribe(check);
        check();
        return typeof unsubscribe === 'function' ? unsubscribe : undefined;
      }, [subscribe]);
      return value;
    },
    useTransition() {
      return [false, (fn) => fn()];
    },
    useDeferredValue(value) {
      return value;
    },
    useOptimistic(value) {
      return [value, () => undefined];
    },
    useDebugValue() {},
  };

  // --- reconciliation ------------------------------------------------------------------------------------------------------
  function kindOf(child) {
    if (typeof child === 'string' || typeof child === 'number' || typeof child === 'bigint') return { kind: 'text', type: 'text' };
    if (Array.isArray(child)) return { kind: 'fragment', type: 'array' };
    if (!isElement(child)) throw new Error(`harness: cannot render ${Object.prototype.toString.call(child)}`);
    const type = child.type;
    if (typeof type === 'string') return { kind: 'host', type };
    if (typeof type === 'function') {
      if (shallow && !shallow(type)) return { kind: 'opaque', type };
      if (type.prototype && type.prototype.isReactComponent) throw new Error(`harness: class component ${type.name || ''} (render it shallow)`);
      return { kind: 'component', type };
    }
    if (typeof type === 'symbol' && PASS_THROUGH.has(type)) return { kind: 'fragment', type };
    if (type && typeof type === 'object') {
      if (type.$$typeof === CONTEXT || type.$$typeof === PROVIDER) return { kind: 'provider', type };
      if (type.$$typeof === CONSUMER) return { kind: 'consumer', type };
      if (type.$$typeof === MEMO || type.$$typeof === FORWARD_REF) {
        const inner = type.$$typeof === MEMO ? type.type : type.render;
        if (shallow && typeof inner === 'function' && !shallow(inner)) return { kind: 'opaque', type };
        return { kind: type.$$typeof === MEMO ? 'memo' : 'forward', type };
      }
    }
    throw new Error(`harness: unsupported element type ${String(type && (type.displayName || type.name || type.$$typeof?.toString()))}`);
  }

  function newInstance(kind, type, key, parent) {
    return { kind, type, key, parent, hooks: [], hookIndex: 0, children: [], node: null, mounted: true, renderAgain: false, hasQueued: false,
      element: null, output: null, ref: undefined, context: null, value: undefined };
  }

  function reconcileChildren(parent, children, previous) {
    const list = Array.isArray(children) ? children : [children];
    const byKey = new Map(previous.map((inst) => [inst.key, inst]));
    const out = [];
    list.forEach((child, index) => {
      if (child === null || child === undefined || typeof child === 'boolean') return;
      const key = isElement(child) && child.key !== null && child.key !== undefined ? `k:${child.key}` : `i:${index}`;
      const prev = byKey.get(key);
      byKey.delete(key);
      out.push(reconcileOne(parent, child, prev, key));
    });
    for (const leftover of byKey.values()) unmount(leftover);
    return out;
  }

  function reconcileOne(parent, child, prev, key) {
    const { kind, type } = kindOf(child);
    let inst = prev;
    if (!inst || inst.kind !== kind || inst.type !== type) {
      if (inst) unmount(inst);
      inst = newInstance(kind, type, key, parent);
    }
    inst.parent = parent;
    switch (kind) {
      case 'text':
        if (!inst.node) inst.node = new FakeText(child);
        else inst.node.text = String(child);
        break;
      case 'fragment':
        inst.children = reconcileChildren(inst, Array.isArray(child) ? child : child.props.children, inst.children);
        break;
      case 'host':
        updateHost(inst, child);
        break;
      case 'component':
        renderComponent(inst, child.props, (props) => type(props));
        break;
      case 'memo':
        renderComponent(inst, child.props, (props) => (typeof type.type === 'function' ? type.type(props) : props.children));
        break;
      case 'forward':
        renderComponent(inst, child.props, (props) => type.render(props, props.ref ?? null));
        break;
      case 'provider':
        inst.context = type.$$typeof === PROVIDER ? type._context : type;
        inst.value = child.props.value;
        inst.children = reconcileChildren(inst, child.props.children, inst.children);
        break;
      case 'consumer': {
        const previous = rendering;
        rendering = inst;
        let output;
        try {
          output = child.props.children(readContext(type._context));
        } finally {
          rendering = previous;
        }
        inst.children = reconcileChildren(inst, output, inst.children);
        break;
      }
      case 'opaque':
        inst.element = child;
        break;
      default:
        break;
    }
    return inst;
  }

  function renderComponent(inst, props, call) {
    let output;
    let passes = 0;
    do {
      passes += 1;
      if (passes > MAX_PASSES) throw new Error('harness: too many re-renders during render');
      inst.renderAgain = false;
      inst.hookIndex = 0;
      const previousDispatcher = internals.H;
      const previous = rendering;
      internals.H = dispatcher;
      rendering = inst;
      try {
        output = call(props);
      } finally {
        internals.H = previousDispatcher;
        rendering = previous;
      }
    } while (inst.renderAgain);
    inst.output = output;
    inst.children = reconcileChildren(inst, output, inst.children);
  }

  function hostChildren(instances) {
    const out = [];
    for (const inst of instances) {
      if (inst.kind === 'host' || inst.kind === 'text') out.push(inst.node);
      else out.push(...hostChildren(inst.children));
    }
    return out;
  }

  function updateHost(inst, element) {
    if (!inst.node) inst.node = new FakeNode(doc, element.type);
    const node = inst.node;
    const props = element.props;
    node.props = props;
    if (Object.prototype.hasOwnProperty.call(props, 'value')) node.value = props.value;
    inst.children = reconcileChildren(inst, props.children, inst.children);
    node.childNodes = hostChildren(inst.children);
    for (const child of node.childNodes) child.parentNode = node;
    const ref = props.ref;
    if (ref !== inst.ref) {
      refChanges.push({ node, prev: inst.ref, next: ref });
      inst.ref = ref;
    }
  }

  function setRef(ref, value) {
    if (typeof ref === 'function') ref(value);
    else if (ref && typeof ref === 'object') ref.current = value;
  }

  function unmount(inst) {
    for (const child of inst.children) unmount(child);
    inst.mounted = false;
    for (const hook of inst.hooks) {
      if (hook && typeof hook.destroy === 'function') {
        const destroy = hook.destroy;
        hook.destroy = undefined;
        destroy();
      }
    }
    if (inst.kind === 'host' && inst.node) {
      if (inst.node.contains(doc.activeElement)) doc.activeElement = doc.body;   // removing the focused node: focus → <body>
      if (inst.ref) setRef(inst.ref, null);
      inst.node.parentNode = null;
    }
  }

  function runEffects(kind) {
    const visit = (inst) => {
      for (const child of inst.children) visit(child);
      if (!inst.hasQueued || !inst.mounted) return;
      let left = false;
      for (const hook of inst.hooks) {
        if (!hook || !hook.queued) continue;
        if (hook.kind !== kind) {
          left = true;
          continue;
        }
        hook.queued = false;
        if (typeof hook.destroy === 'function') hook.destroy();
        const result = hook.create();
        hook.destroy = typeof result === 'function' ? result : undefined;
        hook.deps = hook.nextDeps;
        hook.mountedOnce = true;
      }
      inst.hasQueued = left;
    };
    if (root) visit(root);
  }

  function perform() {
    if (working) {
      dirty = true;
      return;
    }
    working = true;
    try {
      let loops = 0;
      do {
        dirty = false;
        loops += 1;
        if (loops > MAX_PASSES) throw new Error('harness: updates did not settle');
        refChanges = [];
        if (rootElement === null) {
          if (root) unmount(root);
          root = null;
        } else {
          root = reconcileOne(null, rootElement, root, 'root');
        }
        container.childNodes = root ? hostChildren([root]) : [];
        for (const child of container.childNodes) child.parentNode = container;
        for (const change of refChanges) {
          if (change.prev) setRef(change.prev, null);
          if (change.next) setRef(change.next, change.node);
        }
        runEffects('layout');
        runEffects('passive');
      } while (dirty);
    } finally {
      working = false;
    }
  }

  function schedule() {
    if (working || batching) {
      dirty = true;
      return;
    }
    perform();
  }

  function act(fn) {
    batching += 1;
    let result;
    try {
      result = fn();
    } finally {
      batching -= 1;
    }
    if (!batching && dirty) perform();
    return result;
  }

  // --- events ------------------------------------------------------------------------------------------------------------
  function dispatch(node, handler, init = {}) {
    const native = { isComposing: Boolean(init.isComposing), keyCode: init.keyCode ?? 0, ...(init.nativeEvent || {}) };
    const event = {
      type: init.type || handler.slice(2).toLowerCase(), key: init.key, code: init.code, repeat: Boolean(init.repeat), shiftKey: Boolean(init.shiftKey),
      isComposing: native.isComposing, keyCode: native.keyCode, nativeEvent: native, target: node, currentTarget: null,
      defaultPrevented: false, propagationStopped: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
      stopPropagation() {
        this.propagationStopped = true;
      },
      isDefaultPrevented() {
        return this.defaultPrevented;
      },
      isPropagationStopped() {
        return this.propagationStopped;
      },
      persist() {},
    };
    act(() => {
      for (let current = node; current && current.nodeType === 1 && !event.propagationStopped; current = current.parentNode) {
        const fn = current.props && current.props[handler];
        if (typeof fn === 'function') {
          event.currentTarget = current;
          fn(event);
        }
      }
    });
    return event;
  }

  function hosts(from = container) {
    const out = [];
    const walk = (node) => {
      for (const child of node.childNodes) {
        if (child.nodeType !== 1) continue;
        out.push(child);
        walk(child);
      }
    };
    walk(from);
    return out;
  }

  function findElement(test) {
    const search = (element) => {
      if (Array.isArray(element)) {
        for (const item of element) {
          const found = search(item);
          if (found) return found;
        }
        return null;
      }
      if (!isElement(element)) return null;
      if (test(element)) return element;
      return search(element.props?.children);
    };
    const visit = (inst) => {
      if (inst.kind === 'opaque') {
        const found = search(inst.element);
        if (found) return found;
      }
      for (const child of inst.children) {
        const found = visit(child);
        if (found) return found;
      }
      return null;
    };
    return root ? visit(root) : null;
  }

  const api = {
    document: doc,
    container,
    act,
    render(element) {
      rootElement = element;
      act(() => {
        dirty = true;
      });
      return api;
    },
    unmount() {
      rootElement = null;
      act(() => {
        dirty = true;
      });
    },
    /** Unmount (effects clean up while the globals still exist), then restore the globals. */
    cleanup() {
      try {
        if (root) api.unmount();
      } finally {
        for (const [name, descriptor] of saved.reverse()) {
          if (descriptor) Object.defineProperty(globalThis, name, descriptor);
          else delete globalThis[name];
        }
        saved.length = 0;
      }
    },
    hosts,
    find: (test) => hosts().find((node) => matches(node, test)) ?? null,
    findAll: (test) => hosts().filter((node) => matches(node, test)),
    /** A button by its accessible name (aria-label, else its text). */
    button(name) {
      return hosts().find((node) => node.localName === 'button' && (node.getAttribute('aria-label') ?? node.textContent.trim()) === name) ?? null;
    },
    findElement,
    dispatch,
    click(node) {
      if (!node) throw new Error('harness: click on nothing');
      if (node.disabled) return null;   // a disabled control gets no click
      node.focus();                     // Chromium focuses a clicked button
      const event = dispatch(node, 'onClick', { type: 'click' });
      if (node.localName === 'button' && (node.props.type ?? 'submit') === 'submit' && !event.defaultPrevented) {
        const form = node.closest('form');
        if (form) dispatch(form, 'onSubmit', { type: 'submit' });
      }
      return event;
    },
    keyDown(node, key, init = {}) {
      return dispatch(node, 'onKeyDown', { ...init, key, type: 'keydown' });
    },
    type(node, text) {
      node.value = text;
      return dispatch(node, 'onChange', { type: 'change' });
    },
    submit(form) {
      return dispatch(form, 'onSubmit', { type: 'submit' });
    },
    compositionStart(node) {
      return dispatch(node, 'onCompositionStart', { type: 'compositionstart' });
    },
    compositionEnd(node) {
      return dispatch(node, 'onCompositionEnd', { type: 'compositionend' });
    },
  };
  return api;
}

module.exports = { createHarness };
