'use client';

import { useEffect, useMemo, useState } from 'react';
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
          <div className='flex min-h-0 flex-1 flex-col items-end justify-center gap-1'>
          {groups.map((group, index) => {
            const selected = group.some((item) => navigationId(item) === active);
            const first = group[0];
            const preview = first.excerpt ? (first.excerpt.length > 88 ? `${first.excerpt.slice(0, 88)}…` : first.excerpt) : 'No text';
            const motion = audioActive && !reduceMotion
              ? railMotion[index]
              : {
                  width: selected ? 8 : 6,
                  height: selected ? 8 : 6,
                  opacity: selected ? 1 : 0.58,
                  translateX: 0,
                  borderRadius: '9999px',
                  transitionMs: 70
                };
            return (
              <div key={navigationId(first)} className='group relative flex w-11 justify-end'>
                <button type='button' aria-label={`${MARKER_LABELS[first.kind]}, turn ${first.seq}${group.length > 1 ? `, ${group.length} turns` : ''}`}
                  aria-expanded={group.length > 1 ? clusterOpen === index : undefined}
                  className={`rafii-focus flex min-h-2 min-w-10 items-center justify-end rounded-full pr-1 ${selected ? 'text-primary' : 'text-muted-foreground/50 hover:text-foreground'}`}
                  onClick={() => group.length === 1 ? jump(first) : setClusterOpen(clusterOpen === index ? null : index)}>
                  <span aria-hidden className='block bg-current motion-reduce:transition-none'
                    style={{
                      width: `${motion.width}px`,
                      height: `${motion.height}px`,
                      borderRadius: motion.borderRadius,
                      opacity: selected ? 1 : motion.opacity,
                      transform: motion.translateX > 0 ? `translateX(${motion.translateX}px)` : undefined,
                      transformOrigin: 'right center',
                      transition: `width ${motion.transitionMs}ms linear, height ${motion.transitionMs}ms linear, border-radius ${motion.transitionMs + 12}ms ease-out, opacity ${motion.transitionMs + 8}ms linear, transform ${motion.transitionMs}ms linear`,
                      willChange: audioActive && !reduceMotion ? 'width, height, transform' : undefined,
                    }} />
                </button>
                <div className='rafii-elevated pointer-events-none absolute top-1/2 right-full z-20 mr-2 hidden w-52 -translate-y-1/2 rounded-lg p-2 text-xs group-hover:block group-focus-within:block'>
                  <p className='font-medium'>{MARKER_LABELS[first.kind]}{group.length > 1 ? ` · ${group.length} turns` : ''}</p>
                  <p className='text-muted-foreground line-clamp-2'>{preview}</p>
                  <p className='text-muted-foreground'>{relativeTime(first.at)}</p>
                </div>
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
