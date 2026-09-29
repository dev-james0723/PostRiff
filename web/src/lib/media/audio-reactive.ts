'use client';

import { create } from 'zustand';

export type AudioReactiveSource = 'none' | 'rafii' | 'external';
export type ExternalAudioState = 'idle' | 'requesting' | 'active';

export const AUDIO_REACTIVE_BAND_COUNT = 24;

const EMPTY_BANDS = Array.from({ length: AUDIO_REACTIVE_BAND_COUNT }, () => 0);

interface AudioReactiveState {
  source: AudioReactiveSource;
  active: boolean;
  level: number;
  bands: number[];
  transient: number;
  tickMs: number;
  externalState: ExternalAudioState;
  setFrame: (
    source: Exclude<AudioReactiveSource, 'none'>,
    level: number,
    bands: number[],
    transient?: number,
    tickMs?: number
  ) => void;
  deactivate: (source: Exclude<AudioReactiveSource, 'none'>) => void;
  setExternalState: (state: ExternalAudioState) => void;
}

export const useAudioReactive = create<AudioReactiveState>((set) => ({
  source: 'none',
  active: false,
  level: 0,
  bands: EMPTY_BANDS,
  transient: 0,
  tickMs: 0,
  externalState: 'idle',
  setFrame: (source, level, bands, transient = 0, tickMs = 0) =>
    set((state) => {
      // A person explicitly sharing system/tab audio wins over Rafii-owned playback.
      if (source === 'rafii' && state.source === 'external' && state.externalState === 'active')
        return state;
      return { source, active: true, level, bands, transient, tickMs };
    }),
  deactivate: (source) =>
    set((state) =>
      state.source === source
        ? {
            source: 'none',
            active: false,
            level: 0,
            bands: EMPTY_BANDS,
            transient: 0,
            tickMs: 0
          }
        : state
    ),
  setExternalState: (externalState) =>
    set((state) => ({
      externalState,
      ...(externalState === 'idle' && state.source === 'external'
        ? {
            source: 'none' as const,
            active: false,
            level: 0,
            bands: EMPTY_BANDS,
            transient: 0,
            tickMs: 0
          }
        : {})
    }))
}));

export function collapseSpectrum(
  input: ArrayLike<number>,
  bandCount = AUDIO_REACTIVE_BAND_COUNT
): number[] {
  if (bandCount <= 0) return [];
  if (!input.length) return Array.from({ length: bandCount }, () => 0);

  const result: number[] = [];
  for (let band = 0; band < bandCount; band += 1) {
    // Square the normalized position so bass/low-mid energy gets more visual resolution.
    const startRatio = band / bandCount;
    const endRatio = (band + 1) / bandCount;
    const start = Math.min(input.length - 1, Math.floor(startRatio * startRatio * input.length));
    const end = Math.max(
      start + 1,
      Math.min(input.length, Math.ceil(endRatio * endRatio * input.length))
    );
    let energy = 0;
    for (let index = start; index < end; index += 1) energy += Number(input[index] ?? 0) / 255;
    const average = energy / Math.max(1, end - start);
    // Gentle gamma gives quiet passages visible motion without flattening louder peaks.
    result.push(Math.min(1, Math.pow(average, 0.78)));
  }
  return result;
}

export function resampleBands(bands: readonly number[], count: number): number[] {
  if (count <= 0) return [];
  if (!bands.length) return Array.from({ length: count }, () => 0);
  if (count === 1) return [bands.reduce((sum, value) => sum + value, 0) / bands.length];

  return Array.from({ length: count }, (_, index) => {
    const position = (index / (count - 1)) * (bands.length - 1);
    const left = Math.floor(position);
    const right = Math.min(bands.length - 1, left + 1);
    const mix = position - left;
    return Math.max(0, Math.min(1, bands[left] * (1 - mix) + bands[right] * mix));
  });
}

function clamp01(value: number): number {
  return Math.max(0, Math.min(1, value));
}

function easeOutCubic(value: number): number {
  const t = clamp01(value);
  return 1 - (1 - t) ** 3;
}

export function spectralFlux(current: ArrayLike<number>, previous: Float32Array): number {
  if (!current.length || !previous.length) return 0;
  const length = Math.min(current.length, previous.length);
  let flux = 0;
  for (let index = 0; index < length; index += 1) {
    const value = Number(current[index] ?? 0) / 255;
    const delta = value - previous[index];
    if (delta > 0) flux += delta;
    previous[index] = value;
  }
  return Math.min(1, flux / Math.max(1, length * 0.1));
}

