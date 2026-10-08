'use client';

import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { useQueryClient } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button } from '@/components/ui/button';
import { keys } from '@/lib/api/hooks';
import { attachMediaElementAudioMeter, type MediaElementAudioMeter } from '@/lib/media/audio-reactive';
import { attachMediaSession, formatMediaTime, updateMediaPosition, useNowPlaying } from '@/lib/media/now-playing';
import { useWorkspaceApi } from '@/lib/workspace/provider';

/** The only Rafii-owned playback element. It stays mounted across /app navigation. */
export function NowPlayingBar() {
  const { api, workspaceId } = useWorkspaceApi();
  const client = useQueryClient();
  const video = useRef<HTMLVideoElement>(null);
  const audioMeter = useRef<MediaElementAudioMeter | null>(null);
  const track = useNowPlaying((s) => s.track);
  const playing = useNowPlaying((s) => s.playing);
  const seconds = useNowPlaying((s) => s.seconds);
  const duration = useNowPlaying((s) => s.duration);
  const expanded = useNowPlaying((s) => s.expanded);
  const [playbackError, setPlaybackError] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (track && track.workspaceId !== workspaceId) useNowPlaying.getState().close();
  }, [track, workspaceId]);

  useEffect(() => () => {
    audioMeter.current?.close();
    audioMeter.current = null;
  }, []);

  useEffect(() => {
    audioMeter.current?.setEnabled(Boolean(track && playing));
  }, [playing, track]);

  useEffect(() => {
    const element = video.current;
    if (!element || !track) return;
    setPlaybackError(false);
    element.crossOrigin = 'anonymous';
    element.src = track.url;
    element.load();
    const begin = () => {
      if (track.startAt && Number.isFinite(element.duration)) element.currentTime = Math.min(track.startAt, element.duration);
      void element.play().catch(() => useNowPlaying.getState().setPlaying(false));
    };
    element.addEventListener('loadedmetadata', begin);
    const detach = attachMediaSession(typeof navigator !== 'undefined' ? navigator.mediaSession : undefined, element, track.title);
    return () => {
      element.removeEventListener('loadedmetadata', begin);
      detach();
      element.pause();
      element.removeAttribute('src');
      element.load();
    };
  }, [track]);

  useEffect(() => {
    const element = video.current;
    if (!element || !track) return;
    if (playing && element.paused && element.readyState >= 2) void element.play().catch(() => useNowPlaying.getState().setPlaying(false));
    else if (!playing && !element.paused) element.pause();
  }, [playing, track]);

  async function save() {
    if (!track?.conversationId || saving) return;
    setSaving(true);
    try {
      await api.saveMoment(workspaceId, track.conversationId, { assetId: track.assetId, title: track.title, seconds: video.current?.currentTime ?? seconds });
      void client.invalidateQueries({ queryKey: keys.messages(workspaceId, track.conversationId) });
      void client.invalidateQueries({ queryKey: ['navigation', workspaceId, track.conversationId] });
      toast.success('Moment saved to this conversation');
    } catch (error) { toast.error(error instanceof Error ? error.message : 'Could not save moment'); }
    finally { setSaving(false); }
  }

  return (
    <div aria-label='Now Playing' className={`rafii-elevated fixed right-3 bottom-[calc(4.75rem+env(safe-area-inset-bottom))] left-3 z-40 rounded-[var(--rafii-radius-card)] p-2.5 shadow-lg md:right-6 md:bottom-5 md:left-auto md:w-80 ${track ? '' : 'hidden'}`}>
      <div className='flex items-center gap-2'>
        <Button variant='quiet' size='icon-sm' aria-label={playing ? 'Pause' : 'Play'} onClick={() => useNowPlaying.getState().setPlaying(!playing)}>{playing ? <Icons.pause className='size-4' /> : <Icons.play className='size-4' />}</Button>
        <button type='button' className='rafii-focus min-w-0 flex-1 text-left' aria-expanded={expanded} onClick={() => useNowPlaying.getState().setExpanded(!expanded)}>
          <span className='block truncate text-xs font-medium'>{track?.title ?? 'Now Playing'}</span>
          <span className='text-muted-foreground text-[11px]'>Rafii {track?.kind === 'audio' ? 'audio' : 'video'} · {formatMediaTime(seconds)} / {duration ? formatMediaTime(duration) : '–:––'}</span>
        </button>
        <Button variant='quiet' size='icon-sm' aria-label='Close player' onClick={() => useNowPlaying.getState().close()}><Icons.close className='size-4' /></Button>
      </div>
      <input type='range' min={0} max={duration || 1} step={0.1} value={Math.min(seconds, duration || 1)} disabled={!duration}
        aria-label='Seek playback' className='accent-primary mt-1 w-full' onChange={(event) => { if (video.current) video.current.currentTime = Number(event.target.value); }} />
      <div className='flex items-center justify-between gap-2'>
        <span className='text-muted-foreground text-[11px]'>{track?.conversationId ? 'Saved moments stay in this conversation' : 'Open a conversation to save a moment'}</span>
        <Button variant='quiet' size='sm' disabled={!track?.conversationId || saving} onClick={() => void save()}>Save moment</Button>
      </div>
      {playbackError ? <p role='alert' className='text-destructive mt-2 text-xs'>Playback unavailable. Reopen this asset to refresh access, or download its original for another player.</p> : null}
      {/* Only this element owns audio/video; inline cards open it instead of playing a second copy. */}
      {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
      <video ref={video} crossOrigin='anonymous' playsInline preload='metadata' aria-label={track?.title || 'Rafii video'}
        className={expanded && track && track.kind !== 'audio' ? 'mt-2 max-h-52 w-full rounded-lg bg-black' : 'absolute size-px opacity-0'}
        onTimeUpdate={(event) => { useNowPlaying.getState().setPosition(event.currentTarget.currentTime); updateMediaPosition(navigator.mediaSession, event.currentTarget); }}
        onDurationChange={(event) => useNowPlaying.getState().setPosition(event.currentTarget.currentTime, Number.isFinite(event.currentTarget.duration) ? event.currentTarget.duration : null)}
        onPlay={(event) => {
          audioMeter.current ??= attachMediaElementAudioMeter(event.currentTarget);
          audioMeter.current?.setEnabled(true);
          useNowPlaying.getState().setPlaying(true);
        }}
        onPause={() => { audioMeter.current?.setEnabled(false); useNowPlaying.getState().setPlaying(false); }}
        onError={() => { setPlaybackError(true); useNowPlaying.getState().setPlaying(false); }}
        onEnded={() => { audioMeter.current?.setEnabled(false); useNowPlaying.getState().setPlaying(false); }} />
    </div>
  );
}
