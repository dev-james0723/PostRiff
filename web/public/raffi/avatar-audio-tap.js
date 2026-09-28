// Observe the remote Live track without altering its normal <audio> playback path.
class RafiiAvatarAudioTap extends AudioWorkletProcessor {
  constructor() {
    super();
    this.chunks = [];
    this.length = 0;
  }

  process(inputs, outputs) {
    for (const output of outputs) for (const channel of output) channel.fill(0);
    const channels = inputs[0];
    if (!channels?.length) return true;
    const mono = new Float32Array(channels[0].length);
    for (const channel of channels) for (let i = 0; i < mono.length; i++) mono[i] += channel[i] / channels.length;
    this.chunks.push(mono);
    this.length += mono.length;
    if (this.length >= 2048) {
      const packet = new Float32Array(this.length);
      let offset = 0;
      for (const chunk of this.chunks) { packet.set(chunk, offset); offset += chunk.length; }
      this.chunks = [];
      this.length = 0;
      this.port.postMessage(packet, [packet.buffer]);
    }
    return true;
  }
}

registerProcessor('rafii-avatar-audio-tap', RafiiAvatarAudioTap);
