'use client';

import { useEffect, useRef, useState, type KeyboardEvent, type PointerEvent, type RefObject } from 'react';
import { cn } from '@/lib/utils';
import { PEAKS_PER_SECOND, readAudioPeaks, WaveformError, type PeakSnapshot } from './audio-peaks';

const PITCH = 3;
const BAR = 2;
const FRICTION_MS = 325;

/** Seconds across the waveform: short clips get fine detail, long recordings stay quick to travel. */
export const visibleSeconds = (duration: number) => Math.min(90, Math.max(6, duration / 5));

const finished = new Map<string, PeakSnapshot>();
function remember(key: string, snapshot: PeakSnapshot) {
  finished.delete(key);
  finished.set(key, snapshot);
  while (finished.size > 8) finished.delete(finished.keys().next().value!);
}

export interface PeaksState { status: 'idle' | 'loading' | 'ready' | 'error'; snapshot: PeakSnapshot | null; error?: string }

/** Peaks for one original, filled in piece by piece; finished results are kept for a few recently played files. */
export function useAudioPeaks(key: string, url: string | undefined, enabled: boolean, durationHint: number): PeaksState {
  const [state, setState] = useState<PeaksState>({ status: 'idle', snapshot: null });
  const latest = useRef({ url, durationHint });
  useEffect(() => { latest.current = { url, durationHint }; });
  const hasUrl = Boolean(url);
  useEffect(() => {
    if (!enabled || !hasUrl || !latest.current.url) return;
    const cached = finished.get(key);
    if (cached) { setState({ status: 'ready', snapshot: cached }); return; }
    const controller = new AbortController();
    setState({ status: 'loading', snapshot: null });
    readAudioPeaks(latest.current.url, controller.signal, snapshot => { if (!controller.signal.aborted) setState({ status: 'loading', snapshot }); }, latest.current.durationHint)
      .then(snapshot => {
        if (controller.signal.aborted) return;
        if (!snapshot.length) throw new WaveformError('No audio samples were found in this file.');
        remember(key, snapshot);
        setState({ status: 'ready', snapshot });
      })
      .catch((error: unknown) => {
        if (controller.signal.aborted) return;
        setState({ status: 'error', snapshot: null, error: error instanceof WaveformError ? error.message : 'This browser couldn’t read a waveform from this file.' });
      });
    return () => controller.abort();
  }, [enabled, hasUrl, key]);
  return state;
}

/**
 * The recording's waveform under a fixed centre playhead, like Voice Memos: drag or flick it left and right to move
 * through the audio. Bars are measured from decoded samples; parts not read yet show as a flat line. Drawing happens
 * outside React (a pool of SVG bars) so playback and dragging stay smooth on a phone.
 */
