'use client';

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react';
import { motionAllowed, useMotionPreference } from '@/lib/rafii/motion';
import { cn } from '@/lib/utils';
import { SCREEN_HEIGHT, SCREEN_WIDTH } from './phone-frame';
import { PostPreview } from './post-preview';
import { entryPose, keyframe, layerZIndex, mountedLayers, PHONE_EASING, PHONE_TRANSITION_MS, pose, stepKey, switchDirection, type DeckPose } from './preview-deck-core';
import type { PreviewPost } from './types';
import { useSwipe } from './use-swipe';

export interface DeckItem {
  /** Stable identity of the preview: a draft id, a destination key. Two accounts on one app are two items. */
  key: string;
  post: PreviewPost;
  /** Drawn under the stage while this item is active: app name, surface, an expand button. */
  caption?: ReactNode;
}

export interface PreviewDeckProps {
  items: DeckItem[];
  activeKey: string;
  /** The deck only reports which item the person wants to look at; it never changes destinations. */
  onChange: (key: string) => void;
  /** Phone size; 0.62 draws a phone about 262px wide. */
  scale?: number;
  /** The pager, play, guides and export row under the active phone. */
  tools?: boolean;
  /** Accessible name of the stage. */
  label: string;
  className?: string;
}

/** The bezel `PhoneFrame` adds around the scaled screen. */
const BEZEL = 18;

interface DeckState {
  /** The active key the stage currently shows, or null before the first layout. */
  active: string | null;
  animations: Animation[];
  /** Transition identity: a completion callback only cleans up when nothing newer has started. */
  rev: number;
  /** The stage's content height in CSS pixels, kept in step with the active layer. */
  height: number | null;
}

function applyPose(node: HTMLElement, next: DeckPose) {
  node.style.transform = next.transform;
  node.style.opacity = String(next.opacity);
}

function setStageHeight(host: HTMLElement, state: DeckState, height: number) {
  state.height = height;
  host.style.height = `${height}px`;
}

/**
 * The native preview deck (DNA v8 §17): the active phone centred, up to two dimmed neighbours turned away
 * behind it, a 560ms slide/crossfade between them, and a horizontal swipe (or the dock, or keys) to move.
 *
 * Every layer is a real `PostPreview` for its item, mounted once and kept while it is on stage, so a caption
 * edit re-renders the active phone in place without replaying the transition. Only the active layer is
 * exposed to assistive technology or focus; neighbours and the outgoing layer are `aria-hidden` and `inert`.
 * Switches animate with the Web Animations API from each layer's current pose, so a second request mid-flight
 * turns the phones around instead of restarting; the outgoing layer stays until the animation that owns it
 * ends. Reduced motion swaps instantly.
 */