export interface RailMotionPoint {
  width: number;
  height: number;
  opacity: number;
  translateX: number;
  borderRadius: string;
}

export function buildRailMotion({
  count,
  activeIndex,
  level,
  transient,
  bands,
  tickMs
}: {
  count: number;
  activeIndex: number;
  level: number;
  transient: number;
  bands: readonly number[];
  tickMs: number;
}): RailMotionPoint[] {
  if (count <= 0) return [];

  const localBands = resampleBands(bands, count);
  const phase = (tickMs / 1000) * 8.6;
  const globalPulse = easeOutCubic(level);

  return Array.from({ length: count }, (_, index) => {
    const position = count <= 1 ? 0 : index / (count - 1);
    const bodyWave =
      (0.5 + 0.5 * Math.sin(phase - position * 4.4)) * globalPulse;
    const travellingTransient =
      (0.5 + 0.5 * Math.sin(phase * 1.35 - position * 9.2)) * clamp01(transient);
    const texture = clamp01(localBands[index] ?? 0);
    const focus =
      activeIndex >= 0
        ? Math.max(0, 1 - Math.abs(index - activeIndex) / Math.max(4, count * 0.22))
        : 0;

    // Most motion is shared by the whole rail. Spectrum adds texture instead of deciding
    // which vertical section is allowed to move, so bass-heavy tracks animate end to end.
    const energy = clamp01(
      globalPulse * 0.58 +
        bodyWave * 0.17 +
        texture * 0.15 +
        travellingTransient * 0.1
    );
    const base = index === activeIndex ? 8 : 6;

    return {
      width: base + energy * 19 + focus * 2,
      height: base + energy * 4.5,
      opacity: clamp01((index === activeIndex ? 0.92 : 0.5) + energy * 0.42),
      translateX: energy * 1.2 + travellingTransient * 1.5,
      borderRadius:
        energy > 0.05
          ? `${52 + energy * 18}% ${48 - energy * 12}% ${56 - energy * 8}% ${44 + energy * 12}%`
          : '9999px'
    };
  });
}

function rootMeanSquare(samples: Uint8Array<ArrayBuffer>): number {
  if (!samples.length) return 0;
  let sum = 0;
  for (const value of samples) sum += ((value - 128) / 128) ** 2;
  return Math.min(1, Math.sqrt(sum / samples.length) * 4);
}

class BrowserAudioMeter {
  private analyser: AnalyserNode;
  private frequency: Uint8Array<ArrayBuffer>;
  private timeDomain: Uint8Array<ArrayBuffer>;
  private frame: number | null = null;
  private enabled = false;
  private lastCommit = 0;
  private previousSpectrum: Float32Array;
  private smoothedLevel = 0;
  private smoothedTransient = 0;

  constructor(
    private readonly source: Exclude<AudioReactiveSource, 'none'>,
    private readonly context: AudioContext,
    analyser: AnalyserNode
  ) {
    this.analyser = analyser;
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.54;
    this.frequency = new Uint8Array(new ArrayBuffer(this.analyser.frequencyBinCount));
    this.timeDomain = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
    this.previousSpectrum = new Float32Array(this.analyser.frequencyBinCount);
  }

  setEnabled(enabled: boolean) {
    this.enabled = enabled;
    if (enabled) {
      void this.context.resume().catch(() => undefined);
      if (this.frame === null) this.frame = requestAnimationFrame(this.tick);
    } else {
      useAudioReactive.getState().deactivate(this.source);
    }
  }

  close() {
    this.enabled = false;
    if (this.frame !== null) cancelAnimationFrame(this.frame);
    this.frame = null;
    useAudioReactive.getState().deactivate(this.source);
    void this.context.close().catch(() => undefined);
  }

  private tick = (now: number) => {
    this.frame = null;
    if (!this.enabled) return;

    // ~45 fps keeps the rail fast enough to feel coupled to the music without forcing a 60 fps React loop.
    if (now - this.lastCommit >= 22) {
      this.analyser.getByteFrequencyData(this.frequency);
      this.analyser.getByteTimeDomainData(this.timeDomain);

      const rawLevel = rootMeanSquare(this.timeDomain);
      const levelBlend = rawLevel > this.smoothedLevel ? 0.62 : 0.2;
      this.smoothedLevel += (rawLevel - this.smoothedLevel) * levelBlend;

      const rawTransient = spectralFlux(this.frequency, this.previousSpectrum);
      this.smoothedTransient = Math.max(rawTransient, this.smoothedTransient * 0.74);

      useAudioReactive.getState().setFrame(
        this.source,
        this.smoothedLevel,
        collapseSpectrum(this.frequency),
        this.smoothedTransient,
        now
      );
      this.lastCommit = now;
    }
    this.frame = requestAnimationFrame(this.tick);
  };
}

