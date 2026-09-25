/**
 * GPT-Live transport for the browser (docs: developers.openai.com/api/docs/guides/voice-webrtc, Live variant).
 *
 * Real transport: microphone → RTCPeerConnection with the `oai-events` data channel created before the offer; the offer
 * goes to Rafii's server (never to OpenAI with a browser credential); the server returns the answer from
 * `POST /v1/live/sessions`. Audio flows on the media tracks; events on the data channel. Rafii's speaking level is
 * measured from the remote audio track itself (an AnalyserNode), so "speaking" is never a guessed timer.
 *
 * Fake transport: a scriptable stand-in for browser QA in development builds only (window.RAFII_FAKE_LIVE), driven
 * through window.rafiiLiveHarness. It still calls Rafii's server for the session and for every delegated request.
 */

export interface LiveEvent {
  type: string;
  [key: string]: unknown;
}

export type TransportState = 'connecting' | 'connected' | 'disconnected' | 'failed' | 'closed';

export class VoiceTransportError extends Error {
  code: 'mic_denied' | 'mic_missing' | 'mic_busy' | 'webrtc_unavailable' | 'ice_timeout' | 'negotiation_failed';
  constructor(code: VoiceTransportError['code'], message: string) {
    super(message);
    this.code = code;
  }
}

export interface LiveTransport {
  readonly kind: 'webrtc' | 'fake';
  connect(offer: (sdp: string) => Promise<string>): Promise<void>;
  send(event: Record<string, unknown>): void;
  onEvent(handler: (event: LiveEvent) => void): () => void;
  onState(handler: (state: TransportState) => void): () => void;
  /** True while events can reach the voice service (the data channel is open). */
  connected(): boolean;
  setMicEnabled(on: boolean): void;
  setOutputMuted(muted: boolean): void;
  outputLevel(): number;
  close(): void;
}

class Emitter<T> {
  private handlers = new Set<(value: T) => void>();
  on(handler: (value: T) => void) {
    this.handlers.add(handler);
    return () => {
      this.handlers.delete(handler);
    };
  }
  emit(value: T) {
    for (const handler of this.handlers) handler(value);
  }
}

export class WebRtcLiveTransport implements LiveTransport {
  readonly kind = 'webrtc' as const;
  private pc: RTCPeerConnection | null = null;
  private channel: RTCDataChannel | null = null;
  private mic: MediaStream | null = null;
  private audio: HTMLAudioElement | null = null;
  private context: AudioContext | null = null;
  private analyser: AnalyserNode | null = null;
  private samples: Uint8Array<ArrayBuffer> | null = null;
  private queue: string[] = [];
  private events = new Emitter<LiveEvent>();
  private states = new Emitter<TransportState>();
  private closed = false;

  async connect(offer: (sdp: string) => Promise<string>) {
    if (typeof RTCPeerConnection === 'undefined' || !navigator.mediaDevices?.getUserMedia) {
      throw new VoiceTransportError('webrtc_unavailable', 'This browser can’t do voice calls. You can keep typing.');
    }
    this.states.emit('connecting');
    try {
      // Created inside the click that started the call, so browsers (WebKit in particular) let it run; the level meter uses it.
      this.context = new AudioContext();
      void this.context.resume().catch(() => undefined);
    } catch {
      this.context = null; // the level meter is optional
    }
    try {
      this.mic = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
    } catch (error) {
      const name = (error as { name?: string })?.name;
      if (name === 'NotAllowedError' || name === 'SecurityError') throw new VoiceTransportError('mic_denied', 'Microphone access was not allowed. You can keep typing, or allow the microphone and try again.');
      if (name === 'NotFoundError' || name === 'OverconstrainedError') throw new VoiceTransportError('mic_missing', 'No microphone was found. You can keep typing.');
      throw new VoiceTransportError('mic_busy', 'The microphone is busy in another app. You can keep typing.');
    }
    if (this.closed) {
      // Ended while the browser was asking for the microphone: release it at once.
      for (const track of this.mic.getTracks()) track.stop();
      this.mic = null;
      throw new VoiceTransportError('negotiation_failed', 'Voice Mode was ended.');
    }
    const pc = new RTCPeerConnection();
    this.pc = pc;
    const audio = document.createElement('audio');
    audio.autoplay = true;
    audio.setAttribute('data-rafii-voice-output', '');
    audio.hidden = true;
    document.body.appendChild(audio);
    this.audio = audio;
    pc.addEventListener('track', (event) => {
      const stream = event.streams[0];
      audio.srcObject = stream;
      try {
        this.context ??= new AudioContext();
        void this.context.resume().catch(() => undefined);
        const source = this.context.createMediaStreamSource(stream);
        this.analyser = this.context.createAnalyser();
        this.analyser.fftSize = 512;
        this.samples = new Uint8Array(new ArrayBuffer(this.analyser.fftSize));
        source.connect(this.analyser);
      } catch {
        /* the level meter is optional; speech still plays */
      }
    });
    for (const track of this.mic.getTracks()) pc.addTrack(track, this.mic);
    // Create the data channel and its listeners before the offer (Live WebRTC guide, step 2).
    const channel = pc.createDataChannel('oai-events');
    this.channel = channel;
    channel.addEventListener('message', (message) => {
      try {
        const event = JSON.parse(String(message.data)) as LiveEvent;
        if (event && typeof event.type === 'string') this.events.emit(event);
      } catch {
        /* a malformed event is ignored */
      }
    });
    channel.addEventListener('open', () => {
      for (const item of this.queue.splice(0)) channel.send(item);
    });
    pc.addEventListener('connectionstatechange', () => {
      const state = pc.connectionState;
      if (state === 'connected') this.states.emit('connected');
      else if (state === 'disconnected') this.states.emit('disconnected');
      else if (state === 'failed') this.states.emit('failed');
      else if (state === 'closed') this.states.emit('closed');
    });
    await pc.setLocalDescription(await pc.createOffer());
    await waitForIce(pc, 10_000);
    const local = pc.localDescription?.sdp;
    if (this.closed) throw new VoiceTransportError('negotiation_failed', 'Voice Mode was ended.');
    if (!local) throw new VoiceTransportError('negotiation_failed', 'The voice connection could not be prepared.');
    const answer = await offer(local);
    if (this.closed) throw new VoiceTransportError('negotiation_failed', 'Voice Mode was ended.');
    await pc.setRemoteDescription({ type: 'answer', sdp: answer });
  }

