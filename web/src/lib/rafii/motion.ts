'use client';

/**
 * Rafii motion primitives (Design DNA v8 §18, §23.4; v9 addendum §2).
 *
 * One shared motion preference: the OS `prefers-reduced-motion` query or the app's own
 * setting (kept per browser under `rafii.motion`). Reduced motion cancels spatial and
 * decorative effects while logical state changes still complete. Every Web Animations API
 * helper here is interruptible: a new request cancels the previous one and completion
 * callbacks check their own ticket before touching the DOM.
 */

import { useCallback, useLayoutEffect, useRef, useSyncExternalStore, type RefObject } from 'react';

export const RAFII_EASE = {
  ui: [0.2, 0.8, 0.2, 1],
  soft: [0.22, 1, 0.36, 1],
  phone: [0.22, 0.78, 0.22, 1]
} as const;

export const RAFII_EASE_CSS = {
  ui: 'cubic-bezier(0.2, 0.8, 0.2, 1)',
  soft: 'cubic-bezier(0.22, 1, 0.36, 1)',
  phone: 'cubic-bezier(0.22, 0.78, 0.22, 1)'
} as const;

/** Reference timing roles in milliseconds. */
export const RAFII_TIME = {
  feedback: 200,
  tooltip: 180,
  view: 320,
  swap: 430,
  lens: 440,
  disclosure: 480,
  phone: 560
} as const;

const STORAGE_KEY = 'rafii.motion';
const EVENT = 'rafii-motion-change';
export type MotionSetting = 'system' | 'reduced' | 'full';

const QUERY = '(prefers-reduced-motion: reduce)';

function readSetting(): MotionSetting {
  if (typeof window === 'undefined') return 'system';
  try {
    const value = localStorage.getItem(STORAGE_KEY);
    return value === 'reduced' || value === 'full' ? value : 'system';
  } catch {
    return 'system';
  }
}

function systemReduced(): boolean {
  return typeof window !== 'undefined' && typeof window.matchMedia === 'function' && window.matchMedia(QUERY).matches;
}

/** Imperative check for Web Animations API code paths. */
export function motionAllowed(): boolean {
  if (typeof window === 'undefined') return false;
  const setting = readSetting();
  if (setting === 'reduced') return false;
  if (setting === 'full') return true;
  return !systemReduced();
}

export function setMotionSetting(setting: MotionSetting) {
  try {
    if (setting === 'system') localStorage.removeItem(STORAGE_KEY);
    else localStorage.setItem(STORAGE_KEY, setting);
  } catch {
    /* private mode: the choice lasts for this page only */
  }
  applyMotionAttribute();
  window.dispatchEvent(new Event(EVENT));
}

/** Mirrors the effective preference on <html data-motion> so CSS can respect the app setting. */
export function applyMotionAttribute() {
  if (typeof document === 'undefined') return;
  if (motionAllowed()) document.documentElement.removeAttribute('data-motion');
  else document.documentElement.setAttribute('data-motion', 'reduced');
}

function subscribe(callback: () => void) {
  const media = typeof window.matchMedia === 'function' ? window.matchMedia(QUERY) : null;
  media?.addEventListener('change', callback);
  window.addEventListener(EVENT, callback);
  window.addEventListener('storage', callback);
  return () => {
    media?.removeEventListener('change', callback);
    window.removeEventListener(EVENT, callback);
    window.removeEventListener('storage', callback);
  };
}

const snapshot = () => `${readSetting()}:${systemReduced() ? 'r' : 'f'}`;
const serverSnapshot = () => 'system:f';

/**
 * The shared motion preference. `reduced` is what components should obey; `setting` is the
 * person's explicit choice (system / reduced / full) for the preferences UI.
 */
export function useMotionPreference() {
  const value = useSyncExternalStore(subscribe, snapshot, serverSnapshot);
  const [setting, system] = value.split(':') as [MotionSetting, 'r' | 'f'];
  const reduced = setting === 'reduced' || (setting === 'system' && system === 'r');
  useLayoutEffect(() => {
    applyMotionAttribute();
  }, [value]);
  return { reduced, setting, setSetting: setMotionSetting };
}

/* -------------------------------------------------------------------------- */
/* Measured disclosure (DNA §18.4): animate between real heights, restore auto. */
/* -------------------------------------------------------------------------- */

const running = new WeakMap<Element, Animation[]>();

export function cancelAnimations(el: Element | null) {
  if (!el) return;
  const list = running.get(el);
  if (list) {
    list.forEach((a) => a.cancel());
    running.delete(el);
  }
}

/**
 * Opens or closes `el` by animating its height from the currently rendered value to the
 * measured target. The element must clip its overflow. Closed content becomes inert.
 */
