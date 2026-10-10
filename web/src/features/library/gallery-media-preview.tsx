'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore, type PointerEvent as ReactPointerEvent, type RefObject } from 'react';
import Image from 'next/image';
import { useQuery } from '@tanstack/react-query';
import { useInView } from 'motion/react';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useNowPlaying } from '@/lib/media/now-playing';
import { IconControl } from './ui/controls';
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover';
import { ProgressScrubber, ScrubWaveform, useAudioPeaks } from './scrub-waveform';
import type { LibraryAsset } from './use-library';

const PLAY_EVENT = 'rafii-library-inline-play';
const timeLabel = (seconds: number) => {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
};

/*
 * One silent video preview at a time (redesign §5): the first visible video — or the one under the pointer or focus —
 * holds the slot; every other card keeps its real poster until pressed. Bounded concurrency without losing the
 * motion-allowed silent preview.
 */
let silentOwner: string | null = null;
const silentListeners = new Set<() => void>();
function setSilentOwner(next: string | null) {
  if (silentOwner === next) return;
  silentOwner = next;
  for (const listener of silentListeners) listener();
}
function claimSilent(slot: string, force = false) {
  if (silentOwner === slot || (silentOwner && !force)) return;
  setSilentOwner(slot);
}
function releaseSilent(slot: string) {
  if (silentOwner === slot) setSilentOwner(null);
}
function useSilentOwner() {
  return useSyncExternalStore(
    (listener) => {
      silentListeners.add(listener);
      return () => silentListeners.delete(listener);
    },
    () => silentOwner,
    () => null
  );
}

/** Width of an element, kept current (0 until measured). */
function useWidth(element: RefObject<HTMLElement | null>) {
  const [width, setWidth] = useState(0);
  useEffect(() => {
    const node = element.current;
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => setWidth(Math.round(entry.contentRect.width)));
    observer.observe(node);
    return () => observer.disconnect();
  }, [element]);
  return width;
}

/** Below this width a tile shows the whole recording at once (tap or drag to a point) instead of a scrolling window. */
const TIGHT_TILE = 220;

/**
 * Private, source-backed playback in three layouts: a gallery `tile` (any density), a list `row`, and the asset
 * `detail` sheet. Every layout keeps play, the current time and a way to move through the media in view; speed and
 * volume sit in a popover so nothing in a small tile overlaps.
 */
