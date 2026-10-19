// The renderer's half of voice (SPEC §11, ARCHITECTURE §1.2): the mic is captured here, with Chromium's echo
// cancellation, noise suppression and gain control, at 16 kHz, and streamed as PCM16 over Core's /ws/voice; spoken
// answers come back as 24 kHz PCM16 and play through a gap-free queue. Barge-in: the voice process says
// `barge_in` when you start talking over an answer, and playback stops at once.
//
// The mic only opens when Electron main says you consented (protected code; off at every launch). Audio is never
// stored, except a memo you record and save.
import type { ConsentState } from '@universe/shared-types';
import { create } from 'zustand';
import type { VoiceMode } from './voiceCommands';

export type OrbState = 'off' | 'idle' | 'listening' | 'thinking' | 'speaking';

export interface VoiceEvent {
  type: string;
  [key: string]: unknown;
}

interface VoiceStore {
  state: OrbState;
  connected: boolean;
  micOn: boolean;
  mode: VoiceMode;
  levels: number[]; // the waveform: the last ~2.4 s of mic levels
  heard: string | null; // the last thing you said
  reply: string | null; // what's being said back
  error: string | null;
  consent: ConsentState;
  memo: { startedAt: number } | null;
  dictation: boolean;
  /** End of your speech → first spoken audio, for the last answer (SPEC §21: < 1.5 s). */
  latencyMs: number | null;
  set(patch: Partial<Omit<VoiceStore, 'set'>>): void;
}

const NO_CONSENT: ConsentState = { available: false, mic: false, reason: null };
const LEVELS = 24;

export const useVoice = create<VoiceStore>((set) => ({
  state: 'off',
  connected: false,
  micOn: false,
  mode: 'push_to_talk',
  levels: Array.from({ length: LEVELS }, () => 0),
  heard: null,
  reply: null,
  error: null,
  consent: NO_CONSENT,
  memo: null,
  dictation: false,
  latencyMs: null,
  set: (patch) => set(patch),
}));

/** float32 [-1, 1] → little-endian PCM16. */
export function toPcm16(frame: Float32Array): ArrayBuffer {
  const out = new Int16Array(frame.length);
  for (let i = 0; i < frame.length; i++) {
    const v = Math.max(-1, Math.min(1, frame[i]!));
    out[i] = v < 0 ? v * 0x8000 : v * 0x7fff;
  }
  return out.buffer;
}

export function fromPcm16(data: ArrayBuffer): Float32Array {
  const pcm = new Int16Array(data);
  const out = new Float32Array(pcm.length);
  for (let i = 0; i < pcm.length; i++) out[i] = pcm[i]! / 0x8000;
  return out;
}

/** A 16-bit mono WAV, for saving a memo. */
export function encodeWav(samples: Float32Array, rate: number): Blob {
  const pcm = new Int16Array(toPcm16(samples));
  const header = new ArrayBuffer(44);
  const v = new DataView(header);
  const ascii = (offset: number, text: string) =>
    [...text].forEach((c, i) => v.setUint8(offset + i, c.charCodeAt(0)));
  ascii(0, 'RIFF');
  v.setUint32(4, 36 + pcm.byteLength, true);
  ascii(8, 'WAVE');
  ascii(12, 'fmt ');
  v.setUint32(16, 16, true);
  v.setUint16(20, 1, true); // PCM
  v.setUint16(22, 1, true); // mono
  v.setUint32(24, rate, true);
  v.setUint32(28, rate * 2, true);
  v.setUint16(32, 2, true);
  v.setUint16(34, 16, true);
  ascii(36, 'data');
  v.setUint32(40, pcm.byteLength, true);
  return new Blob([header, pcm.buffer], { type: 'audio/wav' });
}

const CAPTURE_RATE = 16000;
const MAX_MEMO_S = 30 * 60;

type Listener = (event: VoiceEvent) => void;