export interface MediaElementAudioMeter {
  setEnabled: (enabled: boolean) => void;
  close: () => void;
}

export function attachMediaElementAudioMeter(
  element: HTMLMediaElement
): MediaElementAudioMeter | null {
  if (typeof AudioContext === 'undefined') return null;
  try {
    const context = new AudioContext();
    const analyser = context.createAnalyser();
    const source = context.createMediaElementSource(element);
    source.connect(analyser);
    analyser.connect(context.destination);
    const meter = new BrowserAudioMeter('rafii', context, analyser);
    return {
      setEnabled: (enabled) => meter.setEnabled(enabled),
      close: () => meter.close()
    };
  } catch {
    // Playback must remain usable even when Web Audio is unavailable or a CORS policy blocks analysis.
    return null;
  }
}

let externalStream: MediaStream | null = null;
let externalMeter: BrowserAudioMeter | null = null;

type DisplayMediaAudioOptions = DisplayMediaStreamOptions & {
  systemAudio?: 'include' | 'exclude';
  windowAudio?: 'exclude' | 'window' | 'system';
  selfBrowserSurface?: 'include' | 'exclude';
  surfaceSwitching?: 'include' | 'exclude';
};

export class ExternalAudioSyncError extends Error {
  code: 'unsupported' | 'no_audio' | 'denied' | 'failed';

  constructor(code: ExternalAudioSyncError['code'], message: string) {
    super(message);
    this.code = code;
  }
}

export async function startExternalAudioSync(): Promise<void> {
  if (externalMeter || useAudioReactive.getState().externalState === 'requesting') return;
  if (!navigator.mediaDevices?.getDisplayMedia || typeof AudioContext === 'undefined') {
    throw new ExternalAudioSyncError(
      'unsupported',
      'This browser cannot share playback audio with Rafii.'
    );
  }

  useAudioReactive.getState().setExternalState('requesting');
  let stream: MediaStream | null = null;
  try {
    const options: DisplayMediaAudioOptions = {
      video: true,
      audio: true,
      systemAudio: 'include',
      windowAudio: 'system',
      selfBrowserSurface: 'exclude',
      surfaceSwitching: 'include'
    };
    stream = await navigator.mediaDevices.getDisplayMedia(options);
    const audioTrack = stream.getAudioTracks()[0];
    if (!audioTrack) {
      for (const track of stream.getTracks()) track.stop();
      throw new ExternalAudioSyncError(
        'no_audio',
        'No audio track was shared. Choose a tab/window/screen with audio sharing enabled.'
      );
    }

    const context = new AudioContext();
    const analyser = context.createAnalyser();
    const audioOnly = new MediaStream([audioTrack]);
    context.createMediaStreamSource(audioOnly).connect(analyser);
    const meter = new BrowserAudioMeter('external', context, analyser);

    externalStream = stream;
    externalMeter = meter;
    useAudioReactive.getState().setExternalState('active');
    meter.setEnabled(true);

    const ended = () => stopExternalAudioSync();
    audioTrack.addEventListener('ended', ended, { once: true });
    for (const track of stream.getVideoTracks())
      track.addEventListener('ended', ended, { once: true });
  } catch (error) {
    if (stream) for (const track of stream.getTracks()) track.stop();
    externalStream = null;
    externalMeter = null;
    useAudioReactive.getState().setExternalState('idle');
    if (error instanceof ExternalAudioSyncError) throw error;
    const name = (error as { name?: string })?.name;
    if (name === 'NotAllowedError' || name === 'SecurityError') {
      throw new ExternalAudioSyncError('denied', 'Playback-audio sharing was not allowed.');
    }
    throw new ExternalAudioSyncError('failed', 'Rafii could not start playback-audio sync.');
  }
}

export function stopExternalAudioSync(): void {
  externalMeter?.close();
  externalMeter = null;
  if (externalStream) for (const track of externalStream.getTracks()) track.stop();
  externalStream = null;
  useAudioReactive.getState().setExternalState('idle');
}
