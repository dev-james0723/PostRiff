/**
 * The ghost cursor's path: where it aims inside a target, how long a glide takes and the gentle curve it follows.
 * Pure viewport maths with no imports, so the tests load it directly.
 */

export interface Point {
  x: number;
  y: number;
}

export interface Box {
  left: number;
  top: number;
  width: number;
  height: number;
}

/** A glide takes 600–900 ms, a little longer the further it goes. */
export function glideDuration(distance: number): number {
  return Math.round(Math.min(900, Math.max(600, 560 + Math.abs(distance) * 0.35)));
}

/**
 * Where the cursor's tip rests on a target, the way a person aims: near the middle of a control, and near the
 * top-left corner (its title) of a large region.
 */
export function anchorOf(box: Box): Point {
  const large = box.width > 360 || box.height > 160;
  if (large) return { x: box.left + Math.min(56, box.width / 2), y: box.top + Math.min(30, box.height / 2) };
  return { x: box.left + box.width * 0.5, y: box.top + Math.min(box.height * 0.6, Math.max(box.height - 6, box.height / 2)) };
}

/**
 * A point on a quadratic curve from `from` to `to` at progress `t` (0–1). The control point sits beside the
 * midpoint, bowed upward on sideways moves, so the path reads as a hand moving a mouse rather than a straight slide.
 */
export function curvePoint(from: Point, to: Point, t: number, bend = 0.18): Point {
  const dx = to.x - from.x;
  const dy = to.y - from.y;
  const distance = Math.hypot(dx, dy);
  if (distance < 1) return { x: to.x, y: to.y };
  let nx = dy / distance;
  let ny = -dx / distance;
  if (ny > 0) {
    nx = -nx;
    ny = -ny;
  }
  const offset = Math.min(140, distance * bend);
  const cx = from.x + dx / 2 + nx * offset;
  const cy = from.y + dy / 2 + ny * offset;
  const p = Math.min(1, Math.max(0, t));
  const u = 1 - p;
  return { x: u * u * from.x + 2 * u * p * cx + p * p * to.x, y: u * u * from.y + 2 * u * p * cy + p * p * to.y };
}
