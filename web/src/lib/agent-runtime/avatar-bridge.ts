import type { LiveTransport } from './live-transport';

export type AvatarStatus = 'idle' | 'listening' | 'thinking' | 'speaking' | 'interrupted' | 'offline';
export type AvatarFrame = { generation: number; sequence: number; jpeg: string; generatedAt: number; sourcePcmSentAt?: number | null };
export type AvatarMetrics = {
  connection: 'idle' | 'connecting' | 'connected' | 'reconnecting';
  connectionError: string | null;
  audioReceivedAt: number | null;
  firstPcmSentAt: number | null;
  audioAcceptedAt: number | null;
  firstFrameReceivedAt: number | null;
  firstFrameDisplayedAt: number | null;
  interruptionRequestedAt: number | null;
  cancellationAcknowledgedAt: number | null;
  staleFrameDiscardedAt: number | null;
  visibleStopAt: number | null;
  reconnectMs: number | null;
  steadyFrameIntervalMs: number | null;
  steadyFrameLatencyMs: number | null;
  workerRssBytes: number | null;
  workerRssGrowthBytes: number | null;
  workerCpuPercent: number | null;
  gpuUtilPercent: number | null;
  gpuMemoryUsedBytes: number | null;
  audioToWorkerMs: number | null;
  workerFirstFrameMs: number | null;
  firstAvatarFrameMs: number | null;
  averageFps: number | null;
  queueDepth: number;
  droppedFrames: number;
  droppedAudioPackets: number;
  droppedAudioSamples: number;
  interruptToStopMs: number | null;
};
export type RendererMetric = Partial<AvatarMetrics> & { firstFrameMs?: number };
export type AvatarSnapshot = { status: AvatarStatus; frame: AvatarFrame | null; error: string | null; metrics: AvatarMetrics };

export interface AvatarRenderer {
  startSession(onFrame: (frame: AvatarFrame) => void, onError: (message: string) => void,
    onMetric: (metric: RendererMetric) => void): Promise<void>;
  pushAudio(pcm16: Int16Array, generation: number): void;
  interrupt(generation: number): void;
  endSession(): void;
}

/** Streaming linear resampler. Carries the fractional position and boundary sample across worklet packets. */
export class Pcm16Resampler {
  private inputCount = 0;
  private nextPosition = 0;
  private lastSample = 0;
  private rate = 0;

  reset() { this.inputCount = 0; this.nextPosition = 0; this.lastSample = 0; this.rate = 0; }

  convert(input: Float32Array, rate: number): Int16Array {
    if (!input.length || !Number.isFinite(rate) || rate < 8000) return new Int16Array();
    if (this.rate && this.rate !== rate) this.reset();
    this.rate = rate;
    const start = this.inputCount;
    const end = start + input.length;
    const values: number[] = [];
    // One future source sample is required for interpolation; keep the tail for the next packet.
    while (this.nextPosition < end - 1) {
      const index = Math.floor(this.nextPosition);
      const offset = this.nextPosition - index;
      const first = index === start - 1 ? this.lastSample : input[index - start];
      const second = input[index + 1 - start];
      if (first === undefined || second === undefined) break;
      const value = Math.max(-1, Math.min(1, first + (second - first) * offset));
      values.push(value < 0 ? Math.round(value * 32768) : Math.round(value * 32767));
      this.nextPosition += rate / 16000;
    }
    this.lastSample = input[input.length - 1];
    this.inputCount = end;
    return Int16Array.from(values);
  }
}

const EMPTY_METRICS: AvatarMetrics = {
  connection: 'idle', connectionError: null, audioReceivedAt: null, firstPcmSentAt: null, audioAcceptedAt: null,
  firstFrameReceivedAt: null, firstFrameDisplayedAt: null, interruptionRequestedAt: null,
  cancellationAcknowledgedAt: null, staleFrameDiscardedAt: null, visibleStopAt: null,
  reconnectMs: null, steadyFrameIntervalMs: null, steadyFrameLatencyMs: null, workerRssBytes: null, workerRssGrowthBytes: null,
  workerCpuPercent: null, gpuUtilPercent: null, gpuMemoryUsedBytes: null,
  audioToWorkerMs: null, workerFirstFrameMs: null, firstAvatarFrameMs: null,
  averageFps: null, queueDepth: 0, droppedFrames: 0, droppedAudioPackets: 0, droppedAudioSamples: 0, interruptToStopMs: null
};