  connected() {
    // The data channel can stay "open" while the connection underneath is down; both must be up.
    return !this.closed && this.channel?.readyState === 'open' && this.pc?.connectionState === 'connected';
  }

  send(event: Record<string, unknown>) {
    const raw = JSON.stringify(event);
    if (this.channel?.readyState === 'open') this.channel.send(raw);
    else this.queue.push(raw);
  }

  onEvent(handler: (event: LiveEvent) => void) {
    return this.events.on(handler);
  }

  onState(handler: (state: TransportState) => void) {
    return this.states.on(handler);
  }

  setMicEnabled(on: boolean) {
    for (const track of this.mic?.getAudioTracks() ?? []) track.enabled = on;
  }

  setOutputMuted(muted: boolean) {
    if (this.audio) this.audio.muted = muted;
  }

  outputLevel() {
    if (!this.analyser || !this.samples || this.audio?.muted) return 0;
    this.analyser.getByteTimeDomainData(this.samples);
    let sum = 0;
    for (const value of this.samples) sum += ((value - 128) / 128) ** 2;
    return Math.min(1, Math.sqrt(sum / this.samples.length) * 4);
  }

  close() {
    this.closed = true;
    try {
      this.channel?.close();
    } catch {
      /* already closed */
    }
    this.pc?.close();
    for (const track of this.mic?.getTracks() ?? []) track.stop();
    void this.context?.close().catch(() => undefined);
    this.audio?.remove();
    this.pc = this.channel = this.mic = this.audio = this.context = this.analyser = null;
  }
}

function waitForIce(pc: RTCPeerConnection, timeout: number) {
  if (pc.iceGatheringState === 'complete') return Promise.resolve();
  return new Promise<void>((resolve) => {
    const timer = setTimeout(done, timeout);
    function done() {
      clearTimeout(timer);
      pc.removeEventListener('icegatheringstatechange', check);
      resolve();
    }
    function check() {
      if (pc.iceGatheringState === 'complete') done();
    }
    pc.addEventListener('icegatheringstatechange', check);
  });
}

/* ------------------------------------------------------------------------------------------------------------------ */
/* Fake transport (development/QA only)                                                                                */
/* ------------------------------------------------------------------------------------------------------------------ */

interface FakeControls {
  sent: Record<string, unknown>[];
  userSays(text: string, options?: { delegate?: boolean }): void;
  rafiiSays(text: string, options?: { chunkMs?: number }): Promise<void>;
  delegate(): string;
  usage(seconds: number): void;
  drop(): void;
  recover(): void;
  close(reason?: string): void;
  speaking(): boolean;
  micEnabled(): boolean;
  outputMuted(): boolean;
}

declare global {
  interface Window {
    RAFII_FAKE_LIVE?: boolean;
    rafiiLiveHarness?: FakeControls;
  }
}

