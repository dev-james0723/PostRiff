'use client';

import { useEffect, useMemo, useRef, useState, type PointerEvent as ReactPointerEvent } from 'react';
import { useReducedMotion } from 'motion/react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet';
import type { NavigationItem } from '@/lib/api/types';
import { buildRailMotion, startExternalAudioSync, stopExternalAudioSync, useAudioReactive } from '@/lib/media/audio-reactive';
import { relativeTime } from '@/lib/time';
import { clusterNavigation, MARKER_LABELS, navigationId } from './markers';

interface Props {
  items: NavigationItem[];
  renderedIds: string[];
  onJump: (item: NavigationItem) => void;
}

export function ThreadNavigator({ items, renderedIds, onJump }: Props) {
  const [active, setActive] = useState('');
  const [sheetOpen, setSheetOpen] = useState(false);
  const [clusterOpen, setClusterOpen] = useState<number | null>(null);
  const [mobileGroup, setMobileGroup] = useState<number | null>(null);
  const [desktopExplore, setDesktopExplore] = useState<number | null>(null);
  const [mobileExplore, setMobileExplore] = useState<number | null>(null);
  const touchStart = useRef<{ surface: 'desktop' | 'mobile'; y: number; index: number } | null>(null);
  const groups = useMemo(() => clusterNavigation(items), [items]);
  const activeIndex = Math.max(0, items.findIndex((item) => navigationId(item) === active));
  const reduceMotion = useReducedMotion();
  const audioActive = useAudioReactive((state) => state.active);
  const audioLevel = useAudioReactive((state) => state.level);
  const audioBands = useAudioReactive((state) => state.bands);
  const audioWaveform = useAudioReactive((state) => state.waveform);
  const audioTransient = useAudioReactive((state) => state.transient);
  const audioTickMs = useAudioReactive((state) => state.tickMs);
  const audioSource = useAudioReactive((state) => state.source);
  const externalState = useAudioReactive((state) => state.externalState);
  const activeGroupIndex = useMemo(
    () => groups.findIndex((group) => group.some((item) => navigationId(item) === active)),
    [active, groups]
  );
  const railMotion = useMemo(
    () =>
      buildRailMotion({
        count: groups.length,
        activeIndex: activeGroupIndex,
        level: audioLevel,
        transient: audioTransient,
        bands: audioBands,
        waveform: audioWaveform,
        tickMs: audioTickMs
      }),
    [activeGroupIndex, audioBands, audioLevel, audioTickMs, audioTransient, audioWaveform, groups.length]
  );

  useEffect(() => {
    if (!renderedIds.length || typeof IntersectionObserver === 'undefined') return;
    const observer = new IntersectionObserver((entries) => {
      const visible = entries.filter((entry) => entry.isIntersecting).toSorted((a, b) => a.boundingClientRect.top - b.boundingClientRect.top);
      if (visible[0]) setActive((visible[0].target as HTMLElement).dataset.navId ?? '');
    }, { rootMargin: '-15% 0px -65% 0px', threshold: 0 });
    for (const id of renderedIds) {
      const element = document.getElementById(`turn-${id}`);
      if (element) observer.observe(element);
    }
    return () => observer.disconnect();
  }, [renderedIds]);

  const nearestNeedle = (root: HTMLElement, clientY: number) => {
    const nodes = Array.from(root.querySelectorAll<HTMLElement>('[data-needle-index]'));
    if (!nodes.length) return null;
    let nearest = Number(nodes[0]?.dataset.needleIndex ?? 0);
    let bestDistance = Number.POSITIVE_INFINITY;
    for (const node of nodes) {
      const rect = node.getBoundingClientRect();
      const distance = Math.abs(clientY - (rect.top + rect.height / 2));
      if (distance < bestDistance) {
        bestDistance = distance;
        nearest = Number(node.dataset.needleIndex ?? 0);
      }
    }
    return nearest;
  };

  const updateNeedleExplore = (
    event: ReactPointerEvent<HTMLElement>,
    surface: 'desktop' | 'mobile'
  ) => {
    const index = nearestNeedle(event.currentTarget, event.clientY);
    if (index === null) return;
    if (surface === 'desktop') setDesktopExplore(index);
    else setMobileExplore(index);
  };

  const handleNeedlePointerDown = (
    event: ReactPointerEvent<HTMLElement>,
    surface: 'desktop' | 'mobile'
  ) => {
    updateNeedleExplore(event, surface);
    const index = nearestNeedle(event.currentTarget, event.clientY);
    if (index === null) return;
    touchStart.current = { surface, y: event.clientY, index };
    if (event.pointerType !== 'mouse') {
      event.preventDefault();
      event.currentTarget.setPointerCapture(event.pointerId);
    }
  };

  const handleNeedlePointerUp = (
    event: ReactPointerEvent<HTMLElement>,
    surface: 'desktop' | 'mobile'
  ) => {
    const start = touchStart.current;
    const index = nearestNeedle(event.currentTarget, event.clientY);
    if (event.pointerType !== 'mouse' && start?.surface === surface && index !== null) {
      const moved = Math.abs(event.clientY - start.y);
      if (moved < 9) {
        const group = groups[index];
        if (group?.[0]) jump(group[0]);
      }
      if (event.currentTarget.hasPointerCapture(event.pointerId)) {
        event.currentTarget.releasePointerCapture(event.pointerId);
      }
      setMobileExplore(null);
    }
    touchStart.current = null;
  };

  const interaction = (index: number, explored: number | null) => {
    if (reduceMotion || explored === null) return { proximity: 0, scale: 1, shiftX: 0, rotate: 0 };
    const delta = index - explored;
    const proximity = Math.max(0, 1 - Math.abs(delta) / 3);
    return {
      proximity,
      scale: 1 + proximity * 0.42,
      shiftX: -proximity * 4.5,
      rotate: delta * proximity * 1.35
    };
  };

  const jump = (item: NavigationItem) => {
    setActive(navigationId(item));
    setSheetOpen(false);
    setClusterOpen(null);
    onJump(item);
  };

  const toggleExternalAudio = async () => {
    if (externalState === 'requesting') return;
    if (externalState === 'active') {
      stopExternalAudioSync();
      toast.success('Music sync stopped');
      return;
    }
    try {
      await startExternalAudioSync();
      toast.success('Music sync is reacting to shared playback audio');
    } catch (error) {
      toast.error(error instanceof Error ? error.message : 'Could not start music sync');
    }
  };

  const syncLabel = externalState === 'active' ? 'Stop music sync' : externalState === 'requesting' ? 'Starting music sync' : 'Sync music from this device';

  if (!items.length) return null;
  return (
    <>
      <div className='rafii-quiet sticky top-16 z-10 flex items-center justify-center gap-1 rounded-[var(--rafii-radius-control)] p-1 text-xs lg:hidden' aria-label='Thread navigation'>
        <Button variant='quiet' size='icon-sm' aria-label={syncLabel} aria-pressed={externalState === 'active'} disabled={externalState === 'requesting'} onClick={() => void toggleExternalAudio()}>
          <Icons.music className={`size-4 ${audioActive && !reduceMotion ? 'motion-safe:animate-pulse' : ''}`} />
        </Button>
        <Button variant='quiet' size='icon-sm' aria-label='Previous moment' disabled={activeIndex === 0} onClick={() => jump(items[activeIndex - 1])}><Icons.chevronUp className='size-4' /></Button>
        <button type='button' className='rafii-focus min-h-9 rounded px-3' aria-label={`Open thread map, ${activeIndex + 1} of ${items.length}`} onClick={() => setSheetOpen(true)}>{activeIndex + 1} / {items.length}</button>
        <Button variant='quiet' size='icon-sm' aria-label='Next moment' disabled={activeIndex >= items.length - 1} onClick={() => jump(items[activeIndex + 1])}><Icons.chevronDown className='size-4' /></Button>
      </div>

      <nav aria-label='Thread map' className='pointer-events-none absolute inset-y-0 right-0 hidden w-12 lg:block'>
        <div className='pointer-events-auto sticky top-24 flex max-h-[75vh] flex-col items-end gap-1 py-2'>
          <Button variant='quiet' size='icon-sm' className='mb-1 shrink-0 rounded-full' aria-label={syncLabel} aria-pressed={externalState === 'active'} disabled={externalState === 'requesting'} onClick={() => void toggleExternalAudio()} title={`${syncLabel}. Audio is analysed locally and is not uploaded.`}>
            <Icons.music className={`size-4 ${audioActive && !reduceMotion ? 'motion-safe:animate-pulse' : ''}`} />
          </Button>
          <div
            data-needle-surface='desktop'
            className='flex min-h-0 flex-1 touch-none select-none flex-col items-end justify-center gap-1'
            onPointerMove={(event) => updateNeedleExplore(event, 'desktop')}
            onPointerDown={(event) => handleNeedlePointerDown(event, 'desktop')}
            onPointerUp={(event) => handleNeedlePointerUp(event, 'desktop')}
            onPointerLeave={(event) => {
              if (event.pointerType === 'mouse') setDesktopExplore(null);
            }}
          >
          {groups.map((group, index) => {
            const selected = group.some((item) => navigationId(item) === active);
            const first = group[0];
            const preview = first.excerpt ? (first.excerpt.length > 88 ? `${first.excerpt.slice(0, 88)}…` : first.excerpt) : 'No text';
            const motion = audioActive && !reduceMotion
              ? railMotion[index]
              : {
                  width: selected ? 11 : 4,
                  height: selected ? 1.5 : 1,
                  opacity: selected ? 1 : 0.32,
                  translateX: 0,
                  borderRadius: '9999px',
                  transitionMs: 70,
                  glowPx: 0,
                  haloOpacity: 0,
                  energy: 0,
                  waveformPeak: 0
                };
            const lens = interaction(index, desktopExplore);
            const explored = desktopExplore === index;
            return (
              <div key={navigationId(first)} data-needle-index={index} className='group relative flex w-11 justify-end'>
                <button type='button' aria-label={`${MARKER_LABELS[first.kind]}, turn ${first.seq}${group.length > 1 ? `, ${group.length} turns` : ''}`}
                  aria-expanded={group.length > 1 ? clusterOpen === index : undefined}
                  className={`rafii-focus flex min-h-2 min-w-10 items-center justify-end rounded-full pr-1 ${selected ? 'text-primary' : 'text-muted-foreground/50 hover:text-foreground'}`}
                  onClick={() => group.length === 1 ? jump(first) : setClusterOpen(clusterOpen === index ? null : index)}>
                  <span aria-hidden data-needle-pulse className='block bg-current motion-reduce:transition-none'
                    style={{
                      width: `${motion.width * lens.scale}px`,
                      height: `${motion.height}px`,
                      borderRadius: motion.borderRadius,
                      opacity: explored ? 1 : selected ? 1 : Math.min(1, motion.opacity + lens.proximity * 0.2),
                      transform: `translateX(${motion.translateX + lens.shiftX}px) rotate(${lens.rotate}deg)`,
                      boxShadow: motion.haloOpacity > 0.01 || explored
                        ? `0 0 ${Math.max(motion.glowPx, explored ? 7 : 0)}px rgba(248, 245, 238, ${Math.max(motion.haloOpacity, explored ? 0.18 : 0)})`
                        : 'none',
                      transformOrigin: 'right center',
                      transition: `width ${Math.min(motion.transitionMs, explored ? 28 : motion.transitionMs)}ms linear, opacity ${motion.transitionMs + 8}ms linear, transform ${explored ? 26 : motion.transitionMs}ms cubic-bezier(.22,.9,.3,1), box-shadow 45ms ease-out`,
                      willChange: audioActive || desktopExplore !== null ? 'width, transform, opacity' : undefined,
                    }} />
                </button>
                <button
                  type='button'
                  data-needle-preview
                  className={`rafii-elevated absolute top-1/2 right-full z-20 mr-2 w-56 -translate-y-1/2 rounded-lg p-2 text-left text-xs shadow-lg transition-[opacity,transform] duration-100 ${explored ? 'pointer-events-auto block opacity-100' : 'pointer-events-none hidden opacity-0 group-hover:block group-hover:opacity-100 group-focus-within:block group-focus-within:opacity-100'}`}
                  onClick={() => jump(first)}
                >
                  <p className='font-medium'>{MARKER_LABELS[first.kind]}{group.length > 1 ? ` · ${group.length} turns` : ''}</p>
                  <p className='text-muted-foreground line-clamp-2'>{preview}</p>
                  <p className='text-muted-foreground mt-1 flex items-center justify-between gap-2'>
                    <span>{relativeTime(first.at)}</span>
                    <span className='italic opacity-70'>Jump to message</span>
                  </p>
                </button>
                {clusterOpen === index && group.length > 1 && (
                  <div className='rafii-elevated absolute top-0 right-full z-30 mr-2 max-h-64 w-64 overflow-y-auto rounded-lg p-2 shadow-lg'>
                    {group.map((item) => <button key={navigationId(item)} type='button' className='rafii-focus hover:bg-accent block w-full rounded px-2 py-1.5 text-left text-xs' onClick={() => jump(item)}>
                      <span className='font-medium'>{MARKER_LABELS[item.kind]} · {relativeTime(item.at)}</span><span className='text-muted-foreground block truncate'>{item.excerpt || 'No text'}</span>
                    </button>)}
                  </div>
                )}
              </div>
            );
          })}
          </div>
          {audioActive && <span className='sr-only' aria-live='polite'>{audioSource === 'external' ? 'Thread map is reacting to shared playback audio' : 'Thread map is reacting to Rafii media'}</span>}
        </div>
      </nav>

      <nav aria-label='Thread map mobile rail' className='pointer-events-none absolute inset-y-0 right-0 z-20 w-8 lg:hidden'>
        <div
          data-needle-surface='mobile'
          className='pointer-events-auto sticky top-28 h-[58vh] touch-none select-none'
          onPointerMove={(event) => {
            if (event.pointerType === 'mouse' || touchStart.current?.surface === 'mobile') {
              updateNeedleExplore(event, 'mobile');
            }
          }}
          onPointerDown={(event) => handleNeedlePointerDown(event, 'mobile')}
          onPointerUp={(event) => handleNeedlePointerUp(event, 'mobile')}
          onPointerCancel={() => {
            touchStart.current = null;
            setMobileExplore(null);
          }}
        >
          <div className='absolute inset-y-0 right-0 w-8'>
            {groups.map((group, index) => {
              const selected = group.some((item) => navigationId(item) === active);
              const first = group[0];
              const motion = audioActive && !reduceMotion
                ? railMotion[index]
                : {
                    width: selected ? 11 : 4,
                    height: selected ? 1.5 : 1,
                    opacity: selected ? 1 : 0.32,
                    translateX: 0,
                    borderRadius: '9999px',
                    transitionMs: 70,
                    glowPx: 0,
                    haloOpacity: 0,
                    energy: 0,
                    waveformPeak: 0
                  };
              const lens = interaction(index, mobileExplore);
              const explored = mobileExplore === index;
              const top = groups.length <= 1 ? 50 : (index / (groups.length - 1)) * 100;
              return (
                <button
                  key={`mobile-${navigationId(first)}`}
                  type='button'
                  data-needle-index={index}
                  aria-label={`${MARKER_LABELS[first.kind]}, turn ${first.seq}`}
                  className={`rafii-focus absolute right-0 flex h-6 w-8 -translate-y-1/2 items-center justify-end rounded-full pr-1 ${selected ? 'text-primary' : 'text-muted-foreground/55'}`}
                  style={{ top: `${top}%` }}
                  onFocus={() => setMobileExplore(index)}
                  onBlur={() => setMobileExplore(null)}
                  onClick={() => jump(first)}
                >
                  <span
                    aria-hidden
                    data-needle-pulse-mobile
                    className='block bg-current'
                    style={{
                      width: `${motion.width * lens.scale}px`,
                      height: `${motion.height}px`,
                      borderRadius: '9999px',
                      opacity: explored ? 1 : selected ? 1 : Math.min(1, motion.opacity + lens.proximity * 0.2),
                      transform: `translateX(${motion.translateX + lens.shiftX}px) rotate(${lens.rotate}deg)`,
                      boxShadow: motion.haloOpacity > 0.01 || explored
                        ? `0 0 ${Math.max(motion.glowPx, explored ? 7 : 0)}px rgba(248, 245, 238, ${Math.max(motion.haloOpacity, explored ? 0.18 : 0)})`
                        : 'none',
                      transformOrigin: 'right center',
                      transition: `width ${Math.min(motion.transitionMs, explored ? 28 : motion.transitionMs)}ms linear, opacity 45ms linear, transform ${explored ? 26 : motion.transitionMs}ms cubic-bezier(.22,.9,.3,1), box-shadow 45ms ease-out`
                    }}
                  />
                </button>
              );
            })}
          </div>
          {mobileExplore !== null && groups[mobileExplore]?.[0] && (() => {
            const group = groups[mobileExplore];
            const first = group[0];
            const preview = first.excerpt
              ? first.excerpt.length > 96 ? `${first.excerpt.slice(0, 96)}…` : first.excerpt
              : 'No text';
            const top = groups.length <= 1 ? 50 : (mobileExplore / (groups.length - 1)) * 100;
            return (
              <button
                type='button'
                data-needle-mobile-preview
                className='rafii-elevated pointer-events-auto absolute right-9 z-40 w-56 max-w-[calc(100vw-3.25rem)] -translate-y-1/2 rounded-xl p-3 text-left text-xs shadow-xl'
                style={{ top: `${Math.max(8, Math.min(92, top))}%` }}
                onClick={() => jump(first)}
              >
                <p className='font-medium'>{MARKER_LABELS[first.kind]}{group.length > 1 ? ` · ${group.length} turns` : ''}</p>
                <p className='text-muted-foreground mt-1 line-clamp-3'>{preview}</p>
                <p className='text-muted-foreground mt-2 flex items-center justify-between gap-2'>
                  <span>{relativeTime(first.at)}</span>
                  <span className='italic opacity-70'>Tap to jump</span>
                </p>
              </button>
            );
          })()}
        </div>
      </nav>

      <Sheet open={sheetOpen} onOpenChange={setSheetOpen}>
        <SheetContent side='bottom' className='max-h-[85dvh] rounded-t-[var(--rafii-radius-dialog)]'>
          <SheetHeader><SheetTitle>Thread map</SheetTitle><SheetDescription>Choose a moment to jump to its exact turn.</SheetDescription></SheetHeader>
          <div className='overflow-y-auto px-4 pb-[calc(1rem+env(safe-area-inset-bottom))]'>
            {groups.map((group, index) => <div key={navigationId(group[0])}>
              {group.length > 1 && <button type='button' className='rafii-focus hover:bg-accent flex min-h-11 w-full items-center justify-between rounded px-2 text-left text-sm' aria-expanded={mobileGroup === index} onClick={() => setMobileGroup(mobileGroup === index ? null : index)}>
                <span>{group[0].seq}–{group[group.length - 1].seq} · {group.length} moments</span><Icons.chevronDown className='size-4' />
              </button>}
              {(group.length === 1 || mobileGroup === index) && group.map((item) => <button key={navigationId(item)} type='button' className='rafii-focus hover:bg-accent block min-h-11 w-full rounded px-2 py-2 text-left' onClick={() => jump(item)}>
                <span className='text-xs font-medium'>{MARKER_LABELS[item.kind]} · {relativeTime(item.at)}</span><span className='text-muted-foreground block truncate text-xs'>{item.excerpt || 'No text'}</span>
              </button>)}
            </div>)}
          </div>
        </SheetContent>
      </Sheet>
    </>
  );
}