/** One per Live call. No renderer operation is awaited from the transport's audio callback. */
export class AvatarSession {
  private renderer: AvatarRenderer | null = null;
  private offAudio: (() => void) | null = null;
  private listeners = new Set<() => void>();
  private resampler = new Pcm16Resampler();
  private generation = 0;
  private paused = false;
  private closed = false;
  private firstAudioAt: number | null = null;
  private previousFrameAt: number | null = null;
  private previousDisplayAt: number | null = null;
  private lastDisplayedSequence: number | null = null;
  private localDroppedFrames = 0;
  private rendererDroppedFrames = 0;
  private lastSoundAt: number | null = null;
  private interruptAt: number | null = null;
  private idleTimer: ReturnType<typeof setTimeout> | null = null;
  private state: AvatarSnapshot = { status: 'idle', frame: null, error: null, metrics: { ...EMPTY_METRICS } };

  get = () => this.state;
  subscribe = (listener: () => void) => { this.listeners.add(listener); return () => { this.listeners.delete(listener); }; };
  private set(patch: Partial<AvatarSnapshot>) {
    this.state = { ...this.state, ...patch };
    for (const listener of this.listeners) {
      try { listener(); } catch { /* an avatar observer cannot interrupt Live playback */ }
    }
  }
  private metric(patch: Partial<AvatarMetrics>) { this.set({ metrics: { ...this.state.metrics, ...patch } }); }

  async start(transport: LiveTransport, renderer: AvatarRenderer) {
    this.end();
    this.closed = false;
    this.renderer = renderer;
    this.generation = 0;
    this.paused = false;
    this.lastSoundAt = null;
    this.localDroppedFrames = 0;
    this.rendererDroppedFrames = 0;
    this.lastDisplayedSequence = null;
    this.resampler.reset();
    this.set({ status: 'thinking', frame: null, error: null, metrics: { ...EMPTY_METRICS } });
    this.offAudio = transport.onAssistantAudio?.((samples, rate, at) => this.pushAudio(samples, rate, at)) ?? null;
    try {
      await renderer.startSession(
        (frame) => this.receiveFrame(frame),
        (message) => this.fail(message),
        (metric) => {
          if (metric.connection === 'reconnecting' || metric.connection === 'connecting') {
            if (this.state.frame && this.lastDisplayedSequence !== this.state.frame.sequence) this.localDroppedFrames++;
            this.lastDisplayedSequence = null;
            this.set({ status: 'offline', frame: null, error: metric.connectionError ?? null });
          }
          else if (metric.connection === 'connected' && this.state.status === 'offline') this.set({ status: 'thinking', error: null });
          if (metric.droppedFrames !== undefined) this.rendererDroppedFrames = metric.droppedFrames;
          this.metric({ ...metric, queueDepth: metric.queueDepth ?? this.state.metrics.queueDepth,
          firstFrameReceivedAt: this.state.metrics.firstFrameReceivedAt ?? metric.firstFrameReceivedAt ?? null,
          workerFirstFrameMs: metric.firstFrameMs ?? this.state.metrics.workerFirstFrameMs,
          audioToWorkerMs: metric.audioAcceptedAt != null && this.firstAudioAt !== null
            ? metric.audioAcceptedAt - this.firstAudioAt : this.state.metrics.audioToWorkerMs,
          droppedFrames: this.rendererDroppedFrames + this.localDroppedFrames,
          droppedAudioPackets: metric.droppedAudioPackets ?? this.state.metrics.droppedAudioPackets,
          droppedAudioSamples: metric.droppedAudioSamples ?? this.state.metrics.droppedAudioSamples });
        }
      );
      if (this.closed || this.renderer !== renderer) { renderer.endSession(); return; }
    } catch (error) {
      this.fail(error instanceof Error ? error.message : 'Avatar worker unavailable');
    }
  }

  pushAudio(samples: Float32Array, rate: number, at: number) {
    if (this.closed || this.paused || !this.renderer) return;
    const pcm = this.resampler.convert(samples, rate);
    if (!pcm.length) return;
    let energy = 0;
    for (const sample of pcm) energy += Math.abs(sample);
    const audible = energy / pcm.length > 180;
    if (audible) {
      this.lastSoundAt = at;
      if (this.idleTimer) clearTimeout(this.idleTimer);
      this.idleTimer = setTimeout(() => this.retireTurn(), 1500);
    }
    if (this.firstAudioAt === null && !audible) return;
    if (!audible && this.lastSoundAt !== null && at - this.lastSoundAt > 1500) {
      this.retireTurn();
      return;
    }
    if (this.firstAudioAt === null) {
      this.firstAudioAt = at;
      this.previousFrameAt = null;
      this.previousDisplayAt = null;
      this.lastDisplayedSequence = null;
      this.set({ status: this.state.metrics.connection === 'connected' ? 'speaking' : 'offline', frame: null,
        metrics: { ...this.state.metrics, audioReceivedAt: at, firstPcmSentAt: null, audioAcceptedAt: null,
          firstFrameReceivedAt: null, firstFrameDisplayedAt: null, firstAvatarFrameMs: null,
          steadyFrameIntervalMs: null, steadyFrameLatencyMs: null, workerFirstFrameMs: null, audioToWorkerMs: null } });
    }
    try { this.renderer.pushAudio(pcm, this.generation); }
    catch { this.fail('Avatar audio stream failed.'); }
  }

