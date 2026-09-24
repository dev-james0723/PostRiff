/**
 * Framework-free rules for the phone preview deck (Design DNA v8 §17.2–17.3; prototype `phone-motion.js`
 * and `swipe.js`): which items sit on stage and where, how a switch travels, and when a pointer gesture
 * counts as a swipe. No DOM or React here, so `preview-deck.test.cjs` runs it under plain node.
 */

export type DeckRole = 'active' | 'left' | 'right' | 'exit';

export type DeckPose = {
  transform: string;
  opacity: number;
};

/** A pose as a Web Animations keyframe. */
export function keyframe(next: DeckPose): Record<string, string | number> {
  return { transform: next.transform, opacity: next.opacity };
}

/** The approved phone switch: 560ms on the phone curve (mirrors `RAFII_TIME.phone` / `RAFII_EASE_CSS.phone`). */
export const PHONE_TRANSITION_MS = 560;
export const PHONE_EASING = 'cubic-bezier(0.22, 0.78, 0.22, 1)';

/** Resting poses: the active phone centred and opaque, neighbours turned away at ±65%, an outgoing layer fading left. */
export const POSES: Record<DeckRole, DeckPose> = {
  active: { transform: 'translateX(0%) rotateY(0deg) scale(1)', opacity: 1 },
  left: { transform: 'translateX(-65%) rotateY(14deg) scale(0.83)', opacity: 0.2 },
  right: { transform: 'translateX(65%) rotateY(-14deg) scale(0.83)', opacity: 0.2 },
  exit: { transform: 'translateX(-38%) rotateY(7deg) scale(0.9)', opacity: 0 }
};

export function pose(role: DeckRole): DeckPose {
  return POSES[role];
}

/** Where a phone that was not on stage starts when it becomes active: just off centre, on the side it arrives from. */
export function entryPose(direction: 1 | -1): DeckPose {
  return { transform: `translateX(${direction * 24}%) rotateY(${-direction * 6}deg) scale(0.94)`, opacity: 0 };
}

/** Keys in order, without repeats or blanks. */
export function uniqueKeys(keys: readonly string[]): string[] {
  const seen = new Set<string>();
  const list: string[] = [];
  for (const key of keys) {
    if (!key || seen.has(key)) continue;
    seen.add(key);
    list.push(key);
  }
  return list;
}

function ring(keys: readonly string[], activeKey: string): string[] {
  const list = uniqueKeys(keys);
  // An active key the list does not know is shown on its own, ahead of the rest.
  if (!list.includes(activeKey)) list.unshift(activeKey);
  return list;
}

export interface StageLayer {
  key: string;
  role: Exclude<DeckRole, 'exit'>;
}

/**
 * What the stage shows for `activeKey`: the active phone, a left neighbour once there are two items and a
 * right neighbour from three. The list wraps, so the first item's left neighbour is the last item.
 */
export function stageLayers(keys: readonly string[], activeKey: string): StageLayer[] {
  const list = ring(keys, activeKey);
  const position = list.indexOf(activeKey);
  const layers: StageLayer[] = [{ key: activeKey, role: 'active' }];
  if (list.length > 1) layers.push({ key: list[(position - 1 + list.length) % list.length], role: 'left' });
  if (list.length > 2) layers.push({ key: list[(position + 1) % list.length], role: 'right' });
  return layers;
}

export interface MountedLayer {
  key: string;
  role: DeckRole;
}

/**
 * Everything mounted on stage: the layers for `activeKey` plus outgoing keys still finishing a transition
 * (role `exit`), in the deck's own order so nodes never move between switches. Keys no longer in the deck
 * are dropped at once.
 */
export function mountedLayers(keys: readonly string[], activeKey: string, retained: readonly string[]): MountedLayer[] {
  const list = ring(keys, activeKey);
  const roles = new Map<string, DeckRole>(stageLayers(list, activeKey).map((layer) => [layer.key, layer.role]));
  for (const key of retained) if (!roles.has(key) && list.includes(key)) roles.set(key, 'exit');
  return list.filter((key) => roles.has(key)).map((key) => ({ key, role: roles.get(key) as DeckRole }));
}

