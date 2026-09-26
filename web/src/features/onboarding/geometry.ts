import type { Rect } from './store';
import type { Placement } from './tours';

/**
 * Rectangle and card-placement helpers shared by the onboarding tour and Rafii's guided walkthroughs
 * (`features/rafii-guide`). Everything is in viewport pixels.
 */

/** The first element a list of selectors finds; an unsupported selector (older browsers and :has) falls through. */
export function queryFirst(selectors: string[], root: ParentNode = document): HTMLElement | null {
  for (const selector of selectors) {
    try {
      const el = root.querySelector<HTMLElement>(selector);
      if (el) return el;
    } catch {
      /* try the next selector */
    }
  }
  return null;
}

export function rectOf(el: Element, pad = 8): Rect {
  const r = el.getBoundingClientRect();
  return { x: r.left - pad, y: r.top - pad, w: r.width + pad * 2, h: r.height + pad * 2 };
}

export function sameRect(a: Rect | null, b: Rect | null) {
  if (!a || !b) return a === b;
  return Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5;
}

export const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

/**
 * Where a card of this size sits beside a rectangle: the preferred side first, then below, above, right and left.
 * `vw` may be narrower than the window (a docked panel takes the right edge).
 */
export function placeCard(rect: Rect, card: { w: number; h: number }, prefer: Placement | undefined, vw: number, vh: number, gap = 14, margin = 12) {
  const clampX = (x: number) => clamp(x, margin, vw - card.w - margin);
  const clampY = (y: number) => clamp(y, margin, vh - card.h - margin);
  const below = rect.y + rect.h + gap;
  const above = rect.y - gap - card.h;
  const order: Placement[] = prefer ? [prefer, 'bottom', 'top', 'right', 'left'] : ['bottom', 'top', 'right', 'left'];
  for (const side of order) {
    if (side === 'bottom' && below + card.h <= vh - margin) return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: below };
    if (side === 'top' && above >= margin) return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: above };
    if (side === 'right' && rect.x + rect.w + gap + card.w <= vw - margin) return { x: rect.x + rect.w + gap, y: clampY(rect.y) };
    if (side === 'left' && rect.x - gap - card.w >= margin) return { x: rect.x - gap - card.w, y: clampY(rect.y) };
  }
  // Nothing fits beside a target this large: sit inside the viewport, over its lower edge.
  return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: clampY(below) };
}