  private retireTurn() {
    if (this.closed || this.paused || !this.renderer || this.firstAudioAt === null) return;
    this.generation++;
    this.firstAudioAt = null;
    this.lastSoundAt = null;
    this.resampler.reset();
    try { this.renderer.interrupt(this.generation); }
    catch { this.fail('Avatar stream failed after speech.'); return; }
    this.set({ status: 'listening', frame: null });
  }

  interrupt() {
    if (this.closed || !this.renderer) return;
    this.generation++;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
    this.paused = true;
    this.firstAudioAt = null;
    this.resampler.reset();
    this.interruptAt = performance.now();
    this.metric({ interruptionRequestedAt: this.interruptAt, cancellationAcknowledgedAt: null, visibleStopAt: null });
    try { this.renderer.interrupt(this.generation); }
    catch { this.fail('Avatar interrupt failed.'); return; }
    this.set({ status: 'interrupted', frame: null, metrics: { ...this.state.metrics, queueDepth: 0 } });
    requestAnimationFrame(() => requestAnimationFrame(() => {
      if (this.interruptAt !== null) {
        const now = performance.now();
        this.metric({ interruptToStopMs: now - this.interruptAt, visibleStopAt: now });
      }
    }));
  }

  resume() {
    if (this.closed) return;
    this.paused = false;
    this.firstAudioAt = null;
    this.resampler.reset();
    this.set({ status: 'thinking', frame: null });
  }

  listening() {
    if (!this.closed && this.state.status !== 'offline' && this.state.status !== 'speaking') this.set({ status: 'listening' });
  }

  receiveFrame(frame: AvatarFrame) {
    if (this.closed || this.paused || frame.generation !== this.generation || this.state.status === 'offline') {
      this.localDroppedFrames++;
      this.metric({ droppedFrames: this.rendererDroppedFrames + this.localDroppedFrames, staleFrameDiscardedAt: performance.now() });
      return;
    }
    if (this.state.frame && this.lastDisplayedSequence !== this.state.frame.sequence) this.localDroppedFrames++;
    const now = performance.now();
    const first = this.previousFrameAt === null;
    const elapsed = first ? 0 : now - this.previousFrameAt!;
    this.previousFrameAt = now;
    this.set({ status: 'speaking', frame,
      metrics: { ...this.state.metrics,
        droppedFrames: this.rendererDroppedFrames + this.localDroppedFrames,
        workerFirstFrameMs: this.state.metrics.workerFirstFrameMs,
        averageFps: first ? null : (this.state.metrics.averageFps ?? (1000 / elapsed)) * 0.8 + (1000 / Math.max(1, elapsed)) * 0.2 }
    });
  }

  displayed(sequence: number) {
    const frame = this.state.frame;
    if (frame?.sequence !== sequence || this.firstAudioAt === null) return;
    const now = performance.now();
    this.metric({ firstAvatarFrameMs: this.state.metrics.firstAvatarFrameMs ?? now - this.firstAudioAt,
      firstFrameDisplayedAt: this.state.metrics.firstFrameDisplayedAt ?? now,
      steadyFrameLatencyMs: frame.sourcePcmSentAt == null ? null : now - frame.sourcePcmSentAt,
      steadyFrameIntervalMs: this.previousDisplayAt === null ? null : now - this.previousDisplayAt });
    this.previousDisplayAt = now;
    this.lastDisplayedSequence = sequence;
  }

  fail(message: string) {
    if (this.closed) return;
    this.offAudio?.();
    this.offAudio = null;
    this.renderer?.endSession();
    this.renderer = null;
    this.set({ status: 'offline', frame: null, error: message });
  }

  end() {
    this.closed = true;
    if (this.idleTimer) clearTimeout(this.idleTimer);
    this.idleTimer = null;
    this.offAudio?.();
    this.offAudio = null;
    this.renderer?.endSession();
    this.renderer = null;
    this.firstAudioAt = null;
    this.set({ status: 'idle', frame: null, error: null });
  }
}

export const avatarSession = new AvatarSession();