/**
 * Which way a switch travels: `1` when `toKey` is ahead of `fromKey` the short way round the ring (the new
 * phone arrives from the right), `-1` when it is behind. A first switch, or one from an unknown key, travels forward.
 */
export function switchDirection(keys: readonly string[], fromKey: string | null, toKey: string): 1 | -1 {
  const list = ring(keys, toKey);
  const from = fromKey === null ? -1 : list.indexOf(fromKey);
  if (from < 0) return 1;
  const to = list.indexOf(toKey);
  return (to - from + list.length) % list.length <= list.length / 2 ? 1 : -1;
}

/** The key `delta` steps away round the ring; the same key when there is nowhere to go. */
export function stepKey(keys: readonly string[], activeKey: string, delta: number): string {
  const list = uniqueKeys(keys);
  if (list.length < 2) return activeKey;
  const index = Math.max(0, list.indexOf(activeKey));
  const step = ((Math.trunc(delta) % list.length) + list.length) % list.length;
  return list[(index + step) % list.length];
}

/** Stacking on stage: the active phone in front, the phone it replaced behind it, everything else at the back. */
export function layerZIndex(role: DeckRole, outgoing: boolean): number {
  return role === 'active' ? 3 : outgoing ? 2 : 1;
}

/** Gesture thresholds, as tuned in the prototype. */
export const SWIPE = {
  /** Travel before the gesture commits to an axis. */
  axisLock: 10,
  /** Sideways travel must beat vertical travel by this ratio, when the axis locks and again on release. */
  ratio: 1.3,
  /** Travel that always counts. */
  distance: 42,
  /** Shorter travel counts when it was quick. */
  quickDistance: 26,
  /** Pixels per millisecond that make a short swipe quick. */
  quickSpeed: 0.45,
  /** A click this soon after a swipe is the gesture's own release, not a tap. */
  clickSuppressMs: 300,
  /** Drag feedback: the stage follows a twelfth of the travel, at most this far. */
  maxOffset: 22,
  offsetFactor: 0.12
} as const;

export type SwipeAxis = 'x' | 'y';

/** The axis a gesture commits to once it has travelled far enough, or null while it is still ambiguous. */
export function lockAxis(dx: number, dy: number): SwipeAxis | null {
  const across = Math.abs(dx);
  const along = Math.abs(dy);
  if (along > SWIPE.axisLock && along > across) return 'y';
  if (across > SWIPE.axisLock && across > along * SWIPE.ratio) return 'x';
  return null;
}

export interface SwipeRelease {
  dx: number;
  dy: number;
  /** Milliseconds between pointer down and release. */
  elapsed: number;
  axis: SwipeAxis | null;
  /** The browser or a second finger took the pointer away. */
  cancelled?: boolean;
  /** A second pointer was down at some point during the gesture. */
  blocked?: boolean;
}

/** Whether a released gesture changes the preview: sideways, decisive, and either long enough or quick enough. */
export function acceptSwipe({ dx, dy, elapsed, axis, cancelled = false, blocked = false }: SwipeRelease): boolean {
  if (cancelled || blocked || axis !== 'x') return false;
  const across = Math.abs(dx);
  if (across <= Math.abs(dy) * SWIPE.ratio) return false;
  const ms = Math.max(1, elapsed);
  return across >= SWIPE.distance || (across >= SWIPE.quickDistance && across / ms > SWIPE.quickSpeed);
}

/** A swipe to the left asks for the next item; to the right, the previous one. */
export function swipeDirection(dx: number): 1 | -1 {
  return dx < 0 ? 1 : -1;
}

/** How far the stage follows the finger, in pixels. */
export function dragOffset(dx: number): number {
  return Math.max(-SWIPE.maxOffset, Math.min(SWIPE.maxOffset, dx * SWIPE.offsetFactor));
}
