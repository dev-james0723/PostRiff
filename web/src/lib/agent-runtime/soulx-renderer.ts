import type { AvatarFrame, AvatarRenderer, RendererMetric } from './avatar-bridge';

type WorkerMessage = {
  type: string;
  sessionId?: string;
  generation?: number;
  sequence?: number;
  sourcePacketId?: number;
  jpeg?: string;
  queueDepth?: number;
  firstFrameMs?: number;
  droppedFrames?: number;
  droppedAudioSamples?: number;
  message?: string;
};

/** Local/SSH-tunnel POC transport. Binary packets are uint32 generation + 16 kHz mono PCM16 LE. */
export class SoulXRenderer implements AvatarRenderer {
  private socket: WebSocket | null = null;
  private sessionId: string | null = null;
  private pending: { generation: number; data: ArrayBuffer }[] = [];
  private controller: AbortController | null = null;
  private connectTask: Promise<void> | null = null;
  private retryTimer: ReturnType<typeof setTimeout> | null = null;
  private wakeRetry: (() => void) | null = null;
  private healthTimer: ReturnType<typeof setInterval> | null = null;
  private reconnectAt: number | null = null;
  private socketEpoch = 0;
  private firstPcmSent = false;
  private firstRss: number | null = null;
  private workerPid: number | null = null;
  private previousCpu: { at: number; seconds: number } | null = null;
  private nextPacketId = 0;
  private sentAt = new Map<number, number>();
  private onFrame: (frame: AvatarFrame) => void = () => undefined;
  private onMetric: (metric: RendererMetric) => void = () => undefined;
  private closed = false;
  private firstAudioAcknowledged = false;
  private dropped = 0;
  private droppedVideo = 0;
  private generation = 0;

  constructor(private readonly baseUrl: string) {}

  async startSession(onFrame: (frame: AvatarFrame) => void, _onError: (message: string) => void,
    onMetric: (metric: RendererMetric) => void) {
    const base = new URL(this.baseUrl);
    if (!['http:', 'https:'].includes(base.protocol)) throw new Error('SoulX worker URL must use HTTP or HTTPS.');
    this.onFrame = onFrame;
    this.onMetric = onMetric;
    this.ensureConnection();
  }

  private ensureConnection() {
    if (this.closed || this.connectTask || this.socket?.readyState === WebSocket.OPEN) return;
    this.connectTask = this.connectLoop().finally(() => {
      this.connectTask = null;
      if (!this.closed && this.socket?.readyState !== WebSocket.OPEN) this.ensureConnection();
    });
  }

  private async connectLoop() {
    let attempt = 0;
    while (!this.closed) {
      this.onMetric({ connection: this.reconnectAt === null ? 'connecting' : 'reconnecting' });
      try {
        await this.connectOnce();
        if (this.closed) return;
        this.onMetric({ connection: 'connected', connectionError: null,
          reconnectMs: this.reconnectAt === null ? null : performance.now() - this.reconnectAt });
        this.reconnectAt = null;
        this.startHealthPolling();
        return;
      } catch (error) {
        if (this.closed) return;
        this.reconnectAt ??= performance.now();
        this.onMetric({ connection: 'reconnecting', connectionError: error instanceof Error ? error.message : 'SoulX unavailable' });
        await new Promise<void>((resolve) => {
          this.wakeRetry = resolve;
          this.retryTimer = setTimeout(resolve, Math.min(8000, 500 * 2 ** Math.min(attempt++, 4)));
        });
        this.retryTimer = null;
        this.wakeRetry = null;
      }
    }
  }

