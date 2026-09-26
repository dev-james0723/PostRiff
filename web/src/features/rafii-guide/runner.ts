/**
 * Runs one walkthrough (Contract 5) against the live page. The overlay supplies the senses and hands (`RunnerIO`):
 * this file decides what happens in which order.
 *
 * - The guide's page opens first, and each target is waited for (a sheet animating in, a page loading its data).
 * - A step whose target never shows is skipped when optional; otherwise the guide says so and stops.
 * - `click` presses only elements `isGuideSafe` accepts, after a visible pause; anything else becomes the person's turn.
 * - `await-click` waits for the person's own click; `point` and `await-visible` wait for Next.
 * - If the lit part of the page closes (the person cancelled a sheet), the guide says so and stops.
 * - It ends with a closing caption. Stop, Escape and leaving the page abort it (`io.signal`).
 */
import { isGuideSafe, pathOf, type Guide, type GuideAction, type GuidePlacement } from './guides';

export interface GuideView {
  phase: 'opening' | 'finding' | 'step' | 'done' | 'stopped';
  index: number;
  total: number;
  text: string;
  /** The person does this step themselves. */
  yourTurn: boolean;
  /** The card's button beside Stop. */
  button: 'next' | 'done' | 'close' | null;
  placement?: GuidePlacement;
}

export interface RunnerIO {
  signal: AbortSignal;
  reduced(): boolean;
  pathname(): string;
  titleOf(path: string): string;
  open(route: string): void;
  /** The page the guide means to be on; arriving anywhere else stops it. */
  expect(path: string): void;
  show(view: GuideView): void;
  /** Light this element and keep following it (null: nothing lit). */
  light(el: HTMLElement | null): void;
  glide(el: HTMLElement): Promise<void>;
  /** The press animation before a click. */
  press(): Promise<void>;
  /** Resolves when the person presses the card's Next, Done or Close. */
  next(): Promise<void>;
}

const ROUTE_MS = 12_000;
/** The first target on a page that just opened: its data may still be loading. */
const FIRST_FIND_MS = 10_000;
/** A target that appears after a click (a sheet opening, a request finishing). */
const AFTER_ACTION_FIND_MS = 10_000;
const FIND_MS = 6_000;
/** `await-visible` waits for the person (an upload finishing). */
const VISIBLE_MS = 120_000;
/** How long a lit target may be gone before the guide gives up. */
const LOST_MS = 1_500;
const CLICK_PAUSE_MS = 450;
const AFTER_CLICK_MS = 380;
const DONE_MS = 9_000;
const STOPPED_MS = 7_000;

export const NOT_FOUND = 'I couldn’t find this part of the page, so I stopped here. It may need a permission you don’t have.';
export const LOST = 'That part of the page closed, so I stopped.';
const YOUR_TURN = 'Press this yourself to go on.';

export function sleep(ms: number, signal: AbortSignal): Promise<void> {
  return new Promise((resolve) => {
    if (signal.aborted) return resolve();
    const timer = setTimeout(done, ms);
    function done() {
      clearTimeout(timer);
      signal.removeEventListener('abort', done);
      resolve();
    }
    signal.addEventListener('abort', done);
  });
}

/** Resolves with the first truthy answer of `check`, re-asked on DOM changes and on a timer; null on timeout or abort. */
export function until<T>(check: () => T | null | undefined | false, options: { timeout: number; signal: AbortSignal; interval?: number }): Promise<T | null> {
  const { timeout, signal, interval = 120 } = options;
  return new Promise((resolve) => {
    let finished = false;
    let frame = 0;
    const observer = typeof MutationObserver === 'function' ? new MutationObserver(schedule) : null;
    const timer = setInterval(test, interval);
    const limit = setTimeout(() => finish(null), timeout);
    function finish(value: T | null) {
      if (finished) return;
      finished = true;
      clearInterval(timer);
      clearTimeout(limit);
      if (frame) cancelAnimationFrame(frame);
      observer?.disconnect();
      signal.removeEventListener('abort', onAbort);
      resolve(value);
    }
    function onAbort() {
      finish(null);
    }
    function test() {
      if (finished) return;
      if (signal.aborted) return finish(null);
      const value = check();
      if (value) finish(value);
    }
    // Animations change attributes every frame: answer at most once a frame.
    function schedule() {
      if (frame || finished) return;
      frame = requestAnimationFrame(() => {
        frame = 0;
        test();
      });
    }
    signal.addEventListener('abort', onAbort);
    observer?.observe(document.body, { childList: true, subtree: true, attributes: true });
    test();
  });
}

