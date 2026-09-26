'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { usePathname, useRouter } from 'next/navigation';
import { AnimatePresence, animate, motion, useMotionValue } from 'motion/react';
import { Icons } from '@/components/icons';
import { Surface } from '@/components/rafii';
import { Button } from '@/components/ui/button';
import { Spinner } from '@/components/ui/spinner';
import { siteConfig } from '@/config/site';
import { clamp, placeCard, sameRect } from '@/features/onboarding/geometry';
import type { Rect } from '@/features/onboarding/store';
import { PANEL_ID, useDocked, useOtherDialog } from '@/features/site-agent/panel';
import { RafiiAvatar } from '@/features/site-agent/rafii-avatar';
import { usePanel } from '@/features/site-agent/store';
import { EASE_IN_OUT, EASE_OUT } from '@/lib/ease';
import { useMotionPreference } from '@/lib/rafii/motion';
import manifestJson from '@/lib/site-agent/route-manifest.json';
import { matchRoute, type RouteManifest } from '@/lib/site-agent/routes';
import { cn } from '@/lib/utils';
import { anchorOf, curvePoint, glideDuration, type Point } from './geometry';
import { guideFor } from './guides';
import { runGuide, sleep, type GuideView, type RunnerIO } from './runner';
import { guideStore, useGuideStore } from './store';

/**
 * Rafii's hands on the page (Contract 5): a cursor that glides from the panel to each target along a gentle curve,
 * a ring around the target, a click ripple, and a caption card with the step, Stop and Next. It never covers the
 * page: everything but the card lets clicks through, so the person can do their own steps while it waits.
 *
 * Z-order: under the docked Rafii panel (the panel stays usable above it) and over the page; while a sheet or dialog
 * is open it rises above that dialog, so it can point inside it. Mounted once in the app shell by `GuideMount`.
 */

const MANIFEST = manifestJson as RouteManifest;
const PAD = 6;
const CARD_W = 336;
const GAP = 18;
const MARGIN = 12;
const RING = '0 0 0 2px color-mix(in oklch, var(--foreground) 82%, transparent), 0 0 0 7px color-mix(in oklch, var(--foreground) 12%, transparent)';

/** The cursor sets off from Rafii: the docked panel's edge, or the lower middle of the screen. */
function startPoint(): Point {
  const panel = document.getElementById(PANEL_ID);
  const box = panel?.getBoundingClientRect();
  if (box && box.width > 0 && box.left > window.innerWidth * 0.4) {
    return { x: Math.max(24, box.left - 36), y: Math.min(window.innerHeight - 96, box.top + box.height * 0.7) };
  }
  return { x: window.innerWidth * 0.6, y: window.innerHeight * 0.8 };
}

/** The open sheet or dialog a target sits in: the card goes beside it rather than over its fields. */
function dialogBox(el: HTMLElement | null) {
  const box = el?.closest('[role="dialog"], [role="alertdialog"]')?.getBoundingClientRect();
  return box && box.width > 0 ? box : null;
}

function CursorArrow() {
  return (
    <svg width='22' height='28' viewBox='0 0 22 28' aria-hidden className='absolute -top-0.5 -left-0.5 drop-shadow-[0_2px_4px_rgb(0_0_0/0.35)]'>
      <path d='M2 2 L2 22.5 L7.4 17.6 L11.1 25.6 L14.6 24 L11 16.1 L18.2 16.1 Z' fill='var(--foreground)' stroke='var(--background)' strokeWidth='1.6' strokeLinejoin='round' />
    </svg>
  );
}

