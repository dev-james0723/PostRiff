'use client';

import { useEffect, useId, useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react';
import Image from 'next/image';
import { useQuery } from '@tanstack/react-query';
import { useInView } from 'motion/react';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useNowPlaying } from '@/lib/media/now-playing';
import { IconControl } from './ui/controls';
import { ScrubWaveform, useAudioPeaks } from './scrub-waveform';
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

/**
 * Private, source-backed playback inside a gallery tile or a list row. Play, time and the timeline stay visible; speed
 * and volume sit behind Playback options so a tile never turns into a control panel.
 */
export function GalleryMediaPreview({ asset, video = false, posterUrl, compact = false, enabled = true }: {
  asset: LibraryAsset; video?: boolean; posterUrl?: string; compact?: boolean; enabled?: boolean;
}) {
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
  const [options, setOptions] = useState(false);
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
  return (
    <div
      ref={container}
      role='group'
      data-library-media-player={video ? 'video' : 'audio'}
      data-library-thumbnail={video ? 'video' : (asset.extension || 'audio')}
      data-thumbnail-preview={video ? 'video-poster' : 'audio-player'}
      aria-label={`${video ? 'Video' : 'Audio'} preview: ${title}`}
      onPointerEnter={(event) => { if (video && event.pointerType === 'mouse' && !reduce && !userPaused && !activated) claimSilent(slot, true); }}
      onFocus={() => { if (video && !reduce && !userPaused && !activated) claimSilent(slot, true); }}
      className={cn('bg-foreground/[0.035] relative flex min-w-0 flex-col overflow-hidden', compact ? 'rounded-[var(--rafii-radius-control)]' : 'aspect-[4/3]')}
    >
      <div className={cn('relative flex min-h-0 flex-1 items-center justify-center', compact ? (video ? 'aspect-video max-h-48' : 'min-h-14') : 'pb-11')}>
        {video ? <>
          {posterUrl ? <Image src={posterUrl} alt='' fill unoptimized sizes={compact ? '320px' : '400px'} className='object-contain' /> : <Icons.video aria-hidden className='text-muted-foreground size-8' />}
          {/* Uploaded originals do not provide a timed caption track. Never fabricate one;
              audio transcripts can be imported/read through the asset details. */}
          {/* oxlint-disable-next-line jsx-a11y/media-has-caption */}
          <video ref={node => { media.current = node; }} src={playbackUrl} poster={posterUrl} muted={volume === 0} playsInline loop preload='metadata' aria-label={`Video preview of ${title}`} {...mediaEvents} className='absolute inset-0 h-full w-full object-contain' />
          {playing && volume === 0 ? <span className='bg-background/85 pointer-events-none absolute top-2 left-2 rounded-full px-2 py-0.5 text-[10px] font-medium'>Silent preview</span> : null}
          {!playing && knownDuration > 0 ? <span className='bg-background/85 pointer-events-none absolute top-2 right-2 rounded-full px-1.5 py-0.5 text-[11px] font-medium tabular-nums'>{timeLabel(knownDuration)}</span> : null}
        </> : <>
          {/* An audio-only upload has no timed captions; its optional imported transcript
              remains available in details, rather than inventing synchronization. */}
          {/* oxlint-disable-next-line jsx-a11y/media-has-caption */}
          <audio ref={node => { media.current = node; }} src={playbackUrl} preload={activated ? 'metadata' : 'none'} {...mediaEvents} />
          {activated ? <div className='w-full px-3'>
            <ScrubWaveform
              snapshot={waveform.snapshot}
              duration={duration}
              position={position}
              media={media}
              playing={playing}
              reduce={reduce}
              compact={compact}
              disabled={!metadataReady || !duration}
              label={`Audio waveform: drag left or right to move through ${title}`}
              valueText={`${timeLabel(position)} of ${duration ? timeLabel(duration) : 'unknown length'}`}
              onScrubStart={scrubStart}
              onScrub={scrubTo}
              onScrubEnd={scrubEnd}
              onSeek={seek}
            />
          </div> : <button type='button' onClick={() => { setActivated(true); setUserPaused(true); }} disabled={!ready} className={cn('rafii-focus text-muted-foreground hover:text-foreground flex items-center gap-2 rounded-md p-3 text-center transition-colors duration-150', compact ? 'flex-row' : 'flex-col')}>
            <Icons.music aria-hidden className={compact ? 'size-5' : 'size-7'} />
            <span className='text-xs'>{knownDuration > 0 ? `Audio · ${timeLabel(knownDuration)}` : 'Listen to this audio'}</span>
            <span className='sr-only'>Show waveform</span>
          </button>}
        </>}
      </div>
      <div className={cn('bg-card/95 z-10 flex min-w-0 flex-col', compact ? 'px-1' : 'absolute inset-x-0 bottom-0 border-t border-foreground/[0.06]')}>
        {/* A container: in a narrow card the time label gives way so the timeline stays usable (the slider still says "x of y"). */}
        <div className='@container flex min-w-0 items-center gap-1 px-1'>
          <button type='button' onClick={toggle} disabled={!ready || busy} aria-label={`${playing ? 'Pause' : 'Play'} ${video ? 'video' : 'audio'} preview`} className='rafii-focus hover:bg-foreground/[0.06] flex size-9 shrink-0 items-center justify-center rounded-full transition-colors duration-150 disabled:opacity-50 pointer-coarse:size-11'>
            {busy ? <Icons.spinner aria-hidden className='size-4 animate-spin motion-reduce:animate-none' /> : playing ? <Icons.pause aria-hidden className='size-4' /> : <Icons.play aria-hidden className='size-4' />}
          </button>
          <input type='range' min={0} max={duration || 1} step={0.05} value={Math.min(position, duration || 1)} onChange={event => seek(Number(event.target.value))} disabled={!metadataReady || !duration} aria-label={`${video ? 'Video' : 'Audio'} preview timeline`} aria-valuetext={`${timeLabel(position)} of ${duration || knownDuration ? timeLabel(duration || knownDuration) : 'unknown length'}`} className='rafii-focus accent-foreground h-9 min-w-0 flex-1 cursor-pointer disabled:cursor-default pointer-coarse:h-11' />
          <span className='text-muted-foreground shrink-0 px-1 text-[11px] tabular-nums @max-[15rem]:hidden'>
            {/* The length is shown once it is known (from the file or its metadata), never as a made-up 0:00. */}
            {timeLabel(position)} / {duration || knownDuration ? timeLabel(duration || knownDuration) : '–:––'}
          </span>
          <IconControl label='Playback options' size='sm' tooltip={false} aria-expanded={options} active={options} onClick={() => setOptions(value => !value)}>
            <Icons.adjustments aria-hidden />
          </IconControl>
        </div>
        {options ? (
          <div className='flex min-w-0 flex-wrap items-center gap-x-3 gap-y-1 px-2 pb-1.5'>
            <label className='text-muted-foreground flex items-center gap-1.5 text-[11px]'>
              <span>Speed</span>
              <select aria-label={`${video ? 'Video' : 'Audio'} playback speed`} value={rate} onChange={event => setRate(Number(event.target.value))} className='rafii-focus h-8 rounded-md bg-transparent px-1 text-xs pointer-coarse:h-11'>
                {[0.5,0.75,1,1.25,1.5,2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}
              </select>
            </label>
            <label className='text-muted-foreground flex min-w-0 flex-1 items-center gap-2 text-[11px]'>
              <span>Volume</span>
              <input type='range' min={0} max={1} step={0.05} value={volume} aria-label={`${video ? 'Video' : 'Audio'} preview volume`} aria-valuetext={`${Math.round(volume * 100)} percent`} onChange={event => { setVolume(Number(event.target.value)); if (Number(event.target.value) > 0) { useNowPlaying.getState().setPlaying(false); window.dispatchEvent(new CustomEvent(PLAY_EVENT, { detail: asset.id })); } }} className='rafii-focus accent-foreground h-8 min-w-0 flex-1 cursor-pointer pointer-coarse:h-11' />
              <span className='w-8 text-right tabular-nums'>{Math.round(volume * 100)}%</span>
            </label>
          </div>
        ) : null}
        {(source.isError || failure) ? <p role='status' className='text-muted-foreground px-2 pb-1.5 text-[11px]'>{failure || 'Private preview unavailable. Press play to retry.'}</p> : null}
        {!video && waveform.status === 'error' ? <p className='text-muted-foreground px-2 pb-1.5 text-[11px]'>{waveform.error} Playback and the timeline still work.</p> : null}
      </div>
    </div>
  );
}