export function ScrubWaveform({ snapshot, duration, position, media, playing, reduce, compact, disabled, label, valueText, onScrubStart, onScrub, onScrubEnd, onSeek }: {
  snapshot: PeakSnapshot | null;
  duration: number;
  position: number;
  media: RefObject<HTMLMediaElement | null>;
  playing: boolean;
  reduce: boolean;
  compact?: boolean;
  disabled?: boolean;
  label: string;
  valueText: string;
  onScrubStart: () => void;
  onScrub: (time: number) => void;
  onScrubEnd: (time: number) => void;
  onSeek: (time: number) => void;
}) {
  const root = useRef<HTMLDivElement>(null);
  const svg = useRef<SVGSVGElement>(null);
  const bars = useRef<SVGRectElement[]>([]);
  const size = useRef({ width: 0, height: 0 });
  const gesture = useRef<{ id: number; x: number; y: number; from: number; time: number; dragging: boolean; samples: { x: number; t: number }[] } | null>(null);
  const momentum = useRef(0);
  const live = useRef({ snapshot, duration, position });
  useEffect(() => { live.current = { snapshot, duration, position }; });

  const clamp = (time: number) => Math.max(0, Math.min(live.current.duration || 0, time));
  const pxPerSecond = () => size.current.width / visibleSeconds(live.current.duration);

  const draw = (time: number) => {
    const { width, height } = size.current;
    const { snapshot: peaks, duration: total } = live.current;
    if (!width || !height) return;
    const perSecond = pxPerSecond(), barSeconds = PITCH / perSecond;
    // Once finished, the measured peaks span exactly the player's duration (the decoder's frame padding drops out).
    const peakSeconds = peaks?.done && total > 0 ? total / peaks.length : 1 / PEAKS_PER_SECOND;
    const first = Math.floor((time - width / 2 / perSecond) / barSeconds);
    const scale = peaks && peaks.max > 0 ? 1 / peaks.max : 0;
    bars.current.forEach((bar, index) => {
      const start = (first + index) * barSeconds;
      const x = width / 2 + (start - time) * perSecond;
      if (start < 0 || (total > 0 && start >= total) || x > width) { bar.setAttribute('height', '0'); return; }
      let peak = -1;
      if (peaks) {
        const from = Math.floor(start / peakSeconds), to = Math.min(peaks.length, Math.ceil((start + barSeconds) / peakSeconds));
        for (let at = from; at < to; at++) if (peaks.peaks[at] > peak) peak = peaks.peaks[at];
      }
      const tall = peak < 0 ? 2 : Math.max(2, Math.pow(peak * scale, 0.8) * (height - 4));
      bar.setAttribute('x', x.toFixed(1));
      bar.setAttribute('y', ((height - tall) / 2).toFixed(1));
      bar.setAttribute('height', tall.toFixed(1));
      bar.setAttribute('opacity', start + barSeconds / 2 <= time ? '1' : peak < 0 ? '0.25' : '0.4');
    });
  };
  const drawRef = useRef(draw);
  useEffect(() => { drawRef.current = draw; });

  // Size the bar pool to the element; redraw on resize.
  useEffect(() => {
    const element = root.current, canvas = svg.current;
    if (!element || !canvas) return;
    const observer = new ResizeObserver(([entry]) => {
      const width = entry.contentRect.width, height = entry.contentRect.height;
      size.current = { width, height };
      canvas.setAttribute('viewBox', `0 0 ${width} ${height}`);
      const needed = Math.ceil(width / PITCH) + 2;
      while (bars.current.length < needed) {
        const bar = document.createElementNS('http://www.w3.org/2000/svg', 'rect');
        bar.setAttribute('width', String(BAR)); bar.setAttribute('rx', '1'); bar.setAttribute('fill', 'currentColor'); bar.setAttribute('height', '0');
        canvas.appendChild(bar); bars.current.push(bar);
      }
      while (bars.current.length > needed) bars.current.pop()!.remove();
      drawRef.current(gesture.current?.dragging || momentum.current ? gesture.current?.time ?? live.current.position : media.current?.currentTime ?? live.current.position);
    });
    observer.observe(element);
    return () => observer.disconnect();
  }, [media]);

  // While playing, follow the media clock every frame (timeupdate alone ticks only ~4 times a second).
  useEffect(() => {
    if (!playing || reduce) return;
    let frame = 0;
    const tick = () => {
      if (!gesture.current?.dragging && !momentum.current && media.current) drawRef.current(media.current.currentTime);
      frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [playing, reduce, media]);

  useEffect(() => {
    if (!gesture.current?.dragging && !momentum.current) drawRef.current(position);
  }, [position, snapshot, duration]);

  useEffect(() => () => cancelAnimationFrame(momentum.current), []);

  // Capture can fail if the pointer already ended (e.g. iOS cancelling a touch); the drag still works without it.
  const capture = (element: HTMLDivElement, id: number) => { try { element.setPointerCapture(id); } catch { /* not capturable */ } };
  const stopMomentum = () => { if (momentum.current) { cancelAnimationFrame(momentum.current); momentum.current = 0; } };

  const move = (time: number) => {
    if (gesture.current) gesture.current.time = time;
    drawRef.current(time);
    onScrub(time);
  };

  const onPointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || !event.isPrimary || (event.pointerType === 'mouse' && event.button !== 0)) return;
    const wasCoasting = Boolean(momentum.current);
    stopMomentum();
    const from = wasCoasting && gesture.current ? gesture.current.time : (media.current?.currentTime ?? live.current.position);
    gesture.current = { id: event.pointerId, x: event.clientX, y: event.clientY, from, time: from, dragging: wasCoasting, samples: [{ x: event.clientX, t: event.timeStamp }] };
    // A mouse keeps the drag even when it leaves the waveform; a finger is captured once the drag turns horizontal.
    if (wasCoasting || event.pointerType === 'mouse') capture(event.currentTarget, event.pointerId);
  };

  const onPointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    const dx = event.clientX - current.x, dy = event.clientY - current.y;
    if (!current.dragging) {
      // Horizontal drags scrub; vertical ones are left to the page scroll (touch-action: pan-y).
      if (Math.abs(dy) > 8 && Math.abs(dy) > Math.abs(dx)) { gesture.current = null; return; }
      if (Math.abs(dx) < 6) return;
      current.dragging = true;
      capture(event.currentTarget, event.pointerId);
      current.x = event.clientX;
      current.samples = [{ x: event.clientX, t: event.timeStamp }];
      onScrubStart();
      return;
    }
    current.samples.push({ x: event.clientX, t: event.timeStamp });
    while (current.samples.length > 2 && event.timeStamp - current.samples[0].t > 100) current.samples.shift();
    move(clamp(current.from - (event.clientX - current.x) / pxPerSecond()));
  };

  const finish = (event: PointerEvent<HTMLDivElement>, cancelled: boolean) => {
    const current = gesture.current;
    if (!current || current.id !== event.pointerId) return;
    if (!current.dragging) { gesture.current = null; return; }
    const oldest = current.samples[0], newest = current.samples[current.samples.length - 1];
    // A finger that stopped before lifting does not flick; a burst of events is measured over at least one frame.
    const resting = event.timeStamp - newest.t > 60;
    const elapsed = Math.max(16, newest.t - oldest.t);
    const pxPerMs = cancelled || resting || current.samples.length < 2 ? 0 : Math.max(-3, Math.min(3, (newest.x - oldest.x) / elapsed));
    // px per ms → seconds per ms (dragging left moves forward in time).
    let velocity = -pxPerMs / pxPerSecond();
    if (reduce || Math.abs(velocity * pxPerSecond()) < 0.3) { gesture.current = null; onScrubEnd(current.time); return; }
    let last = performance.now();
    const coast = (now: number) => {
      const dt = Math.min(48, now - last); last = now;
      const next = clamp(current.time + velocity * dt);
      velocity *= Math.exp(-dt / FRICTION_MS);
      move(next);
      const stopped = Math.abs(velocity * pxPerSecond()) < 0.02 || next <= 0 || next >= live.current.duration;
      if (stopped) { momentum.current = 0; gesture.current = null; onScrubEnd(next); }
      else momentum.current = requestAnimationFrame(coast);
    };
    momentum.current = requestAnimationFrame(coast);
  };

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    if (disabled) return;
    const now = media.current?.currentTime ?? position;
    const step = { ArrowLeft: -5, ArrowDown: -5, ArrowRight: 5, ArrowUp: 5, PageDown: -30, PageUp: 30 }[event.key];
    const target = event.key === 'Home' ? 0 : event.key === 'End' ? duration : step === undefined ? null : now + step;
    if (target === null) return;
    event.preventDefault();
    onSeek(clamp(target));
  };

  const progress = snapshot && !snapshot.done && duration > 0 ? Math.min(99, Math.floor(snapshot.decodedSeconds / duration * 100)) : null;
  return (
    <div
      ref={root}
      role='slider'
      tabIndex={disabled ? -1 : 0}
      aria-label={label}
      aria-valuemin={0}
      aria-valuemax={Math.round(duration)}
      aria-valuenow={Math.round(position)}
      aria-valuetext={valueText}
      aria-disabled={disabled || undefined}
      data-waveform-source={snapshot ? 'original-audio' : undefined}
      data-waveform-state={snapshot?.done ? 'ready' : snapshot ? 'reading' : 'pending'}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={event => finish(event, false)}
      onPointerCancel={event => finish(event, true)}
      onKeyDown={onKeyDown}
      className={cn(
        'rafii-focus relative w-full touch-pan-y select-none overscroll-x-contain rounded-md',
        compact ? 'h-14' : 'h-20',
        disabled ? 'cursor-default' : 'cursor-grab active:cursor-grabbing'
      )}
    >
      <svg ref={svg} aria-hidden className='text-foreground absolute inset-0 h-full w-full [mask-image:linear-gradient(to_right,transparent,black_14%,black_86%,transparent)]' />
      <span aria-hidden className='bg-primary pointer-events-none absolute inset-y-0 left-1/2 w-0.5 -translate-x-1/2 rounded-full' />
      {progress !== null ? <span aria-hidden className='bg-background/85 text-muted-foreground pointer-events-none absolute top-1 left-2 rounded-full px-1.5 text-[10px] tabular-nums'>Reading {progress}%</span> : null}
    </div>
  );
}
