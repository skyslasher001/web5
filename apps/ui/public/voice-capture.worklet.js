/* global AudioWorkletProcessor, registerProcessor */
// AudioWorklet for the microphone (Phase 7): forwards 20 ms frames of mono float audio to the page, which
// converts them to 16-bit PCM for the voice socket. The AudioContext runs at 16 kHz, so Chromium resamples the
// mic for us, after its echo cancellation, noise suppression and gain control.
class VoiceCapture extends AudioWorkletProcessor {
  constructor() {
    super();
    this.frame = new Float32Array(320);
    this.filled = 0;
  }

  process(inputs) {
    const channel = inputs[0] && inputs[0][0];
    if (!channel) return true;
    let offset = 0;
    while (offset < channel.length) {
      const n = Math.min(channel.length - offset, this.frame.length - this.filled);
      this.frame.set(channel.subarray(offset, offset + n), this.filled);
      this.filled += n;
      offset += n;
      if (this.filled === this.frame.length) {
        this.port.postMessage(this.frame.slice(0));
        this.filled = 0;
      }
    }
    return true;
  }
}

registerProcessor('voice-capture', VoiceCapture);
