/**
 * Active work time for Time back (docs/raffi-time-back/ENGINEERING.md §7), kept in memory and sent only as a
 * cumulative number of seconds. A person counts as active while the page is visible and they pressed a key,
 * pointed, touched, scrolled or focused within the last 75 seconds. Which key, where, on what element, and any
 * text are never read. Writing that runs in the background counts only while the person is still interacting.
 *
 * Pure (no DOM, no React) so the rules are testable; `use-active-work-timer.ts` wires it to the page.
 */

export const IDLE_MS = 75_000;
/** A cumulative heartbeat at most this often (the server lets a beat add no more than the time since the last). */
export const HEARTBEAT_MS = 45_000;
/** Events that mean "someone is here", listened to passively; their details are never read. */
export const ACTIVITY_EVENTS = ['keydown', 'pointerdown', 'pointermove', 'wheel', 'scroll', 'touchstart', 'focus'] as const;

/** Bounded workflow keys the server accepts (`time_savings.WORKFLOW_KEY`). */
export type WorkflowPrefix = 'conversation' | 'variant' | 'automation';
const WORKFLOW_ID = /^[A-Za-z0-9_-]{1,64}$/;

/** `variant:<id>`, or null when the id would not pass the server's bound (then nothing is measured). */
export function workflowKey(prefix: WorkflowPrefix, id: string | null | undefined): string | null {
  return id && WORKFLOW_ID.test(id) ? `${prefix}:${id}` : null;
}

/** A random, per-mount key: heartbeats from one mount are one session; nothing about the person is in it. */
export function newSessionKey(random: () => string = () => crypto.randomUUID()): string {
  return random().replace(/[^A-Za-z0-9_-]/g, '').slice(0, 64).padEnd(16, '0');
}

export class ActiveTimeTracker {
  private activeMs = 0;
  private lastTick: number;
  private lastActivity = Number.NEGATIVE_INFINITY;
  private visible: boolean;

  constructor(now: number, visible: boolean) {
    this.lastTick = now;
    this.visible = visible;
  }

  /** Credit time up to `now`: only while visible, and only within the idle window after the last activity. */
  advance(now: number) {
    if (now <= this.lastTick) return;
    if (this.visible) {
      const until = Math.min(now, this.lastActivity + IDLE_MS);
      if (until > this.lastTick) this.activeMs += until - this.lastTick;
    }
    this.lastTick = now;
  }

  /** Someone did something on the visible page. */
  activity(now: number) {
    this.advance(now);
    if (this.visible) this.lastActivity = Math.max(this.lastActivity, now);
  }

  /** Hiding the page ends the active window; coming back counts again from the next activity (a focus counts). */
  visibility(visible: boolean, now: number) {
    this.advance(now);
    this.visible = visible;
    if (!visible) this.lastActivity = Number.NEGATIVE_INFINITY;
  }

  /** Whole active seconds so far. */
  seconds(now: number) {
    this.advance(now);
    return Math.floor(this.activeMs / 1000);
  }
}
