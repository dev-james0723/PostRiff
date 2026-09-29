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
  externalState: ExternalAudioState;
  setFrame: (source: Exclude<AudioReactiveSource, 'none'>, level: number, bands: number[]) => void;
  deactivate: (source: Exclude<AudioReactiveSource, 'none'>) => void;
  setExternalState: (state: ExternalAudioState) => void;
}

export const useAudioReactive = create<AudioReactiveState>((set) => ({
  source: 'none',
  active: false,
  level: 0,
  bands: EMPTY_BANDS,
  externalState: 'idle',
  setFrame: (source, level, bands) =>
    set((state) => {
      // A person explicitly sharing system/tab audio wins over Rafii-owned playback.
      if (source === 'rafii' && state.source === 'external' && state.externalState === 'active')
        return state;
      return { source, active: true, level, bands };
    }),
  deactivate: (source) =>
    set((state) =>
      state.source === source
        ? { source: 'none', active: false, level: 0, bands: EMPTY_BANDS }
        : state
    ),
  setExternalState: (externalState) =>
    set((state) => ({
      externalState,
      ...(externalState === 'idle' && state.source === 'external'
        ? { source: 'none' as const, active: false, level: 0, bands: EMPTY_BANDS }
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

  constructor(
    private readonly source: Exclude<AudioReactiveSource, 'none'>,
    private readonly context: AudioContext,
    analyser: AnalyserNode
  ) {
    this.analyser = analyser;
    this.analyser.fftSize = 512;
    this.analyser.smoothingTimeConstant = 0.78;
    this.frequency = new Uint8Array(new ArrayBuffer(this.analyser.frequencyBinCount));
    this.timeDomain = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
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

    // 30 fps is enough for a fluid rail and avoids turning navigation into a 60 fps React render loop.
    if (now - this.lastCommit >= 33) {
      this.analyser.getByteFrequencyData(this.frequency);
      this.analyser.getByteTimeDomainData(this.timeDomain);
      useAudioReactive
        .getState()
        .setFrame(this.source, rootMeanSquare(this.timeDomain), collapseSpectrum(this.frequency));
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
    // Keep the external graph renderable without sending a second audible copy of the
    // shared device audio back through the page. Some browsers do not advance an analyser
    // that is left disconnected from the destination, which makes the thread rail look frozen.
    const silentSink = context.createGain();
    silentSink.gain.value = 0;
    analyser.connect(silentSink);
    silentSink.connect(context.destination);
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