export function animateHeight(el: HTMLElement, show: boolean, options: { enabled?: boolean; duration?: number; endHeight?: number | null } = {}) {
  const { enabled = true, duration = RAFII_TIME.disclosure, endHeight = null } = options;
  const before = el.getBoundingClientRect().height;
  cancelAnimations(el);
  el.style.height = show ? 'auto' : '0px';
  el.style.overflow = 'hidden';
  el.inert = !show;
  el.setAttribute('aria-hidden', String(!show));
  const after = endHeight ?? (show ? el.getBoundingClientRect().height : 0);
  if (!enabled || !motionAllowed() || typeof el.animate !== 'function' || Math.abs(before - after) < 0.5) {
    el.style.height = show ? 'auto' : '0px';
    return;
  }
  const animation = el.animate([{ height: `${before}px` }, { height: `${after}px` }], { duration, easing: RAFII_EASE_CSS.soft, fill: 'both' });
  const list = [animation];
  if (show && before < 10 && el.firstElementChild) {
    list.push(
      el.firstElementChild.animate([{ opacity: 0, transform: 'translateY(-7px)' }, { opacity: 1, transform: 'translateY(0)' }], {
        duration: 330,
        delay: 100,
        easing: RAFII_EASE_CSS.soft,
        fill: 'backwards'
      })
    );
  }
  running.set(el, list);
  animation.finished
    .catch(() => {})
    .then(() => {
      if (running.get(el) !== list) return;
      list.forEach((a) => a.cancel());
      el.style.height = show ? 'auto' : '0px';
      running.delete(el);
    });
}

/**
 * React binding for a measured disclosure. Attach `ref` to the clipping container; content
 * inside renders always (so it can be measured) and the container animates open/closed.
 * The first render applies the state without animation.
 */
export function useMeasuredDisclosure<T extends HTMLElement>(open: boolean, options: { duration?: number } = {}): RefObject<T | null> {
  const ref = useRef<T>(null);
  const first = useRef(true);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (first.current) {
      first.current = false;
      el.style.height = open ? 'auto' : '0px';
      el.style.overflow = 'hidden';
      el.inert = !open;
      el.setAttribute('aria-hidden', String(!open));
      return;
    }
    animateHeight(el, open, { duration: options.duration });
  }, [open, options.duration]);
  useLayoutEffect(() => () => cancelAnimations(ref.current), []);
  return ref;
}

/* -------------------------------------------------------------------------- */
/* Crossfade swap (DNA §18.3): keep the outgoing layer inert until the new one settles. */
/* -------------------------------------------------------------------------- */

/**
 * Prepares an inert snapshot of `host`'s current content so a new render can crossfade over
 * it. Returns a function that runs the animation once the incoming content is in place.
 */
export function beginSwap(host: HTMLElement, direction: 1 | -1 = 1, duration: number = RAFII_TIME.swap) {
  cancelAnimations(host);
  host.querySelectorAll<HTMLElement>('[data-swap-outgoing]').forEach((n) => n.remove());
  const current = host.querySelector<HTMLElement>('[data-swap-current]');
  if (!current || !motionAllowed() || typeof host.animate !== 'function' || host.getClientRects().length === 0) return null;
  const height = host.getBoundingClientRect().height;
  const outgoing = current.cloneNode(true) as HTMLElement;
  outgoing.removeAttribute('data-swap-current');
  outgoing.setAttribute('data-swap-outgoing', '');
  outgoing.inert = true;
  outgoing.setAttribute('aria-hidden', 'true');
  outgoing.querySelectorAll('[id]').forEach((n) => n.removeAttribute('id'));
  Object.assign(outgoing.style, { position: 'absolute', inset: '0 auto auto 0', width: '100%', pointerEvents: 'none', zIndex: '1' });
  return (incoming: HTMLElement) => {
    host.style.position = host.style.position || 'relative';
    host.style.overflow = 'hidden';
    host.append(outgoing);
    host.style.height = 'auto';
    const target = incoming.getBoundingClientRect().height;
    const opts: KeyframeAnimationOptions = { duration, easing: RAFII_EASE_CSS.soft, fill: 'both' };
    const list = [
      outgoing.animate([{ opacity: 1, transform: 'translateX(0)' }, { opacity: 0, transform: `translateX(${-direction * 18}px)` }], opts),
      incoming.animate([{ opacity: 0, transform: `translateX(${direction * 22}px)` }, { opacity: 1, transform: 'translateX(0)' }], opts),
      host.animate([{ height: `${height}px` }, { height: `${target}px` }], opts)
    ];
    running.set(host, list);
    Promise.all(list.map((a) => a.finished.catch(() => {}))).then(() => {
      if (running.get(host) !== list) return;
      outgoing.remove();
      list.forEach((a) => a.cancel());
      host.style.height = '';
      running.delete(host);
    });
  };
}

/**
 * Hook form of the crossfade: call `swap(direction)` right before changing the content key,
 * and render the live content inside an element marked `data-swap-current` within `hostRef`.
 */
export function useCrossfadeSwap<T extends HTMLElement>(hostRef: RefObject<T | null>) {
  const pending = useRef<((incoming: HTMLElement) => void) | null>(null);
  const swap = useCallback(
    (direction: 1 | -1 = 1) => {
      const host = hostRef.current;
      if (!host) return;
      pending.current = beginSwap(host, direction);
    },
    [hostRef]
  );
  const settle = useCallback(() => {
    const host = hostRef.current;
    const run = pending.current;
    pending.current = null;
    if (!host || !run) return;
    const incoming = host.querySelector<HTMLElement>('[data-swap-current]');
    if (incoming) run(incoming);
  }, [hostRef]);
  return { swap, settle };
}