export function GuideOverlay() {
  const run = useGuideStore((s) => s.run);
  const router = useRouter();
  const pathname = usePathname() ?? '';
  const { reduced } = useMotionPreference();
  const docked = useDocked();
  const dialogOpen = useOtherDialog();
  const panelOpen = usePanel((s) => s.open && !s.above);

  const [mounted, setMounted] = useState(false);
  const [view, setView] = useState<GuideView | null>(null);
  const [rect, setRect] = useState<Rect | null>(null);
  const [arrived, setArrived] = useState(false);
  const [ripples, setRipples] = useState<{ id: number; x: number; y: number }[]>([]);
  const [card, setCard] = useState({ w: CARD_W, h: 150 });
  const [vp, setVp] = useState({ w: 0, h: 0, right: 0 });

  const cursorX = useMotionValue(-80);
  const cursorY = useMotionValue(-80);
  const cursorScale = useMotionValue(1);

  const cardRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const rectRef = useRef<Rect | null>(null);
  const gliding = useRef(false);
  const following = useRef(false);
  const nextRef = useRef<(() => void) | null>(null);
  const expectRef = useRef<string | null>(null);
  const seenPath = useRef(pathname);
  const reducedRef = useRef(reduced);
  reducedRef.current = reduced;

  useEffect(() => setMounted(true), []);

  // The usable width stops at the docked panel's edge, so the card never sits over the conversation.
  useEffect(() => {
    const update = () => {
      const panel = document.getElementById(PANEL_ID);
      const box = panel?.tagName === 'ASIDE' ? panel.getBoundingClientRect() : null;
      setVp({ w: window.innerWidth, h: window.innerHeight, right: box && box.width > 0 ? box.left : window.innerWidth });
    };
    update();
    const frame = requestAnimationFrame(update);
    window.addEventListener('resize', update);
    return () => {
      cancelAnimationFrame(frame);
      window.removeEventListener('resize', update);
    };
  }, [docked, panelOpen]);

  // Going to another page (a link, the back button) stops the guide; the guide's own page changes are expected.
  useEffect(() => {
    if (seenPath.current === pathname) return;
    seenPath.current = pathname;
    const expected = expectRef.current;
    if (guideStore.get().run && expected && pathname !== expected) guideStore.stop();
  }, [pathname]);

  // Escape stops the guide (and only the guide: the docked panel stays open).
  useEffect(() => {
    if (!run) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape' || event.isComposing) return;
      event.preventDefault();
      guideStore.stop();
    };
    window.addEventListener('keydown', onKey, true);
    return () => window.removeEventListener('keydown', onKey, true);
  }, [run]);

  // Follow the lit target every frame: scrolling, a sheet sliding in, a layout shift. React state changes only on a move.
  useEffect(() => {
    if (!run) return;
    let frame = 0;
    const tick = () => {
      const el = targetRef.current;
      if (el && el.isConnected) {
        const box = el.getBoundingClientRect();
        const next = { x: box.left - PAD, y: box.top - PAD, w: box.width + PAD * 2, h: box.height + PAD * 2 };
        if (!sameRect(rectRef.current, next)) {
          rectRef.current = next;
          setRect(next);
          if (following.current && !gliding.current) {
            const aim = anchorOf(box);
            cursorX.set(aim.x);
            cursorY.set(aim.y);
          }
        }
      } else if (rectRef.current) {
        rectRef.current = null;
        setRect(null);
      }
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [run, cursorX, cursorY]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const update = () => setCard({ w: el.offsetWidth, h: el.offsetHeight });
    update();
    const observer = new ResizeObserver(update);
    observer.observe(el);
    return () => observer.disconnect();
  }, [view?.phase, run]);

  const glideTo = useCallback(
    (el: HTMLElement, signal: AbortSignal) =>
      new Promise<void>((resolve) => {
        following.current = false;
        setArrived(false);
        const from = { x: cursorX.get(), y: cursorY.get() };
        const aim = () => anchorOf(el.getBoundingClientRect());
        const to = aim();
        const distance = Math.hypot(to.x - from.x, to.y - from.y);
        const land = () => {
          gliding.current = false;
          following.current = true;
          setArrived(true);
          resolve();
        };
        if (reducedRef.current || distance < 2 || signal.aborted) {
          // Reduced motion: the cursor jumps.
          cursorX.set(to.x);
          cursorY.set(to.y);
          return land();
        }
        gliding.current = true;
        const controls = animate(0, 1, {
          duration: glideDuration(distance) / 1000,
          ease: EASE_IN_OUT,
          // The target may still be moving (a sheet sliding in): aim at where it is now.
          onUpdate: (t) => {
            const point = curvePoint(from, el.isConnected ? aim() : to, t);
            cursorX.set(point.x);
            cursorY.set(point.y);
          },
          onComplete: land
        });
        signal.addEventListener(
          'abort',
          () => {
            controls.stop();
            gliding.current = false;
            resolve();
          },
          { once: true }
        );
      }),
    [cursorX, cursorY]
  );

  const press = useCallback(
    async (signal: AbortSignal) => {
      const id = Date.now() + Math.random();
      setRipples((list) => [...list, { id, x: cursorX.get(), y: cursorY.get() }]);
      if (!reducedRef.current) animate(cursorScale, [1, 0.82, 1], { duration: 0.3, ease: EASE_OUT });
      await sleep(160, signal);
    },
    [cursorX, cursorY, cursorScale]
  );

  // One run at a time: a new run (or "Show me" again) aborts the previous one and starts from step 1.
  const runId = run?.id ?? null;
  const guideId = run?.guideId ?? null;
  useEffect(() => {
    if (runId === null || !guideId) {
      setView(null);
      setArrived(false);
      return;
    }
    const guide = guideFor(guideId);
    if (!guide) {
      guideStore.finish(runId);
      return;
    }
    const controller = new AbortController();
    const { signal } = controller;
    const start = startPoint();
    cursorX.set(start.x);
    cursorY.set(start.y);
    cursorScale.set(1);
    following.current = false;
    targetRef.current = null;
    rectRef.current = null;
    setRect(null);
    setArrived(false);
    const io: RunnerIO = {
      signal,
      reduced: () => reducedRef.current,
      pathname: () => window.location.pathname,
      titleOf: (path) => matchRoute(MANIFEST, path)?.route.title ?? 'the page',
      open: (route) => router.push(route),
      expect: (path) => {
        expectRef.current = path;
      },
      show: (next) => {
        if (!signal.aborted) setView(next);
      },
      light: (el) => {
        targetRef.current = el;
        if (!el) {
          following.current = false;
          setArrived(false);
        }
      },
      glide: (el) => glideTo(el, signal),
      press: () => press(signal),
      next: () =>
        new Promise<void>((resolve) => {
          nextRef.current = resolve;
        })
    };
    void runGuide(guide, io)
      .catch(() => undefined)
      .finally(() => {
        if (!signal.aborted) guideStore.finish(runId);
      });
    return () => {
      controller.abort();
      nextRef.current = null;
      expectRef.current = null;
      targetRef.current = null;
      following.current = false;
    };
  }, [runId, guideId, router, glideTo, press, cursorX, cursorY, cursorScale]);

  const pressNext = useCallback(() => {
    const resolve = nextRef.current;
    nextRef.current = null;
    resolve?.();
  }, []);

  if (!mounted) return null;

  const active = Boolean(run && view);
  const phase = view?.phase ?? null;
  const ended = phase === 'done' || phase === 'stopped';
  const showRing = active && phase === 'step' && arrived && rect !== null;
  const showCursor = active && !ended;
  // Beside an open dialog anything goes; otherwise the card stays left of the docked panel.
  const right = dialogOpen ? vp.w : vp.right || vp.w;
  const cardW = Math.min(CARD_W, Math.max(240, right - MARGIN * 2));
  const box = active && rect ? dialogBox(targetRef.current) : null;
  let pos: Point;
  if (rect && !ended) {
    const y = clamp(rect.y, MARGIN, vp.h - card.h - MARGIN);
    if (box && box.left - GAP - cardW >= MARGIN) pos = { x: box.left - GAP - cardW, y };
    else if (box && box.right + GAP + cardW <= right - MARGIN) pos = { x: box.right + GAP, y };
    else pos = placeCard(rect, { w: cardW, h: card.h }, view?.placement, right, vp.h, GAP, MARGIN);
  } else {
    // Nothing lit yet (a page opening) or the closing words: low in the middle, clear of the phone tab bar.
    pos = { x: clamp(right / 2 - cardW / 2, MARGIN, right - cardW - MARGIN), y: Math.max(MARGIN, vp.h - card.h - (vp.w < 768 ? 88 : 28)) };
  }
  const eyebrow = !view ? '' : phase === 'done' ? 'All done' : phase === 'stopped' ? 'Stopped' : `Step ${view.index + 1} of ${view.total}`;
  const busy = phase === 'opening' || phase === 'finding';
  const buttonLabel = view?.button === 'next' ? 'Next' : view?.button === 'done' ? 'Done' : view?.button === 'close' ? 'Close' : null;
  const transition = { duration: reduced ? 0 : 0.28, ease: EASE_OUT };

  return createPortal(
    <div data-guide-overlay='' className={cn('pointer-events-none fixed inset-0', dialogOpen ? 'z-[60]' : docked ? 'z-[15]' : 'z-[35]')}>
      <p className='sr-only' aria-live='polite'>
        {active && view ? `${eyebrow}. ${view.yourTurn ? 'Your turn. ' : ''}${view.text}` : ''}
      </p>

      <AnimatePresence>
        {showRing && rect && (
          <motion.div
            key='ring'
            aria-hidden
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.2, ease: EASE_OUT }}
            className='absolute rounded-[var(--rafii-radius-control)]'
            style={{ left: rect.x, top: rect.y, width: rect.w, height: rect.h, boxShadow: RING }}
          >
            {!reduced && (
              <motion.span
                aria-hidden
                className='absolute inset-0 rounded-[inherit]'
                style={{ boxShadow: '0 0 0 2px color-mix(in oklch, var(--foreground) 45%, transparent)' }}
                initial={{ opacity: 0.7, scale: 1 }}
                animate={{ opacity: 0, scale: 1.08 }}
                transition={{ duration: 1.6, ease: EASE_OUT, repeat: Infinity, repeatDelay: 0.4 }}
              />
            )}
          </motion.div>
        )}
      </AnimatePresence>

      {ripples.map((ripple) => (
        <motion.span
          key={ripple.id}
          aria-hidden
          className='border-foreground/70 absolute top-0 left-0 size-10 rounded-full border-2'
          style={{ x: ripple.x - 20, y: ripple.y - 20 }}
          initial={{ scale: reduced ? 1 : 0.2, opacity: 0.8 }}
          animate={{ scale: reduced ? 1 : 1.7, opacity: 0 }}
          transition={{ duration: reduced ? 0.25 : 0.5, ease: EASE_OUT }}
          onAnimationComplete={() => setRipples((list) => list.filter((item) => item.id !== ripple.id))}
        />
      ))}

      <AnimatePresence>
        {showCursor && (
          <motion.div
            key='cursor'
            aria-hidden
            className='absolute top-0 left-0'
            style={{ x: cursorX, y: cursorY }}
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            transition={{ duration: reduced ? 0 : 0.2 }}
          >
            <motion.div style={{ scale: cursorScale, transformOrigin: '0px 0px' }}>
              <CursorArrow />
            </motion.div>
            <span className='bg-foreground text-background absolute top-6 left-4 rounded-full px-2 py-0.5 text-[11px] font-medium whitespace-nowrap shadow-sm'>{siteConfig.name}</span>
          </motion.div>
        )}
      </AnimatePresence>

      <AnimatePresence>
        {active && view && (
          <motion.section
            key='card'
            ref={cardRef}
            aria-label={`${siteConfig.name} is showing you how`}
            className='pointer-events-auto absolute top-0 left-0'
            style={{ width: cardW }}
            initial={{ opacity: 0, x: pos.x, y: pos.y + 6 }}
            animate={{ opacity: 1, x: pos.x, y: pos.y }}
            exit={{ opacity: 0, transition: { duration: reduced ? 0 : 0.15 } }}
            transition={transition}
          >
            <Surface material='elevated' padding='none' className='flex flex-col gap-3 p-4'>
              <div className='flex items-center gap-2'>
                <RafiiAvatar size={24} thinking={busy} />
                <span className='rafii-eyebrow'>{eyebrow}</span>
                {view.yourTurn && !ended && <span className='rafii-quiet text-foreground ml-auto rounded-full px-2 py-0.5 text-[11px] font-medium'>Your turn</span>}
              </div>
              <p className='text-foreground flex items-start gap-2 text-sm leading-relaxed'>
                {busy && <Spinner className='mt-1 size-3.5 shrink-0' />}
                <span>{view.text}</span>
              </p>
              <div className='flex items-center justify-between gap-2'>
                {ended ? (
                  <span />
                ) : (
                  <Button type='button' variant='quiet' size='sm' className='h-9' onClick={() => guideStore.stop()}>
                    <Icons.handStop className='size-4' aria-hidden />
                    Stop
                  </Button>
                )}
                {buttonLabel && (
                  <Button type='button' variant='action' size='sm' className='h-9 px-3.5' onClick={pressNext}>
                    {buttonLabel}
                    {view.button === 'next' && <Icons.chevronRight className='size-4' aria-hidden />}
                  </Button>
                )}
              </div>
            </Surface>
          </motion.section>
        )}
      </AnimatePresence>
    </div>,
    document.body
  );
}
