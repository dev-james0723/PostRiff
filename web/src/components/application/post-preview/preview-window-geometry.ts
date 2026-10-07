/** Viewport coordinates only. No DOM, publishing data or persisted workspace state. */
export interface Point { x: number; y: number }
export interface Rect extends Point { width: number; height: number }
export interface WindowRequest extends Point { width: number }
export const WINDOW_PRESETS = { S: 240, M: 300, L: 360 } as const;
export const WINDOW_CHROME = 216;
export const WINDOW_INSET = 42;
const finite = (value: number, fallback: number) => Number.isFinite(value) ? value : fallback;
const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), Math.max(min, max));

export function phoneScale(width: number): number {
  return Math.max(0.1, (finite(width, 300) - WINDOW_INSET) / 393);
}

/** Header coordinates and VisualViewport offsets share layout-viewport CSS pixels. */
export function viewportBounds(viewport: Rect, headerBottom = 64): Rect {
  const x = finite(viewport.x, 0) + 12;
  const bottom = finite(viewport.y, 0) + Math.max(1, finite(viewport.height, 1)) - 12;
  const y = Math.min(Math.max(finite(viewport.y, 0), finite(headerBottom, 64)) + 12, Math.max(finite(viewport.y, 0), bottom - 44));
  return { x, y, width: Math.max(1, finite(viewport.width, 1) - 24), height: Math.max(1, bottom - y) };
}

export function fitWindow(request: WindowRequest, bounds: Rect): Rect {
  // A short keyboard viewport scrolls the body instead of shrinking the controls.
  const heightLimitedWidth = Math.max(220, (bounds.height - WINDOW_CHROME) * 393 / 852 + WINDOW_INSET);
  const maxWidth = Math.max(1, Math.min(360, bounds.width, heightLimitedWidth));
  const width = clamp(finite(request.width, 300), Math.min(220, maxWidth), maxWidth);
  const height = Math.min(bounds.height, phoneScale(width) * 852 + WINDOW_CHROME);
  return {
    x: clamp(finite(request.x, bounds.x), bounds.x, bounds.x + bounds.width - width),
    y: clamp(finite(request.y, bounds.y), bounds.y, bounds.y + bounds.height - height),
    width, height
  };
}

export function dockWindow(slot: Rect, requestedWidth: number, bounds: Rect): Rect {
  const top = clamp(slot.y, bounds.y, bounds.y + Math.max(0, bounds.height - 44));
  const dockBounds = { ...bounds, y: top, height: bounds.y + bounds.height - top };
  const size = fitWindow({ x: slot.x, y: top, width: Math.min(requestedWidth, Math.max(1, slot.width)) }, dockBounds);
  return fitWindow({ x: slot.x + Math.max(0, (slot.width - size.width) / 2), y: top, width: size.width }, dockBounds);
}

export function containsPoint(rect: Rect, point: Point): boolean {
  return rect.width > 0 && rect.height > 0 && point.x >= rect.x && point.x <= rect.x + rect.width && point.y >= rect.y && point.y <= rect.y + rect.height;
}
