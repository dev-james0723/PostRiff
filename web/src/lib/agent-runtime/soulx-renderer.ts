import type { AvatarFrame, AvatarRenderer } from './avatar-bridge';

type WorkerMessage = {
  type: string;
  generation?: number;
  sequence?: number;
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
  private controller = new AbortController();
  private closed = false;
  private firstAudioAcknowledged = false;
  private dropped = 0;
  private generation = 0;

  constructor(private readonly baseUrl: string) {}

  async startSession(onFrame: (frame: AvatarFrame) => void, onError: (message: string) => void,
    onMetric: (metric: { queueDepth?: number; firstFrameMs?: number; audioAcceptedAt?: number;
      droppedFrames?: number; droppedAudioPackets?: number; droppedAudioSamples?: number }) => void) {
    const base = new URL(this.baseUrl);
    if (!['http:', 'https:'].includes(base.protocol)) throw new Error('SoulX worker URL must use HTTP or HTTPS.');
    const response = await fetch(new URL('/session', base), { method: 'POST', signal: this.controller.signal });
    if (!response.ok) throw new Error(`SoulX worker refused the session (${response.status}).`);
    const data = await response.json() as { id?: string };
    if (!data.id || this.closed) throw new Error('SoulX session did not start.');
    this.sessionId = data.id;
    const url = new URL(`/session/${encodeURIComponent(data.id)}/stream`, base);
    url.protocol = base.protocol === 'https:' ? 'wss:' : 'ws:';
    await new Promise<void>((resolve, reject) => {
      const socket = new WebSocket(url);
      this.socket = socket;
      socket.binaryType = 'arraybuffer';
      socket.addEventListener('open', () => { if (this.closed) { socket.close(); return; } this.flush(); resolve(); });
      socket.addEventListener('error', () => reject(new Error('SoulX stream connection failed.')));
      socket.addEventListener('close', () => { if (!this.closed) onError('SoulX stream disconnected.'); });
      socket.addEventListener('message', (event) => {
        try {
          const message = JSON.parse(String(event.data)) as WorkerMessage;
          if (message.type === 'frame' && typeof message.jpeg === 'string' && typeof message.generation === 'number' && typeof message.sequence === 'number') {
            onFrame({ generation: message.generation, sequence: message.sequence,
              jpeg: `data:image/jpeg;base64,${message.jpeg}`, generatedAt: performance.now() });
          } else if (message.type === 'audio_accepted' && message.generation === this.generation && !this.firstAudioAcknowledged) {
            this.firstAudioAcknowledged = true;
            onMetric({ audioAcceptedAt: performance.now() });
          } else if (message.type === 'metrics' && message.generation === this.generation) {
            onMetric({ queueDepth: message.queueDepth, firstFrameMs: message.firstFrameMs,
              droppedFrames: message.droppedFrames ?? 0, droppedAudioPackets: this.dropped,
              droppedAudioSamples: message.droppedAudioSamples ?? 0 });
          } else if (message.type === 'error') onError(message.message ?? 'SoulX worker error.');
        } catch { /* a malformed frame cannot affect Live playback */ }
      });
    });
  }

  pushAudio(pcm16: Int16Array, generation: number) {
    if (this.closed || !pcm16.length) return;
    if (generation !== this.generation) return;
    const packet = new ArrayBuffer(4 + pcm16.length * 2);
    const view = new DataView(packet);
    view.setUint32(0, generation, true);
    for (let i = 0; i < pcm16.length; i++) view.setInt16(4 + i * 2, pcm16[i], true);
    if (this.socket?.readyState === WebSocket.OPEN) {
      if (this.socket.bufferedAmount > 256_000) { this.dropped++; return; }
      this.socket.send(packet);
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
      this.socket.send(item.data);
    }
  }

  interrupt(generation: number) {
    this.pending = [];
    this.generation = generation;
    this.firstAudioAcknowledged = false;
    if (this.socket?.readyState === WebSocket.OPEN) this.socket.send(JSON.stringify({ type: 'interrupt', generation }));
  }

  endSession() {
    if (this.closed) return;
    this.closed = true;
    this.controller.abort();
    this.pending = [];
    this.socket?.close();
    if (this.sessionId) void fetch(new URL(`/session/${encodeURIComponent(this.sessionId)}`, this.baseUrl), { method: 'DELETE', keepalive: true }).catch(() => undefined);
  }
}