/** Rendered with a size and not hidden by CSS (a fading-in sheet counts as shown). */
export function isShown(el: Element): boolean {
  if (!el.isConnected) return false;
  const box = el.getBoundingClientRect();
  if (box.width < 1 || box.height < 1) return false;
  if ('checkVisibility' in el && typeof el.checkVisibility === 'function') return el.checkVisibility({ checkVisibilityCSS: true });
  return getComputedStyle(el).visibility !== 'hidden';
}

/** The first element on screen that a list of selectors finds. */
export function findVisible(selectors: readonly string[]): HTMLElement | null {
  for (const selector of selectors) {
    let found: NodeListOf<HTMLElement>;
    try {
      found = document.querySelectorAll<HTMLElement>(selector);
    } catch {
      continue;
    }
    for (const el of found) if (isShown(el)) return el;
  }
  return null;
}

export function isDisabled(el: Element): boolean {
  return el.matches(':disabled') || el.getAttribute('aria-disabled') === 'true' || el.hasAttribute('data-disabled');
}

/** The element itself while it is still on screen, else what the selectors find now (React may have replaced it). */
function current(el: HTMLElement, selectors: readonly string[]): HTMLElement | null {
  return el.isConnected && isShown(el) ? el : findVisible(selectors);
}

/** Scroll the target into view (past the sticky header), then wait for the scroll to settle. */
async function bringIntoView(el: HTMLElement, io: RunnerIO) {
  const box = el.getBoundingClientRect();
  const height = window.innerHeight;
  if (box.top >= 72 && box.bottom <= height - 24 && box.left >= 0 && box.right <= window.innerWidth) return;
  el.scrollIntoView({ block: box.height > height * 0.6 ? 'start' : 'center', inline: 'nearest', behavior: io.reduced() ? 'auto' : 'smooth' });
  let last = el.getBoundingClientRect().top;
  for (let i = 0; i < 18 && !io.signal.aborted; i += 1) {
    await sleep(50, io.signal);
    const top = el.getBoundingClientRect().top;
    if (Math.abs(top - last) < 0.5 && i > 1) return;
    last = top;
  }
}

/**
 * Hold a step until it is finished: Next pressed (`next`), or the person's own click on the target (`click`).
 * Resolves `lost` when the target has been gone for a moment, and `aborted` when the guide stopped.
 */
function hold(first: HTMLElement, selectors: readonly string[], io: RunnerIO, mode: 'next' | 'click'): Promise<'done' | 'lost' | 'aborted'> {
  return new Promise((resolve) => {
    let target = first;
    let missingSince = 0;
    let finished = false;
    const finish = (outcome: 'done' | 'lost' | 'aborted') => {
      if (finished) return;
      finished = true;
      clearInterval(timer);
      document.removeEventListener('click', onClick, true);
      io.signal.removeEventListener('abort', onAbort);
      resolve(outcome);
    };
    const onAbort = () => finish('aborted');
    // Capture phase: the click is seen before the page reacts to it (a sheet closing, a link leaving the site).
    const onClick = (event: MouseEvent) => {
      if (event.target instanceof Node && target.isConnected && target.contains(event.target)) finish('done');
    };
    const timer = setInterval(() => {
      const now = current(target, selectors);
      if (now) {
        missingSince = 0;
        if (now !== target) {
          target = now;
          io.light(now);
        }
        return;
      }
      if (!missingSince) missingSince = Date.now();
      else if (Date.now() - missingSince > LOST_MS) finish('lost');
    }, 250);
    if (io.signal.aborted) return finish('aborted');
    io.signal.addEventListener('abort', onAbort);
    if (mode === 'click') document.addEventListener('click', onClick, true);
    else void io.next().then(() => finish('done'));
  });
}

