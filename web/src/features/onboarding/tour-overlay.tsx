'use client';

import { useCallback, useEffect, useLayoutEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { usePathname, useRouter } from 'next/navigation';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { useSidebar } from '@/components/ui/sidebar';
import { Spinner } from '@/components/ui/spinner';
import { navGroups } from '@/config/nav-config';
import { cn } from '@/lib/utils';
import { tourStore, useTourStore, type Rect } from './store';
import { stepBody, TOURS, visibleSteps, type Placement, type TourStep } from './tours';
import { useTourContext } from './use-tour-context';

/**
 * The guided-tour overlay: a spotlight cut out of a dim backdrop, a card beside it, and the
 * "navigate animation" between pages.
 *
 * When the next step lives on another page, the spotlight moves onto that page's link in the
 * sidebar (opening its section if it is folded) and the link pulses, so the person sees where
 * the page lives. Nothing moves on a timer: "Open {page}" (or a click on the lit link) opens
 * the route, and the overlay on the new page starts from the same rectangle and morphs onto
 * the step's target once it is on screen. On a phone the menu button is lit instead.
 *
 * Mounted from the app template, so it re-mounts on every navigation; the running tour lives
 * in `tourStore`, which is what makes the continuation possible. While a tour runs the app
 * behind it is `inert`: focus stays in the card, Tab cycles inside it, Esc ends the tour.
 */

const PAD = 8;
const CARD_W = 336;
const GAP = 14;
const MARGIN = 12;
/** How long to wait for a step's target once the page's data has settled. */
const FIND_MS = 2500;
/** How long to wait for a sidebar link to appear after opening its section. */
const LINK_MS = 1200;
const MOBILE = 640;
/** Target lookups poll on a timer, not on animation frames, so a background tab never stalls a step. */
const POLL_MS = 80;

type Phase = 'hop' | 'waiting' | 'shown';

function query(selectors: string[]): HTMLElement | null {
  for (const selector of selectors) {
    try {
      const el = document.querySelector<HTMLElement>(selector);
      if (el) return el;
    } catch {
      /* an unsupported selector (older browsers and :has) just falls through */
    }
  }
  return null;
}

function rectOf(el: HTMLElement, pad = PAD): Rect {
  const r = el.getBoundingClientRect();
  return { x: r.left - pad, y: r.top - pad, w: r.width + pad * 2, h: r.height + pad * 2 };
}

function same(a: Rect | null, b: Rect | null) {
  if (!a || !b) return a === b;
  return Math.abs(a.x - b.x) < 0.5 && Math.abs(a.y - b.y) < 0.5 && Math.abs(a.w - b.w) < 0.5 && Math.abs(a.h - b.h) < 0.5;
}

/** The sidebar section a route belongs to ("Workspace" for /app/workspace/brand). */
function groupOf(route: string): string | null {
  return navGroups.find((group) => group.items.some((item) => item.url === route))?.label ?? null;
}

/** The route's link in the sidebar, only when it is actually on screen (a folded section keeps it in the DOM, hidden). */
function sidebarLink(route: string) {
  const link = document.querySelector<HTMLElement>(`[data-slot="sidebar"] a[href="${route}"]`);
  if (!link) return null;
  const box = link.getBoundingClientRect();
  return box.width > 0 && box.height > 0 ? link : null;
}

function groupTrigger(label: string, expanded: boolean) {
  const buttons = document.querySelectorAll<HTMLElement>(`[data-slot="sidebar"] button[aria-expanded="${expanded}"]`);
  return [...buttons].find((button) => button.textContent?.trim().toLowerCase() === label.toLowerCase()) ?? null;
}

const clamp = (v: number, lo: number, hi: number) => Math.min(Math.max(v, lo), Math.max(lo, hi));

function placeCard(rect: Rect, card: { w: number; h: number }, prefer: Placement | undefined, vw: number, vh: number) {
  const clampX = (x: number) => clamp(x, MARGIN, vw - card.w - MARGIN);
  const clampY = (y: number) => clamp(y, MARGIN, vh - card.h - MARGIN);
  const below = rect.y + rect.h + GAP;
  const above = rect.y - GAP - card.h;
  const order: Placement[] = prefer ? [prefer, 'bottom', 'top', 'right', 'left'] : ['bottom', 'top', 'right', 'left'];
  for (const side of order) {
    if (side === 'bottom' && below + card.h <= vh - MARGIN) return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: below };
    if (side === 'top' && above >= MARGIN) return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: above };
    if (side === 'right' && rect.x + rect.w + GAP + card.w <= vw - MARGIN) return { x: rect.x + rect.w + GAP, y: clampY(rect.y) };
    if (side === 'left' && rect.x - GAP - card.w >= MARGIN) return { x: rect.x - GAP - card.w, y: clampY(rect.y) };
  }
  // Nothing fits beside a target this large: sit inside the viewport, over its lower edge.
  return { x: clampX(rect.x + rect.w / 2 - card.w / 2), y: clampY(below) };
}

