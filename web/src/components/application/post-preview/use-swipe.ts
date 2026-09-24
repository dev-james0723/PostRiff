'use client';

import { useEffect, useRef, type RefObject } from 'react';
import { motionAllowed as sharedMotionAllowed } from '@/lib/rafii/motion';
import { capturePointer } from '@/lib/touch';
import { acceptSwipe, dragOffset, lockAxis, SWIPE, swipeDirection, type SwipeAxis } from './preview-deck-core';

export interface SwipeOptions {
  /** Called once per accepted swipe: `1` for a swipe to the left (next item), `-1` for a swipe to the right (previous). */
  onSwipe: (direction: 1 | -1) => void;
  /** Off while there is nothing to swipe to; nothing is bound then. Default true. */
  enabled?: boolean;
  /** Drag feedback (`--swipe-offset`) runs only while motion is allowed; defaults to the shared Rafii predicate. */
  motionAllowed?: () => boolean;
}

interface Gesture {
  id: number;
  x: number;
  y: number;
  started: number;
  axis: SwipeAxis | null;
}

/** Controls keep their own clicks and drags; a swipe never starts on them. */
const INTERACTIVE = 'button, a, input, textarea, select, [contenteditable="true"]';

/**
 * Whether the gesture started inside something that scrolls sideways on its own (a media carousel, a strip):
 * that region keeps its drag, and a swipe there would page through photos and switch phones at once.
 */
function insideSidewaysScroller(target: EventTarget | null, host: HTMLElement) {
  let node = target instanceof Element ? target : null;
  while (node && node !== host) {
    if (node instanceof HTMLElement && node.scrollWidth > node.clientWidth + 1) {
      const overflow = getComputedStyle(node).overflowX;
      if (overflow === 'auto' || overflow === 'scroll') return true;
    }
    node = node.parentElement;
  }
  return false;
}

/**
 * Pointer-first swipe recogniser for a preview stage (DNA §17.3, §19.5; prototype `swipe.js`). A sideways
 * swipe changes the item; vertical movement stays with the browser (give the host `touch-action: pan-y
 * pinch-zoom`); small, diagonal, cancelled and multi-touch gestures do nothing. While the finger travels
 * sideways the host carries `data-swipe="dragging"` and `--swipe-offset` (at most ±22px) for the stage to
 * follow, and the click that ends an accepted swipe is swallowed so nothing under the finger activates.
 */
export function useSwipe<T extends HTMLElement>(ref: RefObject<T | null>, { onSwipe, enabled = true, motionAllowed = sharedMotionAllowed }: SwipeOptions) {
  const latest = useRef({ onSwipe, motionAllowed });
  useEffect(() => {
    latest.current = { onSwipe, motionAllowed };
  });

  useEffect(() => {
    const host = ref.current;
    if (!host || !enabled) return;
    let gesture: Gesture | null = null;
    let blocked = false;
    let suppressUntil = 0;
    const pointers = new Set<number>();

    const reset = () => {
      gesture = null;
      delete host.dataset.swipe;
      host.style.removeProperty('--swipe-offset');
    };

    const down = (event: PointerEvent) => {
      pointers.add(event.pointerId);
      if (pointers.size > 1) {
        // A second finger means a pinch or a rest, never a swipe, until every pointer is up again.
        blocked = true;
        reset();
        return;
      }
      if (blocked || event.isPrimary === false || (event.pointerType === 'mouse' && event.button !== 0)) return;
      const target = event.target;
      if (target instanceof Element && (target.closest(INTERACTIVE) || insideSidewaysScroller(target, host))) return;
      gesture = { id: event.pointerId, x: event.clientX, y: event.clientY, started: performance.now(), axis: null };
    };

    const move = (event: PointerEvent) => {
      const current = gesture;
      if (!current || current.id !== event.pointerId || blocked) return;
      const dx = event.clientX - current.x;
      const dy = event.clientY - current.y;
      if (!current.axis) {
        const axis = lockAxis(dx, dy);
        if (axis === 'y') {
          // Reading: the browser scrolls, the deck stays put.
          reset();
          return;
        }
        if (axis === 'x') {
          current.axis = 'x';
          capturePointer(host, event.pointerId);
        }
      }
      if (current.axis !== 'x') return;
      if (event.cancelable) event.preventDefault();
      host.dataset.swipe = 'dragging';
      if (latest.current.motionAllowed()) host.style.setProperty('--swipe-offset', `${dragOffset(dx)}px`);
    };

    const end = (event: PointerEvent, cancelled: boolean) => {
      pointers.delete(event.pointerId);
      const current = gesture;
      if (current?.id === event.pointerId) {
        const dx = event.clientX - current.x;
        const dy = event.clientY - current.y;
        const accepted = acceptSwipe({ dx, dy, elapsed: performance.now() - current.started, axis: current.axis, cancelled, blocked });
        reset();
        if (accepted) {
          suppressUntil = performance.now() + SWIPE.clickSuppressMs;
          latest.current.onSwipe(swipeDirection(dx));
        }
      }
      if (pointers.size === 0) blocked = false;
    };
    const up = (event: PointerEvent) => end(event, false);
    const cancel = (event: PointerEvent) => end(event, true);
    const lost = (event: PointerEvent) => {
      if (event.target === host && gesture?.id === event.pointerId) reset();
    };
    const click = (event: MouseEvent) => {
      if (performance.now() < suppressUntil) {
        event.preventDefault();
        event.stopImmediatePropagation();
      }
    };
    const dragStart = (event: DragEvent) => event.preventDefault();
    const blur = () => {
      pointers.clear();
      blocked = false;
      reset();
    };

    host.addEventListener('pointerdown', down);
    host.addEventListener('pointermove', move, { passive: false });
    host.addEventListener('pointerup', up);
    host.addEventListener('pointercancel', cancel);
    host.addEventListener('lostpointercapture', lost);
    host.addEventListener('click', click, true);
    host.addEventListener('dragstart', dragStart);
    window.addEventListener('blur', blur);
    return () => {
      host.removeEventListener('pointerdown', down);
      host.removeEventListener('pointermove', move);
      host.removeEventListener('pointerup', up);
      host.removeEventListener('pointercancel', cancel);
      host.removeEventListener('lostpointercapture', lost);
      host.removeEventListener('click', click, true);
      host.removeEventListener('dragstart', dragStart);
      window.removeEventListener('blur', blur);
      reset();
    };
  }, [ref, enabled]);
}
