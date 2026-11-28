'use client';

import { useEffect, useRef, useState } from 'react';
import { useQuery } from '@tanstack/react-query';
import { Icons } from '@/components/icons';
import { Button, buttonVariants } from '@/components/ui/button';
import { NativeSelect, NativeSelectOption } from '@/components/ui/native-select';
import { Label } from '@/components/ui/label';
import { StateMessage } from '@/components/rafii';
import { useLibrary } from '@/features/library/use-library';
import type { Asset } from '@/lib/api/types';
import type { RenderedCaption } from '@/lib/api/creative-video';
import { isPostableVideo } from '@/lib/media/asset-kinds';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import { captionTrack } from './scene-edit';

export function useVideoLibrary() {
  const library = useLibrary({ filter: 'all', kindFilter: 'video', sort: 'newest', query: '' });
  const available = new Map<string, Asset>();
  for (const asset of [...(library.snapshot.data?.state.phase2?.assets ?? []), ...library.assets]) {
    if (isPostableVideo(asset) && (asset.bytes ?? 0) <= 64 * 1024 * 1024) available.set(asset.id, asset);
    else available.delete(asset.id);
  }
  const state = library.snapshot.data?.state;
  return { videos: [...available.values()], query: library.normalized, sample: state?.workspace?.sample === true,
    brand: state?.brandHub?.speaker || state?.speaker?.label || '', product: state?.brandHub?.subject || '' };
}
export type VideoLibrary = ReturnType<typeof useVideoLibrary>;

function assetLabel(asset: Asset) {
  const name = asset.displayTitle || asset.originalFilename || `Video ${asset.id.slice(0, 8)}`;
  const duration = asset.duration ? ` · ${Number(asset.duration.toFixed(2))} s` : '';
  return name + duration;
}

export function VideoSelect({ id, label, library, value, onChange, footage = false, exclude, currentClip, linkedReference, disabled }: {
  id: string; label: string; library: VideoLibrary; value: string; onChange: (value: string) => void;
  footage?: boolean; exclude?: string; currentClip?: string | null; linkedReference?: string; disabled?: boolean;
}) {
  const { videos, query } = library;
  const choices = videos.filter(v => v.id !== exclude && (footage || (v.duration ?? 0) <= 90));
  return <div className='grid min-w-0 gap-2'>
    <Label htmlFor={id}>{label}</Label>
    <NativeSelect id={id} className='w-full [&_select]:h-11' value={value} disabled={disabled} onChange={e => onChange(e.target.value)}>
      <NativeSelectOption value=''>{footage ? 'No footage assigned' : 'No reference · use my brief'}</NativeSelectOption>
      {linkedReference && !choices.some(v => v.id === linkedReference) &&
        <NativeSelectOption value={linkedReference}>Video matched to your published post</NativeSelectOption>}
      {currentClip && currentClip !== exclude && !choices.some(v => v.id === currentClip) &&
        <NativeSelectOption value={currentClip}>Current scene footage</NativeSelectOption>}
      {choices.map(asset => <NativeSelectOption value={asset.id} key={asset.id}>{assetLabel(asset)}</NativeSelectOption>)}
    </NativeSelect>
    <div className='flex flex-wrap items-center gap-x-3 gap-y-1 text-xs'>
      {!disabled && <a href='/app/library' target='_blank' rel='noopener noreferrer' className='rafii-focus min-h-8 content-center rounded-sm underline underline-offset-4'>Upload in Library (new tab)</a>}
      <Button type='button' variant='quiet' size='sm' disabled={query.isFetching || disabled} onClick={() => void query.refetch()}>
        {query.isFetching ? 'Loading videos…' : 'Refresh videos'}
      </Button>
      {query.hasNextPage && <Button type='button' variant='quiet' size='sm' disabled={query.isFetching || disabled} onClick={() => void query.fetchNextPage()}>Load more videos</Button>}
    </div>
    {query.isError && <p role='alert' className='text-sm text-destructive'>The Library could not load this list. Refresh videos to try again.</p>}
  </div>;
}