export class FakeLiveTransport implements LiveTransport {
  readonly kind = 'fake' as const;
  private events = new Emitter<LiveEvent>();
  private states = new Emitter<TransportState>();
  private clock = 0;
  private level = 0;
  private mic = true;
  private muted = false;
  private generation = 0;
  private closed = false;
  private dropped = false;

  async connect(offer: (sdp: string) => Promise<string>) {
    this.states.emit('connecting');
    await offer('v=0\r\no=- 0 0 IN IP4 127.0.0.1\r\ns=rafii-fake-live\r\nt=0 0\r\n');
    this.install();
    this.states.emit('connected');
    setTimeout(() => this.emit({ type: 'session.started', session: { id: 'live_fake', expires_at: Math.floor(Date.now() / 1000) + 1800 } }), 20);
  }

  private emit(event: LiveEvent) {
    if (!this.closed) this.events.emit(event);
  }

  private install() {
    const sent: Record<string, unknown>[] = [];
    this.sent = sent;
    const delegate = () => {
      const id = `item_fake_${Math.random().toString(36).slice(2, 10)}`;
      this.emit({ type: 'session.delegation.created', delegation: { id, type: 'delegation', target: 'client' } });
      return id;
    };
    const rafiiSays = async (text: string, options?: { chunkMs?: number }) => {
      const generation = ++this.generation;
      this.level = 0.6;
      for (const word of text.split(/(\s+)/)) {
        if (generation !== this.generation || this.muted) break;
        this.emit({ type: 'session.output_transcript.delta', delta: word, start_ms: (this.clock += 30), end_ms: (this.clock += 30) });
        await new Promise((resolve) => setTimeout(resolve, options?.chunkMs ?? 40));
      }
      if (generation === this.generation) this.level = 0;
    };
    window.rafiiLiveHarness = {
      sent,
      userSays: (text, options) => {
        // Barge-in: Live stops its own speech when the user talks (full duplex); the stand-in does the same.
        this.generation += 1;
        this.level = 0;
        const start = (this.clock += 50);
        for (const word of text.split(/(\s+)/)) this.emit({ type: 'session.input_transcript.delta', delta: word, start_ms: start, end_ms: (this.clock += 40) });
        if (options?.delegate !== false) setTimeout(delegate, 30);
      },
      rafiiSays,
      delegate,
      usage: (seconds) => this.emit({ type: 'session.usage.updated', usage: { seconds } }),
      drop: () => {
        this.dropped = true;
        this.states.emit('disconnected');
      },
      recover: () => {
        this.dropped = false;
        this.states.emit('connected');
      },
      close: (reason = 'remote_hangup') => this.emit({ type: 'session.closed', reason, usage: { seconds: 42 } }),
      speaking: () => this.level > 0,
      micEnabled: () => this.mic,
      outputMuted: () => this.muted
    };
  }

  private sent: Record<string, unknown>[] = [];

  send(event: Record<string, unknown>) {
    this.sent.push(event);
    if (typeof event.type === 'string' && event.type.endsWith('.append')) {
      setTimeout(() => this.emit({ type: `${event.type}ed`, client_event_id: event.event_id ?? null }), 5);
      if (event.type === 'session.commentary.append' && typeof event.content === 'string') {
        // The stand-in "speaks" the commentary, as GPT-Live paraphrases it aloud.
        void window.rafiiLiveHarness?.rafiiSays(event.content, { chunkMs: 15 });
      }
      if (event.type === 'session.instructions.append') {
        this.generation += 1;
        this.level = 0;
      }
    }
    if (event.type === 'session.close') setTimeout(() => this.emit({ type: 'session.closed', reason: 'close_requested', usage: { seconds: 42 } }), 10);
  }

  onEvent(handler: (event: LiveEvent) => void) {
    return this.events.on(handler);
  }

  onState(handler: (state: TransportState) => void) {
    return this.states.on(handler);
  }

  connected() {
    return !this.closed && !this.dropped;
  }

  setMicEnabled(on: boolean) {
    this.mic = on;
  }

  setOutputMuted(muted: boolean) {
    this.muted = muted;
    if (muted) {
      this.generation += 1;
      this.level = 0;
    }
  }

  outputLevel() {
    return this.muted ? 0 : this.level;
  }

  close() {
    this.closed = true;
    this.states.emit('closed');
  }
}

export function createTransport(): LiveTransport {
  if (process.env.NODE_ENV !== 'production' && typeof window !== 'undefined' && window.RAFII_FAKE_LIVE === true) return new FakeLiveTransport();
  return new WebRtcLiveTransport();
}