const FOCUSABLE = 'button:not([disabled]), [href], input:not([disabled]), [tabindex]:not([tabindex="-1"])';

export function TourOverlay() {
  const active = useTourStore((s) => s.active);
  const lastRect = useTourStore((s) => s.lastRect);
  const pathname = usePathname();
  const router = useRouter();
  const reduce = useReducedMotion();
  const { isMobile } = useSidebar();
  const { ctx, ready } = useTourContext();

  const tour = active ? TOURS[active.tourId] : null;
  const steps = tour ? visibleSteps(tour, ctx) : [];
  const total = steps.length;
  const index = active ? Math.min(active.index, Math.max(0, total - 1)) : 0;
  const step: TourStep | undefined = steps[index];

  // Whether this mount continues a tour that just changed page: then nothing fades in again.
  const continuing = useRef(Boolean(tourStore.get().hop)).current;

  const [phase, setPhase] = useState<Phase>('waiting');
  const [rect, setRect] = useState<Rect | null>(lastRect);
  const [card, setCard] = useState({ w: CARD_W, h: 168 });
  const [vp, setVp] = useState({ w: 0, h: 0 });
  const [mounted, setMounted] = useState(false);
  const cardRef = useRef<HTMLDivElement>(null);
  const targetRef = useRef<HTMLElement | null>(null);
  const restoreFocus = useRef<Element | null>(null);
  const stepRef = useRef(step);
  stepRef.current = step;
  const reduceRef = useRef(reduce);
  reduceRef.current = reduce;

  useEffect(() => setMounted(true), []);

  useEffect(() => {
    const update = () => setVp({ w: window.innerWidth, h: window.innerHeight });
    update();
    window.addEventListener('resize', update);
    return () => window.removeEventListener('resize', update);
  }, []);

  const measure = useCallback(() => {
    const el = targetRef.current;
    if (!el || !el.isConnected) return;
    const next = rectOf(el);
    setRect((prev) => (same(prev, next) ? prev : next));
  }, []);

  const advance = useCallback(() => {
    if (index + 1 < total) tourStore.goTo(index + 1);
    else tourStore.end('completed');
  }, [index, total]);

  const back = useCallback(() => {
    if (index > 0) tourStore.goTo(index - 1);
  }, [index]);

  /** Open the step's page. The lit link's rectangle is where the next page's spotlight starts. */
  const openRoute = useCallback(() => {
    const current = stepRef.current;
    if (!current) return;
    const lit = targetRef.current;
    tourStore.setLastRect(lit && lit.isConnected ? rectOf(lit) : null);
    tourStore.hopTo(current.route);
    router.push(current.route);
  }, [router]);

  // Close the sidebar sections the tour opened, once it ends (except the one holding this page).
  useEffect(() => {
    if (active) return;
    const current = groupOf(pathname);
    for (const label of tourStore.takeOpenedGroups()) {
      if (label !== current) groupTrigger(label, true)?.click();
    }
  }, [active, pathname]);

  // Keep the app behind the tour out of reach: no stray clicks, no focus behind the card.
  useEffect(() => {
    if (!active) return;
    const app = document.querySelector<HTMLElement>('[data-slot="sidebar-wrapper"]');
    app?.setAttribute('inert', '');
    return () => app?.removeAttribute('inert');
  }, [active]);

  // Find the target on this page, or light the way to the step's page.
  const tourId = active?.tourId ?? null;
  const stepId = step?.id ?? null;
  const stepRoute = step?.route ?? null;
  useEffect(() => {
    const current = stepRef.current;
    if (!tourId || !current || !ready) return;
    let cancelled = false;
    let raf = 0;
    let poll = 0;
    const undo: (() => void)[] = [];

    if (current.route !== pathname) {
      setPhase('hop');
      if (isMobile) {
        // On a phone the sidebar is a sheet; light the button that opens it.
        const trigger = document.querySelector<HTMLElement>('[data-sidebar="trigger"]');
        targetRef.current = trigger;
        if (trigger) measure();
        else setRect(null);
        return;
      }
      const label = groupOf(current.route);
      const started = performance.now();
      let opened = false;
      const light = () => {
        if (cancelled) return;
        const link = sidebarLink(current.route);
        if (link) {
          link.setAttribute('data-tour-pulse', '');
          undo.push(() => link.removeAttribute('data-tour-pulse'));
          targetRef.current = link;
          link.scrollIntoView({ block: 'nearest', behavior: reduceRef.current ? 'auto' : 'smooth' });
          measure();
          return;
        }
        if (label && !opened) {
          const trigger = groupTrigger(label, false);
          if (trigger) {
            opened = true;
            trigger.click();
            tourStore.rememberOpenedGroup(label);
          }
        }
        if (performance.now() - started > LINK_MS) {
          // No link to light (hidden by permissions, or the sidebar is elsewhere): the card says where to go.
          targetRef.current = null;
          setRect(null);
          return;
        }
        poll = window.setTimeout(light, POLL_MS);
      };
      light();
      return () => {
        cancelled = true;
        clearTimeout(poll);
        for (const fn of undo) fn();
      };
    }

    setPhase('waiting');
    const started = performance.now();
    let ro: ResizeObserver | null = null;
    const find = () => {
      if (cancelled) return;
      const el = query(current.target);
      if (el) {
        targetRef.current = el;
        tourStore.clearHop();
        el.scrollIntoView({ block: 'center', inline: 'nearest', behavior: reduceRef.current ? 'auto' : 'smooth' });
        setPhase('shown');
        measure();
        ro = new ResizeObserver(measure);
        ro.observe(el);
        // Follow the page's enter transition and the smooth scroll for a moment.
        const until = performance.now() + 900;
        const follow = () => {
          if (cancelled) return;
          measure();
          if (performance.now() < until) raf = requestAnimationFrame(follow);
        };
        raf = requestAnimationFrame(follow);
        return;
      }
      if (performance.now() - started > FIND_MS) {
        // Nothing to point at on this page (a permission hid it, or the page is empty): move on.
        tourStore.clearHop();
        const state = tourStore.get();
        if (state.active && state.active.index + 1 < total) tourStore.goTo(state.active.index + 1);
        else tourStore.end('completed');
        return;
      }
      poll = window.setTimeout(find, POLL_MS);
    };
    find();
    const onMove = () => measure();
    window.addEventListener('scroll', onMove, true);
    window.addEventListener('resize', onMove);
    return () => {
      cancelled = true;
      cancelAnimationFrame(raf);
      clearTimeout(poll);
      ro?.disconnect();
      window.removeEventListener('scroll', onMove, true);
      window.removeEventListener('resize', onMove);
    };
  }, [tourId, stepId, stepRoute, pathname, ready, total, isMobile, measure]);

  // Esc works even if focus somehow left the card.
  useEffect(() => {
    if (!active) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      event.preventDefault();
      tourStore.end('dismissed');
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [active]);

  useEffect(() => {
    if (!active) return;
    if (!restoreFocus.current) restoreFocus.current = document.activeElement;
    return () => {
      const el = restoreFocus.current;
      restoreFocus.current = null;
      if (el instanceof HTMLElement && el.isConnected && !tourStore.get().active) el.focus({ preventScroll: true });
    };
  }, [active]);

  useEffect(() => {
    if (phase !== 'waiting') cardRef.current?.focus({ preventScroll: true });
  }, [phase, stepId]);

  useLayoutEffect(() => {
    const el = cardRef.current;
    if (!el) return;
    const update = () => setCard({ w: el.offsetWidth, h: el.offsetHeight });
    update();
    const ro = new ResizeObserver(update);
    ro.observe(el);
    return () => ro.disconnect();
  }, [active, phase, stepId]);

  /** Arrows step through, Tab stays inside the card. */
  const onCardKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    if (event.key === 'Tab') {
      const items = [...(cardRef.current?.querySelectorAll<HTMLElement>(FOCUSABLE) ?? [])];
      if (items.length === 0) return;
      const first = items[0];
      const last = items[items.length - 1];
      if (event.shiftKey && (document.activeElement === first || document.activeElement === cardRef.current)) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
      return;
    }
    if (phase === 'shown' && event.key === 'ArrowRight') {
      event.preventDefault();
      advance();
    } else if (event.key === 'ArrowLeft') {
      event.preventDefault();
      back();
    }
  };

  if (!mounted) return null;

  const mobile = vp.w > 0 && vp.w < MOBILE;
  const transition = { duration: reduce ? 0 : 0.25, ease: [0.22, 1, 0.36, 1] as const };
  const cut: Rect = rect ?? { x: vp.w / 2 - 1, y: vp.h / 2 - 1, w: 2, h: 2 };
  const cardPos = mobile
    ? null
    : phase === 'waiting' || !rect
      ? { x: Math.max(MARGIN, vp.w / 2 - card.w / 2), y: Math.max(MARGIN, vp.h / 2 - card.h / 2) }
      : placeCard(rect, card, phase === 'hop' ? 'right' : step?.placement, vp.w, vp.h);
  const body = step ? stepBody(step, ctx) : '';
  const last = index + 1 >= total;
  const group = step ? groupOf(step.route) : null;
  const hopBody = !step
    ? ''
    : isMobile
      ? `Every page is in this menu. Next up is ${step.stop}.`
      : rect && group
        ? `${step.stop} lives in the sidebar under ${group}. Open it from there any time.`
        : `Next up is ${step.stop}.`;
  const title = phase === 'shown' ? step?.title : `Next: ${step?.stop}`;

  return createPortal(
    <AnimatePresence initial={!continuing}>
      {active && step && (
        <motion.div
          key='tour'
          initial={{ opacity: 0 }}
          animate={{ opacity: 1, transition: { duration: reduce ? 0 : 0.25, ease: [0.22, 1, 0.36, 1] } }}
          exit={{ opacity: 0, transition: { duration: reduce ? 0 : 0.15 } }}
          className='fixed inset-0 z-70'
          data-slot='tour-overlay'
        >
          {/* The spotlight: one box whose enormous shadow is the dim backdrop, so moving the box moves the hole.
              While it lights a link, clicking inside it opens that page, like clicking the link itself. */}
          <motion.div
            aria-hidden
            initial={false}
            animate={{ x: cut.x, y: cut.y, opacity: phase === 'waiting' ? 0.6 : 1 }}
            transition={transition}
            onClick={phase === 'hop' && rect ? openRoute : undefined}
            className={cn('ring-foreground/70 absolute rounded-[var(--rafii-radius-control)] ring-2', phase === 'hop' && rect ? 'cursor-pointer' : 'pointer-events-none')}
            style={{ left: 0, top: 0, width: cut.w, height: cut.h, boxShadow: '0 0 0 200vmax rgb(0 0 0 / 0.5)' }}
          />
          <p className='sr-only' aria-live='polite'>
            {phase === 'shown' ? `Step ${index + 1} of ${total}: ${step.title}` : `Next: ${step.stop}`}
          </p>
          <motion.div
            ref={cardRef}
            role='dialog'
            aria-modal='true'
            aria-labelledby='tour-title'
            aria-describedby='tour-body'
            tabIndex={-1}
            onKeyDown={onCardKeyDown}
            initial={false}
            animate={{ x: mobile ? 0 : cardPos?.x ?? MARGIN, y: mobile ? 0 : cardPos?.y ?? MARGIN, opacity: 1 }}
            transition={transition}
            className={cn(
              'rafii-elevated text-foreground absolute flex flex-col gap-3 rounded-[var(--rafii-radius-card)] p-5 outline-hidden',
              mobile ? 'inset-x-3 bottom-[max(0.75rem,env(safe-area-inset-bottom))]' : 'top-0 left-0 w-[336px]'
            )}
          >
            <div className='flex items-center justify-between gap-2'>
              <span className='rafii-eyebrow'>
                {tour?.title} · {index + 1} of {total}
              </span>
              <button
                type='button'
                onClick={() => tourStore.end('dismissed')}
                aria-label='End tour'
                className='rafii-focus hover:rafii-quiet text-muted-foreground hover:text-foreground -mr-2 -mt-1 flex size-9 items-center justify-center rounded-full transition-colors'
              >
                <Icons.close className='size-4' />
              </button>
            </div>
            <div className='flex flex-col gap-1'>
              <h2 id='tour-title' className='text-foreground text-base leading-snug font-medium tracking-tight'>
                {title}
              </h2>
              <p id='tour-body' className='text-muted-foreground flex items-center gap-2 text-sm leading-relaxed'>
                {phase === 'waiting' && <Spinner className='size-3.5 shrink-0' />}
                {phase === 'shown' ? body : phase === 'hop' ? hopBody : `Opening ${step.stop}…`}
              </p>
            </div>
            <div className='flex items-center justify-between gap-2 pt-1'>
              <button type='button' onClick={() => tourStore.end('dismissed')} className='rafii-focus text-muted-foreground hover:text-foreground min-h-9 rounded-sm text-xs underline-offset-4 hover:underline'>
                Skip tour
              </button>
              <div className='flex items-center gap-2'>
                <Button variant='quiet' size='sm' className='h-9' onClick={back} disabled={index === 0}>
                  Back
                </Button>
                {phase === 'shown' && (
                  <Button variant='action' size='sm' className='h-9 px-3.5' onClick={advance}>
                    {last ? 'Done' : 'Next'}
                    {!last && <Icons.chevronRight className='size-4' />}
                  </Button>
                )}
                {phase === 'hop' && (
                  <Button variant='action' size='sm' className='h-9 px-3.5' onClick={openRoute}>
                    Open {step.stop}
                    <Icons.chevronRight className='size-4' />
                  </Button>
                )}
              </div>
            </div>
          </motion.div>
        </motion.div>
      )}
    </AnimatePresence>,
    document.body
  );
}
