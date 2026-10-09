'use client';

import { useRef, useState } from 'react';
import { toast } from 'sonner';
import { Icons } from '@/components/icons';
import { PanelButton as Button } from '../ui/controls';
import type { AssetRef, ContentSegment } from '@/lib/api/library-intelligence-types';
import { newIdempotencyKey, outcomeFromActionResult, outcomeFromError } from '@/lib/library/batch';
import { assetRefFor } from '@/lib/library/url-state';
import { formatClock, momentInterval } from '@/lib/library/wording';
import { useNowPlaying } from '@/lib/media/now-playing';
import { useWorkspaceApi } from '@/lib/workspace/provider';
import type { LibraryAsset } from '../use-library';

function randomKey() {
  return typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function' ? crypto.randomUUID() : `${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

/**
 * Seek the one Rafii player (the Now Playing bar) in place. Returns false when this item is not the loaded track, so
 * the caller starts it at that point instead — always from the person's own action.
 */
function seekNowPlaying(assetId: string, seconds: number): boolean {
  return useNowPlaying.getState().seek(seconds, assetId);
}

/**
 * Audio in the detail panel: play, pause and seek through the Now Playing bar (the only media element Rafii owns),
 * and save a moment as a real interval of this version. Opening the detail never starts playback (A021).
 */
export function AudioMomentPlayer({
  asset,
  title,
  assetRef,
  durationMs,
  moments,
  canEdit,
  onAnnounce
}: {
  asset: LibraryAsset;
  title: string;
  assetRef?: AssetRef | null;
  durationMs?: number | null;
  moments: ContentSegment[];
  canEdit: boolean;
  onAnnounce?: (message: string) => void;
}) {
  const { api, workspaceId } = useWorkspaceApi();
  const track = useNowPlaying((state) => state.track);
  const playing = useNowPlaying((state) => state.playing);
  const seconds = useNowPlaying((state) => state.seconds);
  const playerDuration = useNowPlaying((state) => state.duration);
  const current = track?.assetId === asset.id;
  const [starting, setStarting] = useState(false);
  const [start, setStart] = useState<number | null>(null);
  const [end, setEnd] = useState<number | null>(null);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const momentKey = useRef<{ digest: string; key: string } | null>(null);
  const ready = ['ready', 'unsupported'].includes(asset.processing ?? '');
  const total = current && playerDuration ? playerDuration : typeof durationMs === 'number' && durationMs > 0 ? durationMs / 1000 : typeof asset.duration === 'number' && asset.duration > 0 ? asset.duration : null;
  const check = momentInterval(start, end, total);

  /** Only ever called from a press: the person chose to listen. */
  async function startPlayback(startAt?: number) {
    setStarting(true);
    try {
      const { url } = await api.libraryFileUrl(workspaceId, asset.id);
      useNowPlaying.getState().open({ kind: 'audio', workspaceId, assetId: asset.id, title, url, startAt });
    } catch (failure) {
      toast.error(failure instanceof Error ? failure.message : 'Audio unavailable');
    } finally {
      setStarting(false);
    }
  }

  async function saveMoment() {
    if (!check.ok) return;
    const ref = assetRef ?? assetRefFor(asset.id);
    const digest = `${ref.assetId}:${ref.versionId}:${check.startMs}:${check.endMs}`;
    if (!momentKey.current || momentKey.current.digest !== digest) momentKey.current = { digest, key: newIdempotencyKey('lib-moment', randomKey) };
    setSaving(true);
    setError(null);
    try {
      const result = await api.libraryAction(workspaceId, {
        actionId: `moment-${Date.now()}`,
        uiInstanceId: 'library-detail',
        actionType: 'moment.save',
        targetRefs: [ref],
        expectedRevision: null,
        idempotencyKey: momentKey.current.key,
        payload: { startMs: check.startMs, endMs: check.endMs }
      });
      const outcome = outcomeFromActionResult(asset.id, result);
      if (outcome.status === 'applied') {
        momentKey.current = null;
        onAnnounce?.(`Moment ${formatClock(check.startMs)}–${formatClock(check.endMs)} saved.`);
        setStart(null);
        setEnd(null);
      } else setError(outcome.message ?? 'The moment wasn’t saved.');
    } catch (failure) {
      setError(outcomeFromError(asset.id, failure as { status?: number; code?: string; message?: string }).message ?? 'The moment wasn’t saved.');
    } finally {
      setSaving(false);
    }
  }

  const position = current ? seconds : 0;
  return (
    <section aria-label='Listen' className='flex flex-col gap-3'>
      <div className='flex flex-wrap items-center gap-2'>
        {current ? (
          <Button variant='action' size='control' onClick={() => useNowPlaying.getState().setPlaying(!playing)} aria-label={playing ? 'Pause playback' : 'Resume playback'}>
            {playing ? <Icons.pause aria-hidden /> : <Icons.play aria-hidden />}
            {playing ? 'Pause' : 'Resume'}
          </Button>
        ) : (
          <Button variant='glass' size='control' disabled={!ready || starting} onClick={() => void startPlayback()}>
            {starting ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : <Icons.play aria-hidden />}
            Play audio in Now Playing
          </Button>
        )}
        <span className='text-muted-foreground text-sm tabular-nums'>
          {formatClock(position * 1000)} / {total ? formatClock(total * 1000) : '–:––'}
        </span>
      </div>
      <input
        type='range'
        min={0}
        max={total || 1}
        step={0.1}
        value={Math.min(position, total || 1)}
        disabled={!current || !total}
        aria-label={`Position in ${title}`}
        aria-valuetext={`${formatClock(position * 1000)} of ${total ? formatClock(total * 1000) : 'unknown length'}`}
        onChange={(event) => {
          const to = Number(event.target.value);
          if (!seekNowPlaying(asset.id, to)) void startPlayback(to);
        }}
        className='accent-foreground h-11 w-full'
      />
      {canEdit ? (
        <div className='rafii-quiet flex flex-col gap-2 rounded-[var(--rafii-radius-card)] p-3'>
          <p className='text-sm font-medium'>Save a moment</p>
          <p className='text-muted-foreground text-xs'>Play to the start, set it, then play to the end and set that. The moment keeps this exact version and interval.</p>
          <div className='flex flex-wrap gap-2'>
            <Button variant='glass' size='control' disabled={!current} onClick={() => setStart(seconds)} aria-label={`Set moment start at ${formatClock(position * 1000)}`}>
              Start {start !== null ? formatClock(start * 1000) : 'not set'}
            </Button>
            <Button variant='glass' size='control' disabled={!current} onClick={() => setEnd(seconds)} aria-label={`Set moment end at ${formatClock(position * 1000)}`}>
              End {end !== null ? formatClock(end * 1000) : 'not set'}
            </Button>
            <Button variant='action' size='control' disabled={!check.ok || saving} onClick={() => void saveMoment()}>
              {saving ? <Icons.spinner className='animate-spin motion-reduce:animate-none' aria-hidden /> : null}
              Save moment
            </Button>
          </div>
          {start !== null || end !== null ? (!check.ok ? <p className='text-muted-foreground text-xs'>{check.reason}</p> : null) : null}
          {error ? (
            <p role='alert' className='text-destructive text-xs'>
              {error}
            </p>
          ) : null}
        </div>
      ) : null}
      {moments.length ? (
        <div className='flex flex-col gap-1'>
          <p className='rafii-eyebrow'>Saved moments</p>
          <ul className='flex flex-col'>
            {moments.map((moment) =>
              moment.locator?.kind === 'time' ? (
                <li key={moment.id} className='flex min-h-11 items-center justify-between gap-2 text-sm'>
                  <span className='min-w-0 truncate'>
                    {moment.locatorLabel || `${formatClock(moment.locator.startMs)}–${formatClock(moment.locator.endMs)}`}
                    {moment.text ? <span className='text-muted-foreground'> · {moment.text}</span> : null}
                  </span>
                  <Button
                    variant='quiet'
                    size='lg'
                    className='h-11 shrink-0'
                    aria-label={`Play from ${formatClock(moment.locator.startMs)}`}
                    onClick={() => {
                      const at = moment.locator?.kind === 'time' ? moment.locator.startMs / 1000 : 0;
                      if (!seekNowPlaying(asset.id, at)) void startPlayback(at);
                    }}
                  >
                    <Icons.play aria-hidden />
                    Play
                  </Button>
                </li>
              ) : null
            )}
          </ul>
        </div>
      ) : null}
    </section>
  );
}