/** One per window. `connect` opens the socket (speaking works without a mic); `startMic` adds listening. */
export class VoiceClient {
  private ws: WebSocket | null = null;
  private listeners = new Set<Listener>();
  private pendingAudio: VoiceEvent | null = null;
  // playback
  private out: AudioContext | null = null;
  private nextAt = 0;
  private sources = new Set<AudioBufferSourceNode>();
  private speechSeq = 0;
  private muted = new Set<string>(); // speech ids cut off by barge-in or stop
  private firstAudioWanted: number | null = null; // performance.now() at end of speech
  // capture
  private stream: MediaStream | null = null;
  private mic: AudioContext | null = null;
  private node: AudioWorkletNode | null = null;
  private memoFrames: Float32Array[] = [];

  constructor(private readonly socketUrl: () => Promise<string>) {}

  on(listener: Listener): () => void {
    this.listeners.add(listener);
    return () => this.listeners.delete(listener);
  }

  get connected(): boolean {
    return this.ws?.readyState === WebSocket.OPEN;
  }

  async connect(): Promise<void> {
    if (this.ws && this.ws.readyState <= WebSocket.OPEN) return;
    const url = await this.socketUrl();
    await new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(url);
      ws.binaryType = 'arraybuffer';
      ws.onopen = () => resolve();
      ws.onerror = () => reject(new Error('The voice connection failed'));
      ws.onclose = (e) => {
        if (this.ws === ws) this.ws = null;
        this.stopPlayback();
        useVoice.getState().set({ connected: false, state: 'off' });
        this.emit({ type: 'closed', code: e.code, reason: e.reason });
      };
      ws.onmessage = (e) => this.onMessage(e.data as string | ArrayBuffer);
      this.ws = ws;
    });
    useVoice.getState().set({ connected: true, state: 'idle', error: null });
  }

  disconnect(): void {
    this.stopMic();
    this.ws?.close();
    this.ws = null;
  }

  private send(message: object | ArrayBuffer): void {
    if (this.ws?.readyState !== WebSocket.OPEN) return;
    this.ws.send(message instanceof ArrayBuffer ? message : JSON.stringify(message));
  }

  private emit(event: VoiceEvent): void {
    this.listeners.forEach((l) => l(event));
  }

  private onMessage(data: string | ArrayBuffer): void {
    if (typeof data !== 'string') {
      const header = this.pendingAudio;
      this.pendingAudio = null;
      if (header && !this.muted.has(String(header.id)))
        this.play(fromPcm16(data), Number(header.rate) || 24000);
      return;
    }
    let event: VoiceEvent;
    try {
      event = JSON.parse(data) as VoiceEvent;
    } catch {
      return;
    }
    const store = useVoice.getState();
    switch (event.type) {
      case 'audio':
        this.pendingAudio = event;
        return;
      case 'level': {
        const levels = [...store.levels.slice(1), Number(event.value) || 0];
        store.set({ levels });
        return;
      }
      case 'state':
        if (!this.sources.size) store.set({ state: event.state as OrbState });
        break;
      case 'mode':
        store.set({ mode: event.mode as VoiceMode });
        break;
      case 'barge_in':
        this.stopSpeaking();
        break;
      case 'final':
        // When you stopped talking: now, minus Whisper's time and the silence it took to notice you'd finished.
        this.firstAudioWanted =
          performance.now() - (Number(event.stt_s ?? 0) + Number(event.waited_s ?? 0)) * 1000;
        store.set({ heard: String(event.text ?? '') });
        break;
      case 'ready':
        if (event.mode) store.set({ mode: event.mode as VoiceMode });
        break;
      case 'error':
        store.set({ error: String(event.message ?? 'voice error') });
        break;
    }
    this.emit(event);
  }

  // ---------- speaking ----------

  /** Queue a sentence in a voice. Returns its id (to cut it off later). */
  speak(text: string, voice?: string, speed?: number): string {
    const id = `s${++this.speechSeq}`;
    if (text.trim()) this.send({ type: 'speak', text, voice, speed, id });
    return id;
  }

  /** Stop talking now: drop the queue, tell the voice process to stop synthesising. */
  stopSpeaking(): void {
    for (let i = 1; i <= this.speechSeq; i++) this.muted.add(`s${i}`);
    this.send({ type: 'stop' });
    this.stopPlayback();
  }

  get speaking(): boolean {
    return this.sources.size > 0;
  }

  private play(samples: Float32Array, rate: number): void {
    if (!this.out) this.out = new AudioContext();
    const ctx = this.out;
    void ctx.resume();
    const buffer = ctx.createBuffer(1, samples.length, rate);
    buffer.copyToChannel(samples as Float32Array<ArrayBuffer>, 0);
    const source = ctx.createBufferSource();
    source.buffer = buffer;
    source.connect(ctx.destination);
    const at = Math.max(ctx.currentTime + 0.02, this.nextAt);
    source.start(at);
    this.nextAt = at + buffer.duration;
    if (this.sources.size === 0) {
      this.send({ type: 'playing', playing: true });
      useVoice.getState().set({ state: 'speaking' });
      if (this.firstAudioWanted !== null) {
        useVoice.getState().set({ latencyMs: Math.round(performance.now() - this.firstAudioWanted) });
        this.firstAudioWanted = null;
      }
    }
    this.sources.add(source);
    source.onended = () => {
      this.sources.delete(source);
      if (this.sources.size === 0) this.finished();
    };
  }

  private stopPlayback(): void {
    const had = this.sources.size > 0;
    this.sources.forEach((s) => {
      s.onended = null;
      try {
        s.stop();
      } catch {
        // already stopped
      }
    });
    this.sources.clear();
    this.nextAt = 0;
    if (had) this.finished();
  }

  private finished(): void {
    this.send({ type: 'playing', playing: false });
    const s = useVoice.getState();
    if (s.state === 'speaking') s.set({ state: this.connected ? 'idle' : 'off' });
    this.emit({ type: 'playback_ended' });
  }

  /** A new answer is starting: earlier cut-offs don't apply to it. */
  newAnswer(): void {
    this.muted.clear();
  }

  // ---------- listening ----------

  setMode(mode: VoiceMode): void {
    this.send({ type: 'mode', mode });
    useVoice.getState().set({ mode });
  }

  push(down: boolean): void {
    if (down && this.speaking) this.stopSpeaking(); // pressing to talk is a barge-in too
    this.send({ type: 'push', down });
  }

  async startMic(): Promise<void> {
    if (this.stream) return;
    this.stream = await navigator.mediaDevices.getUserMedia({
      audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true, channelCount: 1 },
    });
    this.mic = new AudioContext({ sampleRate: CAPTURE_RATE });
    await this.mic.audioWorklet.addModule(new URL('./voice-capture.worklet.js', document.baseURI).href);
    const source = this.mic.createMediaStreamSource(this.stream);
    this.node = new AudioWorkletNode(this.mic, 'voice-capture');
    this.node.port.onmessage = (e: MessageEvent<Float32Array>) => {
      const frame = e.data;
      if (useVoice.getState().memo) {
        this.memoFrames.push(frame);
        if (this.memoFrames.length * frame.length > MAX_MEMO_S * CAPTURE_RATE)
          this.emit({ type: 'memo_full' });
      }
      this.send(toPcm16(frame));
    };
    source.connect(this.node);
    useVoice.getState().set({ micOn: true });
  }

  stopMic(): void {
    this.node?.disconnect();
    this.node = null;
    this.stream?.getTracks().forEach((t) => t.stop());
    this.stream = null;
    void this.mic?.close();
    this.mic = null;
    useVoice.getState().set({ micOn: false, memo: null });
    this.memoFrames = [];
  }

  // ---------- memos ----------

  startMemo(): void {
    this.memoFrames = [];
    useVoice.getState().set({ memo: { startedAt: Date.now() } });
  }

  /** The recorded memo as a WAV, minus the last `trimS` seconds (the "save the memo" you just said). */
  finishMemo(trimS = 0): Blob | null {
    const frames = this.memoFrames;
    this.memoFrames = [];
    useVoice.getState().set({ memo: null });
    const total = frames.reduce((n, f) => n + f.length, 0);
    const keep = Math.max(0, total - Math.round(trimS * CAPTURE_RATE));
    if (keep < CAPTURE_RATE / 2) return null;
    const samples = new Float32Array(keep);
    let offset = 0;
    for (const f of frames) {
      if (offset >= keep) break;
      samples.set(f.subarray(0, Math.min(f.length, keep - offset)), offset);
      offset += f.length;
    }
    return encodeWav(samples, CAPTURE_RATE);
  }

  cancelMemo(): void {
    this.memoFrames = [];
    useVoice.getState().set({ memo: null });
  }
}