export function GalleryMediaPreview({ asset, video = false, posterUrl, compact = false, enabled = true, variant }: {
  asset: LibraryAsset; video?: boolean; posterUrl?: string;
  /** Kept for list rows; same as `variant='row'`. */
  compact?: boolean;
  enabled?: boolean;
  variant?: 'tile' | 'row' | 'detail';
}) {
  const layout = variant ?? (compact ? 'row' : 'tile');
  const { api, workspaceId } = useWorkspaceApi();
  const slot = useId();
  // Motion 11 snapshots this preference; media playback must follow live OS changes.
  const [reduce, setReduce] = useState(true);
  const container = useRef<HTMLDivElement>(null);
  const media = useRef<HTMLMediaElement | null>(null);
  const visible = useInView(container, { amount: 0.25 });
  const [foreground, setForeground] = useState(true);
  const [activated, setActivated] = useState(false);
  const [userPaused, setUserPaused] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const savedPosition = useRef(0);
  const loadedSource = useRef<string | undefined>(undefined);
  const restorePosition = useRef<{ value: number; applied: boolean } | null>(null);
  const [duration, setDuration] = useState(asset.duration || 0);
  const [metadataReady, setMetadataReady] = useState(false);
  const [rate, setRate] = useState(1);
  const [volume, setVolume] = useState(video ? 0 : 0.8);
  const [failure, setFailure] = useState('');
  const [refreshAttempts, setRefreshAttempts] = useState(0);
  const [primed, setPrimed] = useState(false);
  const owner = useSilentOwner();
  const ownsSilent = video && owner === slot;
  const title = asset.displayTitle || asset.originalFilename || (video ? 'Video' : 'Audio');
  const ready = !asset.processing || ['ready', 'unsupported'].includes(asset.processing);
  const active = enabled && ready && (activated || visible);
  const source = useQuery<{ url: string; mime: string }>({
    queryKey: ['library-inline-source', workspaceId, asset.id, video],
    queryFn: async () => {
      const result = await (video ? api.mediaUrl(workspaceId, asset.id) : api.libraryFileUrl(workspaceId, asset.id));
      return { url: result.url, mime: result.mime };
    },
    enabled: Boolean(workspaceId) && active && (!video || activated || ownsSilent || primed),
    staleTime: 3 * 60_000,
    refetchInterval: active ? 4 * 60_000 : false,
    retry: 1
  });
  // A video gets its source only once it may play (the slot or a press); after that it keeps it, so a paused preview
  // can still seek. Other tiles stay on their poster without loading a player.
  useEffect(() => {
    if (video && (ownsSilent || activated) && !primed) setPrimed(true);
  }, [video, ownsSilent, activated, primed]);
  const playbackUrl = video ? (primed && active ? source.data?.url : undefined) : source.data?.url;
  useLayoutEffect(() => {
    if (loadedSource.current === playbackUrl) return;
    // Changing src resets native time before metadata arrives. Preserve the last
    // settled position before the reset's queued timeupdate can overwrite it.
    if (loadedSource.current || restorePosition.current) {
      restorePosition.current = { value: savedPosition.current, applied: false };
    }
    loadedSource.current = playbackUrl;
    setMetadataReady(false);
  }, [playbackUrl]);
  // Every length and format the Library keeps: read piece by piece after the person first plays or opens the waveform.
  const waveform = useAudioPeaks(`${workspaceId}:${asset.id}:${asset.hash ?? ''}`, source.data?.url, !video && activated, duration);
  const scrub = useRef<{ resume: boolean; seekedAt: number } | null>(null);
  useEffect(() => {
    const preference = window.matchMedia('(prefers-reduced-motion: reduce)');
    const update = () => setReduce(preference.matches);
    update(); preference.addEventListener('change', update);
    return () => preference.removeEventListener('change', update);
  }, []);
  useEffect(() => {
    const update = () => setForeground(document.visibilityState === 'visible');
    update(); document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
  // Ask for the silent slot while this video could preview; give it back otherwise (the next visible video takes it).
  useEffect(() => {
    if (!video) return;
    const eligible = enabled && ready && visible && foreground && !reduce && !userPaused && !activated;
    if (eligible) claimSilent(slot);
    else releaseSilent(slot);
  }, [video, enabled, ready, visible, foreground, reduce, userPaused, activated, slot, owner]);
  useEffect(() => () => releaseSilent(slot), [slot]);
  useEffect(() => {
    const pauseOther = (event: Event) => {
      if ((event as CustomEvent<string>).detail !== asset.id && media.current && !media.current.muted) {
        media.current.pause(); setUserPaused(true);
      }
    };
    window.addEventListener(PLAY_EVENT, pauseOther);
    return () => { window.removeEventListener(PLAY_EVENT, pauseOther); };
  }, [asset.id]);
  useEffect(() => useNowPlaying.subscribe((state, previous) => {
    if (state.playing && (!previous.playing || state.track !== previous.track) && media.current && !media.current.muted) {
      media.current.pause(); setUserPaused(true);
    }
  }), []);
  useEffect(() => {
    const element = media.current;
    if (!element) return;
    element.volume = volume;
    element.muted = volume === 0;
    element.playbackRate = rate;
  }, [volume, rate, source.data?.url]);
  useEffect(() => {
    const element = media.current;
    if (!element) return;
    const shouldPlay = active && foreground && !userPaused && (video ? visible && (activated || ownsSilent) : activated);
    if (shouldPlay && playbackUrl) {
      void element.play().catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setPlaying(false);
        setFailure('Press play to preview');
      });
    } else element.pause();
  }, [active, foreground, userPaused, video, visible, activated, ownsSilent, playbackUrl]);
  useEffect(() => {
    const element = media.current;
    return () => { element?.pause(); element?.removeAttribute('src'); element?.load(); };
  }, []);

  const announcePlay = () => {
    if (volume > 0) {
      useNowPlaying.getState().setPlaying(false);
      window.dispatchEvent(new CustomEvent(PLAY_EVENT, { detail: asset.id }));
    }
  };
  const toggle = () => {
    setFailure('');
    if (playing) { media.current?.pause(); setUserPaused(true); }
    else {
      setActivated(true); setUserPaused(false); announcePlay();
      if (media.current && source.data?.url) void media.current.play().catch(() => setFailure('Playback unavailable in this browser'));
      if (source.isError) void source.refetch();
    }
  };
  const seek = (value: number) => {
    if (!media.current || !Number.isFinite(duration) || duration <= 0) return;
    restorePosition.current = null; savedPosition.current = value;
    media.current.currentTime = value; setPosition(value);
  };
  // Voice Memos-style scrubbing: playback pauses under the finger, the audible position follows (throttled), and
  // playback resumes where the drag or flick settles.
  const scrubStart = () => {
    const element = media.current;
    if (!element) return;
    scrub.current = { resume: !element.paused, seekedAt: 0 };
    if (!element.paused) element.pause();
  };
  const scrubTo = (value: number) => {
    const element = media.current;
    if (!element || !scrub.current) return;
    restorePosition.current = null; savedPosition.current = value; setPosition(value);
    const now = performance.now();
    if (now - scrub.current.seekedAt > 80) {
      scrub.current.seekedAt = now;
      if (typeof element.fastSeek === 'function') element.fastSeek(value); else element.currentTime = value;
    }
  };
  const scrubEnd = (value: number) => {
    const resume = scrub.current?.resume;
    scrub.current = null;
    seek(value);
    if (resume && media.current) { announcePlay(); void media.current.play().catch(() => setFailure('Playback unavailable in this browser')); }
  };
  const onMetadata = () => {
    const element = media.current;
    if (!element) return;
    setDuration(Number.isFinite(element.duration) ? element.duration : 0); setMetadataReady(true);
    const pending = restorePosition.current;
    if (pending && Number.isFinite(element.duration)) {
      const target = Math.max(0, Math.min(pending.value, element.duration));
      if (Math.abs(element.currentTime - target) > 0.001) {
        pending.applied = true; element.currentTime = target;
        savedPosition.current = target; setPosition(target);
      } else {
        restorePosition.current = null; savedPosition.current = target; setPosition(target);
      }
    }
    element.volume = volume; element.muted = volume === 0; element.playbackRate = rate;
  };
  const onError = () => {
    setPlaying(false);
    if (refreshAttempts < 1) { setRefreshAttempts(value => value + 1); void source.refetch(); }
    else setFailure('Playback unavailable in this browser. Open the original to use another player.');
  };
  const mediaEvents = {
    onLoadedMetadata: onMetadata,
    onDurationChange: () => { if (media.current && Number.isFinite(media.current.duration)) setDuration(media.current.duration); },
    onTimeUpdate: () => {
      const element = media.current;
      if (!element || element.readyState === 0 || element.seeking || restorePosition.current || scrub.current) return;
      savedPosition.current = element.currentTime; setPosition(element.currentTime);
    },
    onSeeked: () => {
      const element = media.current;
      if (!element || element.readyState === 0 || scrub.current || (restorePosition.current && !restorePosition.current.applied)) return;
      restorePosition.current = null;
      savedPosition.current = element.currentTime; setPosition(element.currentTime);
    },
    onPlay: () => { setPlaying(true); setFailure(''); announcePlay(); },
    onPause: () => setPlaying(false),
    onEnded: () => { setPlaying(false); setUserPaused(true); },
    onError
  };
  const busy = activated && source.isFetching && !source.data;
  const knownDuration = duration > 0 ? duration : (asset.duration ?? 0);
  const width = useWidth(container);
  const tile = layout === 'tile', detail = layout === 'detail';
  const tight = tile && width > 0 && width < TIGHT_TILE;
  const noun = video ? 'video' : 'audio';
  const valueText = `${timeLabel(position)} of ${duration || knownDuration ? timeLabel(duration || knownDuration) : 'unknown length'}`;
  const seekable = metadataReady && duration > 0;
  const scrubProps = { onScrubStart: scrubStart, onScrub: scrubTo, onScrubEnd: scrubEnd, onSeek: seek };
  // Small tiles: the waveform is the whole recording (it is the timeline). Larger: a Voice Memos window plus a thin
  // whole-length timeline underneath, so the place in the file is always visible.
  const waveMode = tight ? 'overview' : 'scroll';
  const showTimeline = video || (activated && waveMode === 'scroll');
  const message = source.isError || failure
    ? failure || 'Private preview unavailable. Press play to retry.'
    : !video && waveform.status === 'error' ? `${waveform.error} Playback and the timeline still work.` : '';

  const playButton = (
    <button type='button' onClick={toggle} disabled={!ready || busy} aria-label={`${playing ? 'Pause' : 'Play'} ${noun} preview`} className={cn('rafii-focus hover:bg-foreground/[0.08] flex shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:opacity-50', detail ? 'bg-foreground text-background hover:bg-foreground/90 size-11' : tile ? 'size-8' : 'size-9 pointer-coarse:size-10')}>
      {busy ? <Icons.spinner aria-hidden className='size-4 animate-spin motion-reduce:animate-none' /> : playing ? <Icons.pause aria-hidden className='size-4' /> : <Icons.play aria-hidden className='size-4' />}
    </button>
  );
  // The current time is always shown; the total gives way first in a very narrow tile.
  const clock = (
    <span className={cn('min-w-0 flex-1 truncate tabular-nums', detail ? 'text-sm' : 'text-[11px]')}>
      <span className='text-foreground font-medium'>{timeLabel(position)}</span>
      <span className='text-muted-foreground @max-[7.5rem]:hidden'> / {duration || knownDuration ? timeLabel(duration || knownDuration) : '–:––'}</span>
    </span>
  );
  const options = (
    <Popover>
      <PopoverTrigger render={<IconControl label='Playback options' size='sm' tooltip={false} className={cn('shrink-0', tile && 'size-7')} />}>
        <Icons.adjustments aria-hidden />
      </PopoverTrigger>
      <PopoverContent side='top' align='end' className='w-60 gap-3 p-3'>
        <label className='flex items-center justify-between gap-3 text-xs'>
          <span className='text-muted-foreground'>Speed</span>
          <select aria-label={`${video ? 'Video' : 'Audio'} playback speed`} value={rate} onChange={event => setRate(Number(event.target.value))} className='rafii-focus bg-foreground/[0.06] h-8 rounded-md px-2 text-xs pointer-coarse:h-10'>
            {[0.5, 0.75, 1, 1.25, 1.5, 2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}
          </select>
        </label>
        <label className='flex items-center gap-2 text-xs'>
          <span className='text-muted-foreground shrink-0'>Volume</span>
          <input type='range' min={0} max={1} step={0.05} value={volume} aria-label={`${video ? 'Video' : 'Audio'} preview volume`} aria-valuetext={`${Math.round(volume * 100)} percent`} onChange={event => { setVolume(Number(event.target.value)); if (Number(event.target.value) > 0) { useNowPlaying.getState().setPlaying(false); window.dispatchEvent(new CustomEvent(PLAY_EVENT, { detail: asset.id })); } }} className='rafii-focus accent-foreground h-8 min-w-0 flex-1 cursor-pointer' />
          <span className='w-9 shrink-0 text-right tabular-nums'>{Math.round(volume * 100)}%</span>
        </label>
      </PopoverContent>
    </Popover>
  );
  const timeline = showTimeline ? <ProgressScrubber duration={duration} position={position} disabled={!seekable} label={`${video ? 'Video' : 'Audio'} preview timeline`} valueText={valueText} {...scrubProps} /> : null;

  const audioArea = !video ? (activated ? (
    <ScrubWaveform
      snapshot={waveform.snapshot}
      duration={duration}
      position={position}
      media={media}
      playing={playing}
      reduce={reduce}
      mode={waveMode}
      className={detail ? 'h-28' : tile ? 'h-full' : 'h-14'}
      disabled={!seekable}
      label={waveMode === 'overview' ? `Audio waveform: tap or drag to move through ${title}` : `Audio waveform: drag left or right to move through ${title}`}
      valueText={valueText}
      {...scrubProps}
    />
  ) : (
    <button type='button' onClick={() => { setActivated(true); setUserPaused(true); }} disabled={!ready} className={cn('rafii-focus text-muted-foreground hover:text-foreground flex h-full w-full items-center justify-center gap-2 rounded-md p-2 text-center transition-colors duration-150', tile ? 'flex-col' : 'flex-row', detail && 'min-h-28')}>
      <Icons.music aria-hidden className={detail ? 'size-8' : tight ? 'size-5' : 'size-6'} />
      <span className={detail ? 'text-sm' : 'text-xs tabular-nums'}>{knownDuration > 0 ? (tight ? timeLabel(knownDuration) : `Audio · ${timeLabel(knownDuration)}`) : 'Audio'}</span>
      <span className={detail ? 'text-xs' : 'sr-only'}>Show waveform</span>
    </button>
  )) : null;

  const videoArea = video ? <>
    {posterUrl ? <Image src={posterUrl} alt='' fill unoptimized sizes={tile ? '400px' : '640px'} className='object-contain' /> : <Icons.video aria-hidden className='text-muted-foreground size-8' />}
    {/* Uploaded originals do not provide a timed caption track. Never fabricate one;
        audio transcripts can be imported/read through the asset details. */}
    {/* oxlint-disable-next-line jsx-a11y/media-has-caption */}
    <video ref={node => { media.current = node; }} src={playbackUrl} poster={posterUrl} muted={volume === 0} playsInline loop preload='metadata' aria-label={`Video preview of ${title}`} {...mediaEvents} className='absolute inset-0 h-full w-full object-contain' />
    {playing && volume === 0 && !tight ? <span className='bg-background/70 pointer-events-none absolute top-2 left-2 rounded-full px-2 py-0.5 text-[10px] font-medium backdrop-blur-md'>Silent preview</span> : null}
  </> : null;
  // An audio-only upload has no timed captions; its optional imported transcript remains available in details.
  // oxlint-disable-next-line jsx-a11y/media-has-caption
  const audioElement = !video ? <audio ref={node => { media.current = node; }} src={playbackUrl} preload={activated ? 'metadata' : 'none'} {...mediaEvents} /> : null;

  const root = {
    ref: container,
    role: 'group',
    'data-library-media-player': video ? 'video' : 'audio',
    'data-library-thumbnail': video ? 'video' : (asset.extension || 'audio'),
    'data-thumbnail-preview': video ? 'video-poster' : 'audio-player',
    'data-player-layout': tight ? 'tile-tight' : layout,
    'aria-label': `${video ? 'Video' : 'Audio'} preview: ${title}`,
    onPointerEnter: (event: ReactPointerEvent) => { if (video && event.pointerType === 'mouse' && !reduce && !userPaused && !activated) claimSilent(slot, true); },
    onFocus: () => { if (video && !reduce && !userPaused && !activated) claimSilent(slot, true); }
  } as const;

  if (tile) {
    // Gallery tile: the media fills a 4:3 box; a frosted bar keeps play, time and options in one line at any width.
    return (
      <div {...root} className='bg-foreground/[0.035] @container relative aspect-[4/3] min-w-0 overflow-hidden'>
        {videoArea}
        {audioElement}
        {!video ? <div className={cn('absolute inset-x-2 top-2', showTimeline ? 'bottom-[3.75rem]' : 'bottom-11')}>{audioArea}</div> : null}
        {timeline ? <div className='absolute inset-x-2 bottom-9 z-10'>{timeline}</div> : null}
        {message ? <p role='status' className='bg-background/75 text-muted-foreground absolute top-1.5 right-10 left-1.5 z-10 line-clamp-2 rounded-md px-1.5 py-0.5 text-[10px] backdrop-blur-md'>{message}</p> : null}
        <div className='bg-background/70 border-foreground/[0.06] absolute inset-x-0 bottom-0 z-10 flex h-9 min-w-0 items-center gap-0.5 border-t px-1 backdrop-blur-md'>
          {playButton}
          {clock}
          {options}
        </div>
      </div>
    );
  }
  // List row and detail sheet: waveform or picture, the whole-length timeline, then one control line.
  return (
    <div {...root} className={cn('@container flex min-w-0 flex-col', detail ? 'gap-2' : 'bg-foreground/[0.035] gap-0.5 rounded-[var(--rafii-radius-control)] px-1 pb-1')}>
      {video ? <div className={cn('relative flex items-center justify-center overflow-hidden', detail ? 'bg-foreground/[0.035] aspect-video max-h-[44vh] rounded-[var(--rafii-radius-card)]' : 'aspect-video max-h-48')}>{videoArea}</div> : null}
      {audioElement}
      {!video ? <div className={cn('flex items-center', detail ? 'bg-foreground/[0.035] min-h-28 rounded-[var(--rafii-radius-card)] px-3 py-2' : 'min-h-14 px-2 pt-1')}>{audioArea}</div> : null}
      {timeline ? <div className={detail ? 'px-1' : 'px-2'}>{timeline}</div> : null}
      <div className='flex min-w-0 items-center gap-1.5 px-1'>
        {playButton}
        {clock}
        {options}
      </div>
      {detail && activated && !video && waveform.status !== 'error' ? <p className='text-muted-foreground px-1 text-xs'>Drag the waveform left or right to move through the recording.</p> : null}
      {message ? <p role='status' className='text-muted-foreground px-1 pb-1 text-[11px]'>{message}</p> : null}
    </div>
  );
}