export function PreviewDeck({ items, activeKey, onChange, scale = 0.62, tools = true, label, className }: PreviewDeckProps) {
  const keys = useMemo(() => items.map((item) => item.key), [items]);
  // Derived from props during render: the key that was active before this one, kept mounted while it leaves.
  const [swap, setSwap] = useState<{ active: string; from: string | null }>({ active: activeKey, from: null });
  if (swap.active !== activeKey) setSwap({ active: activeKey, from: swap.active });
  const outgoing = swap.active === activeKey ? swap.from : swap.active;
  const retained = useMemo(() => (outgoing && outgoing !== activeKey ? [outgoing] : []), [outgoing, activeKey]);
  const layers = useMemo(() => mountedLayers(keys, activeKey, retained), [keys, activeKey, retained]);

  const stage = useRef<HTMLDivElement>(null);
  const state = useRef<DeckState>({ active: null, animations: [], rev: 0, height: null });
  const phoneWidth = SCREEN_WIDTH * scale + BEZEL;
  const phoneHeight = SCREEN_HEIGHT * scale + BEZEL;
  // Reduced motion also drops the neighbours' blur: no filter to composite, nothing left to soften.
  const { reduced } = useMotionPreference();

  useSwipe(stage, {
    onSwipe: (direction) => {
      const next = stepKey(keys, activeKey, direction);
      if (next !== activeKey) onChange(next);
    },
    enabled: keys.length > 1
  });

  // The transition engine (DNA §18.3): read the current poses, cancel the previous owner, pose every layer,
  // animate, and clean up only if this switch is still the latest one.
  useLayoutEffect(() => {
    const host = stage.current;
    if (!host) return;
    const deck = state.current;
    const nodes = new Map<string, HTMLElement>();
    host.querySelectorAll<HTMLElement>('[data-deck-key]').forEach((node) => nodes.set(node.dataset.deckKey ?? '', node));
    const roles = new Map(layers.map((layer) => [layer.key, layer.role]));
    const previous = deck.active;
    const switching = previous !== null && previous !== activeKey;
    const allow = switching && motionAllowed() && host.getClientRects().length > 0 && typeof host.animate === 'function';
    const before = new Map<string, DeckPose>();
    let heightBefore = deck.height;
    if (switching) {
      nodes.forEach((node, key) => {
        // A layer mounted for this switch has no pose yet; it starts from its entry pose below.
        if (!node.style.transform) return;
        const computed = getComputedStyle(node);
        before.set(key, { transform: computed.transform, opacity: Number(computed.opacity) });
      });
      const running = parseFloat(getComputedStyle(host).height);
      if (Number.isFinite(running) && running > 0) heightBefore = running;
      deck.rev += 1;
      deck.animations.forEach((animation) => animation.cancel());
      deck.animations = [];
    }
    const busy = deck.animations.length > 0;
    nodes.forEach((node, key) => {
      const role = roles.get(key) ?? 'exit';
      // Typing while a transition runs updates content, not poses: a mid-flight layer keeps its animation.
      if (switching || !busy || !node.style.transform) applyPose(node, pose(role));
    });
    deck.active = activeKey;
    const activeNode = nodes.get(activeKey);
    const target = activeNode ? activeNode.offsetHeight : 0;

    if (!allow) {
      if (switching || !busy) {
        deck.animations.forEach((animation) => animation.cancel());
        deck.animations = [];
        host.dataset.transition = 'idle';
        if (target > 0) setStageHeight(host, deck, target);
        setSwap((current) => (current.from === null ? current : { active: current.active, from: null }));
      }
      return;
    }

    const rev = deck.rev;
    host.dataset.transition = 'switching';
    const direction = switchDirection(keys, previous, activeKey);
    const options: KeyframeAnimationOptions = { duration: PHONE_TRANSITION_MS, easing: PHONE_EASING, fill: 'both' };
    nodes.forEach((node, key) => {
      const end = pose(roles.get(key) ?? 'exit');
      let start = before.get(key) ?? (key === activeKey ? entryPose(direction) : { transform: end.transform, opacity: 0 });
      if (start.transform === 'none') start = { ...start, transform: pose('active').transform };
      deck.animations.push(node.animate([keyframe(start), keyframe(end)], options));
    });
    if (target > 0) {
      if (heightBefore !== null && heightBefore > 0 && Math.abs(heightBefore - target) > 0.5) {
        deck.animations.push(host.animate([{ height: `${heightBefore}px` }, { height: `${target}px` }], options));
      }
      setStageHeight(host, deck, target);
    }
    const owned = [...deck.animations];
    Promise.all(owned.map((animation) => animation.finished.catch(() => {}))).then(() => {
      if (deck.rev !== rev) return;
      owned.forEach((animation) => animation.cancel());
      deck.animations = [];
      host.dataset.transition = 'idle';
      const settled = host.querySelector<HTMLElement>(`[data-deck-key="${CSS.escape(activeKey)}"]`);
      if (settled && settled.offsetHeight > 0) setStageHeight(host, deck, settled.offsetHeight);
      setSwap((current) => (current.from === null ? current : { active: current.active, from: null }));
    });
  }, [layers, keys, activeKey]);

  // Notes under the active phone change with the text; the stage follows its layer's height without a transition.
  useLayoutEffect(() => {
    const host = stage.current;
    const node = host?.querySelector<HTMLElement>(`[data-deck-key="${CSS.escape(activeKey)}"]`);
    if (!host || !node || typeof ResizeObserver === 'undefined') return;
    const observer = new ResizeObserver(() => {
      if (host.dataset.transition === 'switching') return;
      if (node.offsetHeight > 0) setStageHeight(host, state.current, node.offsetHeight);
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, [activeKey]);

  useEffect(() => {
    const deck = state.current;
    return () => {
      deck.rev += 1;
      deck.animations.forEach((animation) => animation.cancel());
      deck.animations = [];
    };
  }, []);

  const active = items.find((item) => item.key === activeKey);

  return (
    <div className={cn('flex min-w-0 flex-col items-center', className)}>
      <div
        ref={stage}
        role='group'
        aria-label={label}
        className={cn(
          'relative isolate grid w-full [grid-template-columns:minmax(0,1fr)] [align-items:start] justify-items-center overflow-hidden pt-6 pb-5 [box-sizing:content-box] [perspective:1100px]',
          '[touch-action:pan-y_pinch-zoom] [translate:var(--swipe-offset,0px)_0] transition-[translate] duration-[160ms] ease-out data-[swipe=dragging]:transition-none data-[swipe=dragging]:select-none',
          keys.length > 1 && 'cursor-grab data-[swipe=dragging]:cursor-grabbing'
        )}
      >
        {layers.map(({ key, role }) => {
          const item = items.find((entry) => entry.key === key);
          if (!item) return null;
          const isActive = role === 'active';
          return (
            <div
              key={key}
              data-deck-key={key}
              data-role={role}
              aria-hidden={!isActive}
              inert={!isActive}
              className={cn(
                'relative [grid-area:1/1] transform-flat backface-hidden',
                // Neighbours and the outgoing layer are pictures: no pointer, no selection, contained layout.
                'aria-hidden:pointer-events-none aria-hidden:select-none aria-hidden:[contain:layout_style]',
                'in-data-[transition=switching]:will-change-[transform,opacity]',
                // Resting poses until the first layout; inline poses take over from then on.
                'data-[role=left]:[transform:translateX(-65%)_rotateY(14deg)_scale(0.83)] data-[role=left]:opacity-20',
                'data-[role=right]:[transform:translateX(65%)_rotateY(-14deg)_scale(0.83)] data-[role=right]:opacity-20',
                'data-[role=exit]:opacity-0'
              )}
              style={{
                width: phoneWidth,
                transformOrigin: `50% ${phoneHeight * 0.52}px`,
                zIndex: layerZIndex(role, key === outgoing),
                filter: isActive || reduced ? undefined : 'blur(0.6px)'
              }}
            >
              <PostPreview post={item.post} scale={scale} tools={tools && isActive} className={isActive ? undefined : '[&>figcaption]:hidden'} />
            </div>
          );
        })}
      </div>
      {active?.caption && <div className='w-full max-w-full'>{active.caption}</div>}
    </div>
  );
}
