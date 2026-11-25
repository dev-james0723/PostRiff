/**
 * ScrollReveal's hidden and shown states and its transition, as data.
 *
 * The hidden state never depends on the reduced-motion preference. The server can't know that preference, so it always
 * renders the full hidden state (offset and blur); a browser that rendered a different one would be a hydration
 * mismatch, which React leaves unrepaired: the server's `filter: blur(…)` and `transform` then stay on the content after
 * the reveal has faded it in. That left the Pricing FAQ blurred for people who turned on Reduce motion. With reduced
 * motion the reveal only fades; the offset and the blur are dropped at once instead of animating.
 */
export interface RevealOptions<E> {
  /** Slide distance in px before reveal. */
  y: number;
  /** Enter blur in px. */
  blur: number;
  /** Reveal duration in seconds. */
  duration: number;
  delay: number;
  ease: E;
}

export function revealStates<E>(reduce: boolean, { y, blur, duration, delay, ease }: RevealOptions<E>) {
  const hidden = { opacity: 0, y, filter: `blur(${blur}px)` };
  // PostRiff: drop the filter once settled; a lingering `blur(0px)` keeps a compositing layer and
  // makes the wrapper the containing block for fixed-position children.
  const shown = { opacity: 1, y: 0, filter: 'blur(0px)', transitionEnd: { filter: 'none' } };
  const transition = reduce
    ? { duration, ease, delay, y: { duration: 0 }, filter: { duration: 0 } }
    : { duration, ease, delay };
  return { hidden, shown, transition };
}