  private async connectOnce() {
    const base = new URL(this.baseUrl);
    const controller = new AbortController();
    this.controller = controller;
    const fetchTimeout = setTimeout(() => controller.abort(), 4000);
    let newId: string | null = null;
    try {
    const response = await fetch(new URL('/session', base), { method: 'POST', signal: controller.signal });
    if (!response.ok) throw new Error(`SoulX worker refused the session (${response.status}).`);
    const data = await response.json() as { id?: string; protocolVersion?: number };
    if (!data.id) throw new Error('SoulX session did not start.');
    newId = data.id;
    if (data.protocolVersion !== 2) throw new Error('SoulX worker protocol version mismatch.');
    if (this.closed) return;
    this.sessionId = newId;
    const url = new URL(`/session/${encodeURIComponent(data.id)}/stream`, base);
    url.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
    const epoch = ++this.socketEpoch;
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.binaryType = 'arraybuffer';
      const openingTimeout = setTimeout(() => { socket.close(); reject(new Error('SoulX stream timed out.')); }, 4000);
      socket.addEventListener('open', () => {
        clearTimeout(openingTimeout);
        if (this.closed || epoch !== this.socketEpoch) { socket.close(); return; }
        if (this.generation) {
          try { socket.send(JSON.stringify({ type: 'interrupt', generation: this.generation })); }
          catch { socket.close(); reject(new Error('SoulX generation sync failed.')); return; }
        }
        this.flush(); resolve();
      });
      socket.addEventListener('error', () => { clearTimeout(openingTimeout); reject(new Error('SoulX stream connection failed.')); });
      socket.addEventListener('close', () => {
        clearTimeout(openingTimeout);
        if (epoch !== this.socketEpoch) return;
        if (this.socket === socket) this.socket = null;
        this.stopHealthPolling();
        this.releaseSession();
        if (!this.closed) {
          this.reconnectAt ??= performance.now();
          this.onMetric({ connection: 'reconnecting', connectionError: 'SoulX stream disconnected.' });
          queueMicrotask(() => this.ensureConnection());
        }
      });
      socket.addEventListener('message', (event) => {
        if (this.closed || epoch !== this.socketEpoch || this.sessionId !== data.id) return;
        try {
          const message = JSON.parse(String(event.data)) as WorkerMessage;
          if (message.sessionId !== data.id) return;
          if (message.type === 'frame' && typeof message.jpeg === 'string' && typeof message.generation === 'number' && typeof message.sequence === 'number') {
            if (message.generation !== this.generation) {
              this.droppedVideo++; this.onMetric({ droppedFrames: this.droppedVideo, staleFrameDiscardedAt: performance.now() }); return;
            }
            this.onMetric({ firstFrameReceivedAt: performance.now() });
            this.onFrame({ generation: message.generation, sequence: message.sequence,
              jpeg: `data:image/jpeg;base64,${message.jpeg}`, generatedAt: performance.now(),
              sourcePcmSentAt: message.sourcePacketId === undefined ? null : this.sentAt.get(message.sourcePacketId) ?? null });
          } else if (message.type === 'audio_accepted' && message.generation === this.generation && !this.firstAudioAcknowledged) {
            this.firstAudioAcknowledged = true;
            this.onMetric({ audioAcceptedAt: performance.now() });
          } else if (message.type === 'metrics' && message.generation === this.generation) {
            this.onMetric({ queueDepth: message.queueDepth, firstFrameMs: message.firstFrameMs,
              droppedFrames: (message.droppedFrames ?? 0) + this.droppedVideo, droppedAudioPackets: this.dropped,
              droppedAudioSamples: message.droppedAudioSamples ?? 0 });
          } else if (message.type === 'interrupted' && message.generation === this.generation) {
            this.onMetric({ cancellationAcknowledgedAt: performance.now() });
          } else if (message.type === 'error') socket.close();
        } catch { /* a malformed frame cannot affect Live playback */ }
      });
    });
    } finally {
      clearTimeout(fetchTimeout);
      if (this.controller === controller) this.controller = null;
      if (this.socket?.readyState !== WebSocket.OPEN && newId) this.releaseSession(newId);
    }
  }

  pushAudio(pcm16: Int16Array, generation: number) {
    if (this.closed || !pcm16.length) return;
    if (generation !== this.generation) return;
    const packet = new ArrayBuffer(8 + pcm16.length * 2);
    const view = new DataView(packet);
    view.setUint32(0, generation, true);
    view.setUint32(4, ++this.nextPacketId, true);
    for (let i = 0; i < pcm16.length; i++) view.setInt16(8 + i * 2, pcm16[i], true);
    if (this.socket?.readyState === WebSocket.OPEN) {
      if (this.socket.bufferedAmount > 256_000) { this.dropped++; return; }
      try {
        this.socket.send(packet);
        this.recordSent(packet);
        if (!this.firstPcmSent) { this.firstPcmSent = true; this.onMetric({ firstPcmSentAt: performance.now() }); }
      } catch { this.dropped++; this.socket.close(); }
    } else {
      this.pending.push({ generation, data: packet });
      // At most two seconds of 16 kHz PCM, bounded even during a failed startup.
      let bytes = this.pending.reduce((sum, item) => sum + item.data.byteLength, 0);
      while (bytes > 64_000 && this.pending.length) { bytes -= this.pending.shift()!.data.byteLength; this.dropped++; }
    }
  }

  private flush() {
    for (const item of this.pending.splice(0)) {
      if (this.socket?.readyState !== WebSocket.OPEN) break;
      if (this.socket.bufferedAmount > 256_000) { this.dropped++; continue; }
      if (item.generation === this.generation) {
        try {
          this.socket.send(item.data);
          this.recordSent(item.data);
          if (!this.firstPcmSent) { this.firstPcmSent = true; this.onMetric({ firstPcmSentAt: performance.now() }); }
        } catch { this.dropped++; this.socket.close(); break; }
      }
    }
  }

  interrupt(generation: number) {
    this.pending = [];
    this.sentAt.clear();
    this.generation = generation;
    this.firstAudioAcknowledged = false;
    this.firstPcmSent = false;
    if (this.socket?.readyState === WebSocket.OPEN) {
      try { this.socket.send(JSON.stringify({ type: 'interrupt', generation })); }
      catch { this.socket.close(); }
    }
  }

  private recordSent(packet: ArrayBuffer) {
    this.sentAt.set(new DataView(packet).getUint32(4, true), performance.now());
    if (this.sentAt.size > 512) this.sentAt.delete(this.sentAt.keys().next().value!);
  }

  private startHealthPolling() {
    this.stopHealthPolling();
    const poll = async () => {
      if (this.closed || this.socket?.readyState !== WebSocket.OPEN) return;
      try {
        const response = await fetch(new URL('/health', this.baseUrl), { cache: 'no-store', signal: AbortSignal.timeout(2500) });
        if (!response.ok) return;
        const data = await response.json() as { processId?: number; processRssBytes?: number; cpuUserSeconds?: number; cpuSystemSeconds?: number;
          gpuUtilPercent?: number | null; gpuMemoryUsedBytes?: number | null };
        const now = performance.now();
        if (typeof data.processId === 'number' && data.processId !== this.workerPid) {
          this.workerPid = data.processId;
          this.firstRss = null;
          this.previousCpu = null;
        }
        const seconds = (data.cpuUserSeconds ?? 0) + (data.cpuSystemSeconds ?? 0);
        const cpuPercent = this.previousCpu ? (seconds - this.previousCpu.seconds) / ((now - this.previousCpu.at) / 1000) * 100 : null;
        this.previousCpu = { at: now, seconds };
        if (this.firstRss === null && typeof data.processRssBytes === 'number') this.firstRss = data.processRssBytes;
        this.onMetric({ workerRssBytes: data.processRssBytes,
          workerRssGrowthBytes: this.firstRss === null ? null : (data.processRssBytes ?? this.firstRss) - this.firstRss,
          workerCpuPercent: cpuPercent, gpuUtilPercent: data.gpuUtilPercent, gpuMemoryUsedBytes: data.gpuMemoryUsedBytes });
      } catch { /* monitoring cannot affect the avatar or Live */ }
    };
    void poll();
    this.healthTimer = setInterval(() => void poll(), 5000);
  }

  private stopHealthPolling() {
    if (this.healthTimer) clearInterval(this.healthTimer);
    this.healthTimer = null;
  }

  private releaseSession(id = this.sessionId) {
    if (!id) return;
    if (this.sessionId === id) this.sessionId = null;
    void fetch(new URL(`/session/${encodeURIComponent(id)}`, this.baseUrl), { method: 'DELETE', keepalive: true }).catch(() => undefined);
  }

  endSession() {
    if (this.closed) return;
    this.closed = true;
    this.socketEpoch++;
    this.controller?.abort();
    if (this.retryTimer) clearTimeout(this.retryTimer);
    this.wakeRetry?.();
    this.stopHealthPolling();
    this.pending = [];
    this.sentAt.clear();
    this.socket?.close();
    this.socket = null;
    this.releaseSession();
  }
}