async function stopWith(io: RunnerIO, index: number, total: number, text: string) {
  io.light(null);
  io.show({ phase: 'stopped', index, total, text, yourTurn: false, button: 'close' });
  await Promise.race([io.next(), sleep(STOPPED_MS, io.signal)]);
}

function findTimeout(action: GuideAction, arrived: boolean, previous: GuideAction | null): number {
  if (action === 'await-visible') return VISIBLE_MS;
  if (arrived) return FIRST_FIND_MS;
  if (previous === 'click' || previous === 'await-click') return AFTER_ACTION_FIND_MS;
  return FIND_MS;
}

export async function runGuide(guide: Guide, io: RunnerIO): Promise<void> {
  const { signal } = io;
  const total = guide.steps.length;
  let previous: GuideAction | null = null;
  let caption = '';
  for (let index = 0; index < total; index += 1) {
    if (signal.aborted) return;
    const step = guide.steps[index];
    const route = step.route ?? guide.route;
    const path = pathOf(route);
    io.expect(path);
    let arrived = index === 0;
    if (io.pathname() !== path) {
      io.light(null);
      io.show({ phase: 'opening', index, total, text: `Opening ${io.titleOf(path)}…`, yourTurn: false, button: null });
      io.open(route);
      const opened = await until(() => io.pathname() === path, { timeout: ROUTE_MS, signal });
      if (signal.aborted) return;
      if (!opened) return stopWith(io, index, total, `I couldn’t open ${io.titleOf(path)}, so I stopped.`);
      arrived = true;
    }

    const yourTurn = step.action === 'await-click';
    // An optional step may be skipped, so its words wait until its target is really there.
    const waiting = step.optional && step.action !== 'await-visible' ? caption || step.say : step.say;
    io.show({ phase: 'finding', index, total, text: waiting, yourTurn: waiting === step.say && yourTurn, button: null, placement: step.placement });
    const found = await until(() => findVisible(step.target), { timeout: findTimeout(step.action, arrived, previous), signal });
    if (signal.aborted) return;
    if (!found) {
      if (step.optional) {
        previous = step.action;
        continue;
      }
      return stopWith(io, index, total, NOT_FOUND);
    }

    await bringIntoView(found, io);
    if (signal.aborted) return;
    let el = current(found, step.target);
    if (!el) return stopWith(io, index, total, LOST);
    caption = step.say;
    io.light(el);
    io.show({ phase: 'step', index, total, text: step.say, yourTurn, button: null, placement: step.placement });
    await io.glide(el);
    if (signal.aborted) return;

    if (step.action === 'point' || step.action === 'await-visible') {
      io.show({ phase: 'step', index, total, text: step.say, yourTurn: false, button: 'next', placement: step.placement });
      const outcome = await hold(el, step.target, io, 'next');
      if (outcome === 'aborted') return;
      if (outcome === 'lost') return stopWith(io, index, total, LOST);
    } else {
      let theirs = step.action === 'await-click';
      if (step.action === 'click') {
        await sleep(CLICK_PAUSE_MS, signal);
        if (signal.aborted) return;
        const now = current(el, step.target);
        if (!now) return stopWith(io, index, total, LOST);
        if (now !== el) {
          // The page drew it again elsewhere (loading finished): follow it before pressing.
          el = now;
          io.light(el);
          await io.glide(el);
          if (signal.aborted) return;
        }
        if (isGuideSafe(el) && !isDisabled(el)) {
          await io.press();
          if (signal.aborted) return;
          el.click();
        } else {
          // Never clicked for the person: it isn't marked safe (or can't be pressed yet), so it is their turn.
          theirs = true;
          caption = YOUR_TURN;
          io.show({ phase: 'step', index, total, text: YOUR_TURN, yourTurn: true, button: null, placement: step.placement });
        }
      }
      if (theirs) {
        const outcome = await hold(el, step.target, io, 'click');
        if (outcome === 'aborted') return;
        if (outcome === 'lost') return stopWith(io, index, total, LOST);
      }
      await sleep(AFTER_CLICK_MS, signal);
    }
    previous = step.action;
  }
  if (signal.aborted) return;
  io.light(null);
  io.show({ phase: 'done', index: total - 1, total, text: guide.done, yourTurn: false, button: 'done' });
  await Promise.race([io.next(), sleep(DONE_MS, signal)]);
}
