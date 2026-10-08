'use client';

import { useEffect, useRef, useState } from 'react';
import Image from 'next/image';
import { useQuery } from '@tanstack/react-query';
import { useInView, useReducedMotion } from 'motion/react';
import { Icons } from '@/components/icons';
import { cn } from '@/lib/utils';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { useNowPlaying } from '@/lib/media/now-playing';
import type { LibraryAsset } from './use-library';

const WAVEFORM_BYTE_LIMIT = 16 * 1024 * 1024;
const WAVEFORM_DURATION_LIMIT = 300;
const PLAY_EVENT = 'rafii-library-inline-play';
const timeLabel = (seconds: number) => {
  const value = Number.isFinite(seconds) ? Math.max(0, Math.floor(seconds)) : 0;
  return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, '0')}`;
};

/** Download/decode only after the user plays audio, with bounded bytes/duration/sample rate. */
async function sourceWaveform(url: string, signal: AbortSignal): Promise<number[]> {
  const response = await fetch(url, { signal });
  if (!response.ok || !response.body || Number(response.headers.get('content-length') || 0) > WAVEFORM_BYTE_LIMIT) throw new Error('Waveform unavailable');
  const reader = response.body.getReader();
  const chunks: Uint8Array[] = [];
  let length = 0;
  try {
    while (true) {
      const part = await reader.read();
      if (part.done) break;
      length += part.value.byteLength;
      if (length > WAVEFORM_BYTE_LIMIT) throw new Error('Waveform unavailable');
      chunks.push(part.value);
    }
  } finally {
    await reader.cancel().catch(() => undefined);
    reader.releaseLock();
  }
  signal.throwIfAborted();
  const bytes = new Uint8Array(length);
  let offset = 0;
  for (const chunk of chunks) { bytes.set(chunk, offset); offset += chunk.byteLength; }
  const context = new AudioContext({ sampleRate: 22050 });
  try {
    const audio = await context.decodeAudioData(bytes.buffer);
    signal.throwIfAborted();
    if (audio.duration > WAVEFORM_DURATION_LIMIT) throw new Error('Waveform unavailable');
    const channels = Array.from({ length: Math.min(audio.numberOfChannels, 2) }, (_, channel) => audio.getChannelData(channel));
    const peaks = Array.from({ length: 96 }, (_, bin) => {
      const start = Math.floor(bin * audio.length / 96), end = Math.floor((bin + 1) * audio.length / 96);
      let peak = 0;
      const stride = Math.max(1, Math.floor((end - start) / 1024));
      for (const channel of channels) for (let sample = start; sample < end; sample += stride) peak = Math.max(peak, Math.abs(channel[sample]));
      return peak;
    });
    const max = Math.max(...peaks, 0.00001);
    return peaks.map(peak => peak / max);
  } finally { await context.close(); }
}

/** Private, source-backed playback directly in a gallery tile or its list-row preview area. */
export function GalleryMediaPreview({ asset, video = false, posterUrl, compact = false, enabled = true }: {
  asset: LibraryAsset; video?: boolean; posterUrl?: string; compact?: boolean; enabled?: boolean;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const reduce = useReducedMotion();
  const container = useRef<HTMLDivElement>(null);
  const media = useRef<HTMLMediaElement | null>(null);
  const visible = useInView(container, { amount: 0.25 });
  const [foreground, setForeground] = useState(true);
  const [activated, setActivated] = useState(false);
  const [userPaused, setUserPaused] = useState(false);
  const [playing, setPlaying] = useState(false);
  const [position, setPosition] = useState(0);
  const [duration, setDuration] = useState(asset.duration || 0);
  const [metadataReady, setMetadataReady] = useState(false);
  const [rate, setRate] = useState(1);
  const [volume, setVolume] = useState(video ? 0 : 0.8);
  const [failure, setFailure] = useState('');
  const [refreshAttempts, setRefreshAttempts] = useState(0);
  const title = asset.displayTitle || asset.originalFilename || (video ? 'Video' : 'Audio');
  const ready = !asset.processing || ['ready', 'unsupported'].includes(asset.processing);
  const active = enabled && ready && (activated || visible);
  const source = useQuery({
    queryKey: ['library-inline-source', workspaceId, asset.id, video],
    queryFn: () => video ? api.mediaUrl(workspaceId, asset.id) : api.libraryFileUrl(workspaceId, asset.id),
    enabled: Boolean(workspaceId) && active,
    staleTime: 3 * 60_000,
    refetchInterval: active ? 4 * 60_000 : false,
    retry: 1
  });
  const waveformAllowed = !video && activated && metadataReady && duration > 0 && duration <= WAVEFORM_DURATION_LIMIT && (!asset.bytes || asset.bytes <= WAVEFORM_BYTE_LIMIT);
  const waveform = useQuery({
    queryKey: ['library-audio-waveform', workspaceId, asset.id, asset.hash],
    queryFn: ({ signal }) => sourceWaveform(source.data!.url, signal),
    enabled: waveformAllowed && Boolean(source.data?.url),
    staleTime: Infinity,
    gcTime: 60_000,
    retry: false
  });
  useEffect(() => {
    const update = () => setForeground(document.visibilityState === 'visible');
    update(); document.addEventListener('visibilitychange', update);
    return () => document.removeEventListener('visibilitychange', update);
  }, []);
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
    const shouldPlay = active && foreground && !userPaused && (video ? visible && (!reduce || activated) : activated);
    if (shouldPlay && source.data?.url) {
      void element.play().catch(error => {
        if (error instanceof DOMException && error.name === 'AbortError') return;
        setPlaying(false);
        setFailure('Press play to preview');
      });
    } else element.pause();
  }, [active, foreground, userPaused, video, visible, reduce, activated, source.data?.url]);
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
    media.current.currentTime = value; setPosition(value);
  };
  const onMetadata = () => {
    const element = media.current;
    if (!element) return;
    setDuration(Number.isFinite(element.duration) ? element.duration : 0); setMetadataReady(true);
    // Refreshing an expiring private URL keeps the user's place and controls.
    if (position > 0 && position < element.duration) element.currentTime = position;
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
    onTimeUpdate: () => setPosition(media.current?.currentTime || 0),
    onPlay: () => { setPlaying(true); setFailure(''); announcePlay(); },
    onPause: () => setPlaying(false),
    onEnded: () => { setPlaying(false); setUserPaused(true); },
    onError
  };
  const progress = duration > 0 ? Math.min(1, position / duration) : 0;
  return (
    <div ref={container} role='group' data-library-media-player={video ? 'video' : 'audio'} data-library-thumbnail={video ? 'video' : (asset.extension || 'audio')} data-thumbnail-preview={video ? 'video-poster' : 'audio-player'} aria-label={`${video ? 'Video' : 'Audio'} preview: ${title}`} className={cn('rafii-quiet relative flex min-w-0 flex-col overflow-hidden', !compact && 'aspect-square min-h-[250px]', compact && 'rounded-[var(--rafii-radius-control)]')}>
      <div className={cn('relative flex min-h-0 flex-1 items-center justify-center', compact ? (video ? 'h-40 min-h-40' : 'min-h-20') : 'min-h-24')}>
        {video ? <>
          {posterUrl ? <Image src={posterUrl} alt='' fill unoptimized sizes={compact ? '320px' : '400px'} className='object-cover' /> : <Icons.video aria-hidden className='text-muted-foreground size-8' />}
          <video ref={node => { media.current = node; }} src={active ? source.data?.url : undefined} poster={posterUrl} muted={volume === 0} playsInline loop preload='metadata' aria-label={`Video preview of ${title}`} {...mediaEvents} className='absolute inset-0 h-full w-full object-contain' />
          <span className='rafii-glass pointer-events-none absolute top-2 left-2 rounded-full px-2 py-1 text-[10px] font-medium'>{volume === 0 ? 'Silent preview' : 'Video preview'}</span>
        </> : <>
          <audio ref={node => { media.current = node; }} src={source.data?.url} preload={activated ? 'metadata' : 'none'} {...mediaEvents} />
          {waveform.data ? <svg viewBox='0 0 384 64' preserveAspectRatio='none' aria-label='Waveform decoded from the original audio' role='img' data-waveform-source='original-audio' className='mx-4 h-16 w-[calc(100%-2rem)]'>
            {waveform.data.map((peak, index) => <rect key={index} x={index * 4} y={32 - Math.max(1, peak * 56) / 2} width={2} height={Math.max(1, peak * 56)} rx={1} fill='currentColor' className={index / 96 <= progress ? 'text-foreground' : 'text-muted-foreground/50'} />)}
          </svg> : <div className='text-muted-foreground flex flex-col items-center gap-2 p-3 text-center'>
            <Icons.music aria-hidden className='size-7' />
            <span className='text-[11px]'>{!activated ? 'Listen to this audio' : waveform.isFetching ? 'Reading audio waveform…' : 'Audio preview'}</span>
          </div>}
        </>}
      </div>
      <div className='bg-card/95 relative flex min-w-0 flex-col gap-0.5 px-2 pb-2'>
        <div className='flex min-w-0 items-center gap-1'>
          <button type='button' onClick={toggle} disabled={!ready || (activated && source.isFetching && !source.data)} aria-label={`${playing ? 'Pause' : 'Play'} ${video ? 'video' : 'audio'} preview`} className='rafii-focus hover:bg-foreground/5 flex size-11 shrink-0 items-center justify-center rounded-full disabled:opacity-50'>
            {source.isFetching && !source.data ? <Icons.spinner aria-hidden className='size-4 animate-spin motion-reduce:animate-none' /> : playing ? <Icons.pause aria-hidden className='size-4' /> : <Icons.play aria-hidden className='size-4' />}
          </button>
          <span className='text-muted-foreground min-w-0 flex-1 text-[10px] tabular-nums'>{timeLabel(position)} / {timeLabel(duration)}</span>
          <select aria-label={`${video ? 'Video' : 'Audio'} playback speed`} value={rate} onChange={event => setRate(Number(event.target.value))} className='rafii-focus min-h-11 max-w-20 rounded-md bg-transparent px-1 text-xs' >
            {[0.5,0.75,1,1.25,1.5,2].map(speed => <option key={speed} value={speed}>{speed}×</option>)}
          </select>
        </div>
        <input type='range' min={0} max={duration || 1} step={0.05} value={Math.min(position, duration || 1)} onChange={event => seek(Number(event.target.value))} disabled={!metadataReady || !duration} aria-label={`${video ? 'Video' : 'Audio'} preview timeline`} aria-valuetext={`${timeLabel(position)} of ${timeLabel(duration)}`} className='rafii-focus accent-foreground h-11 w-full cursor-pointer disabled:cursor-default' />
        <label className='text-muted-foreground flex min-h-11 items-center gap-2 text-[10px]'>
          <span>Volume</span>
          <input type='range' min={0} max={1} step={0.05} value={volume} aria-label={`${video ? 'Video' : 'Audio'} preview volume`} aria-valuetext={`${Math.round(volume * 100)} percent`} onChange={event => { setVolume(Number(event.target.value)); if (Number(event.target.value) > 0) { useNowPlaying.getState().setPlaying(false); window.dispatchEvent(new CustomEvent(PLAY_EVENT, { detail: asset.id })); } }} className='rafii-focus accent-foreground h-11 min-w-0 flex-1 cursor-pointer' />
          <span className='w-7 text-right tabular-nums'>{Math.round(volume * 100)}%</span>
        </label>
        {(source.isError || failure) ? <p role='status' className='text-muted-foreground px-1 text-[10px]'>{failure || 'Private preview unavailable. Press play to retry.'}</p> : null}
        {!video && activated && !waveform.data && !waveform.isFetching ? <p className='text-muted-foreground px-1 text-[10px]'>{waveformAllowed ? 'Waveform unavailable for this audio codec.' : 'Waveform is available for supported audio up to 5 minutes / 16 MB.'}</p> : null}
      </div>
    </div>
  );
}