export function PrivateVideo({ assetId, label, downloadName, captions, exportFrames, cut, onCutPositionChange }: {
  assetId: string; label: string; downloadName?: string; captions?: RenderedCaption[];
  exportFrames?: { projectId: string; revision: number; fps: number; count: number };
  cut?: { start: number; duration: number };
  onCutPositionChange?: (elapsedMs: number) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const [show, setShow] = useState(false);
  const [problem, setProblem] = useState('');
  const [downloading, setDownloading] = useState<'video' | 'frame' | null>(null);
  const [track, setTrack] = useState('');
  const downloadingRef = useRef(false);
  const downloadController = useRef<AbortController | null>(null);
  const player = useRef<HTMLVideoElement | null>(null);
  useEffect(() => () => downloadController.current?.abort(), []);
  useEffect(() => {
    const vtt = show ? captionTrack(captions) : null;
    if (!vtt) { setTrack(''); return; }
    const url = URL.createObjectURL(new Blob([vtt], { type: 'text/vtt' }));
    setTrack(url);
    return () => URL.revokeObjectURL(url);
  }, [captions, show]);
  const link = useQuery({
    queryKey: ['creative-video-playback', workspaceId, assetId], queryFn: () => api.mediaUrl(workspaceId, assetId),
    enabled: show, retry: false, gcTime: 0, refetchOnWindowFocus: false
  });
  async function download(kind: 'video' | 'frame') {
    if (downloadingRef.current) return;
    downloadingRef.current = true;
    const controller = new AbortController();
    downloadController.current = controller;
    setDownloading(kind);
    setProblem('');
    try {
      let data: Blob;
      let filename = downloadName || 'video.mp4';
      if (kind === 'frame') {
        if (!player.current || !exportFrames) return;
        const frame = Math.min(exportFrames.count - 1, Math.floor(player.current.currentTime * exportFrames.fps));
        data = await api.creativeVideoFrame(workspaceId, exportFrames.projectId, exportFrames.revision, frame, controller.signal);
        filename = `revision-${exportFrames.revision}-frame-${frame}.png`;
      } else {
        const fresh = await api.mediaUrl(workspaceId, assetId);
        if (controller.signal.aborted) return;
        const response = await fetch(fresh.url, { credentials: 'omit', referrerPolicy: 'no-referrer', signal: controller.signal });
        if (!response.ok) throw new Error();
        data = await response.blob();
      }
      if (controller.signal.aborted) return;
      if (!data.size) throw new Error();
      const objectUrl = URL.createObjectURL(data);
      const anchor = document.createElement('a');
      anchor.href = objectUrl;
      anchor.download = filename;
      document.body.appendChild(anchor);
      anchor.click();
      anchor.remove();
      window.setTimeout(() => URL.revokeObjectURL(objectUrl), 30_000);
    } catch {
      if (controller.signal.aborted) return;
      setProblem(kind === 'frame' ? 'The frame could not be downloaded. Reload the saved video and try again.' : 'The file could not be downloaded. Open the private video and use your browser’s save option.');
      setShow(true);
    } finally {
      downloadingRef.current = false;
      downloadController.current = null;
      if (!controller.signal.aborted) setDownloading(null);
    }
  }
  return <div className='grid gap-2'>
    <div className='flex flex-wrap gap-2'>
      <Button type='button' variant='glass' size='lg' disabled={link.isFetching} onClick={() => {
        setProblem('');
        if (show) void link.refetch();
        else setShow(true);
      }}><Icons.play aria-hidden />{link.isFetching ? 'Loading video…' : show ? 'Refresh playback' : label}</Button>
      {downloadName && <Button type='button' variant='action' size='lg' disabled={Boolean(downloading)} onClick={() => void download('video')}>{downloading === 'video' ? 'Preparing download…' : 'Download MP4'}</Button>}
    </div>
    {show && link.data && <>
      {/* oxlint-disable-next-line jsx-a11y/media-has-caption -- An authored export has a conditional track below. Uploaded media can have its own embedded track. */}
      <video ref={player} controls playsInline preload='metadata' src={link.data.url} aria-label={label}
        onLoadedMetadata={event => { if (cut) event.currentTarget.currentTime = cut.start; }}
        onPlay={event => { const video = event.currentTarget; if (cut && (video.currentTime < cut.start || video.currentTime >= cut.start + cut.duration)) video.currentTime = cut.start; }}
        onTimeUpdate={event => {
          if (!cut) return;
          const video = event.currentTarget;
          const elapsed = video.currentTime - cut.start;
          if (!video.paused && elapsed >= cut.duration) video.pause();
          onCutPositionChange?.(Math.round(Math.min(cut.duration, Math.max(0, elapsed)) * 1000));
        }}
        onError={() => setProblem('Playback could not start. Refresh playback to request a new private link.')}
        className='rafii-quiet max-h-[28rem] w-full rounded-xl object-contain'>
        {track && <track kind='captions' label='Project captions' srcLang='und' src={track} />}
      </video>
      {exportFrames && <Button type='button' variant='glass' className='w-fit' disabled={Boolean(downloading)} onClick={() => void download('frame')}>
        {downloading === 'frame' ? 'Preparing image…' : 'Save current frame as PNG'}</Button>}
      {problem && <a href={link.data.url} target='_blank' rel='noopener noreferrer' className={buttonVariants({ variant: 'link' })}>Open private video</a>}
    </>}
    {(link.isError || problem) && <StateMessage kind='error' layout='inline' title={problem || 'The private video could not be opened.'}
      description={link.isError && link.error instanceof Error ? link.error.message : undefined} />}
  </div>;
}
