import { afterEach, describe, expect, it, vi } from 'vitest';
import { VoiceClient, encodeWav, fromPcm16, toPcm16, useVoice } from './voiceClient';

describe('PCM16', () => {
  it('round-trips audio and clips what is too loud', () => {
    const audio = new Float32Array([0, 0.5, -0.5, 1, -1, 2, -2]);
    const back = fromPcm16(toPcm16(audio));
    expect(Array.from(back.slice(0, 5)).map((v) => Math.round(v * 1000) / 1000)).toEqual([
      0, 0.5, -0.5, 1, -1,
    ]);
    expect(back[5]).toBeCloseTo(1, 3);
    expect(back[6]).toBe(-1);
  });
});

describe('encodeWav', () => {
  it('writes a 16 kHz mono 16-bit WAV that Core accepts', async () => {
    const wav = encodeWav(new Float32Array(16000), 16000);
    expect(wav.type).toBe('audio/wav');
    const bytes = new DataView(await wav.arrayBuffer());
    const text = (offset: number) =>
      String.fromCharCode(...[0, 1, 2, 3].map((i) => bytes.getUint8(offset + i)));
    expect(text(0)).toBe('RIFF');
    expect(text(8)).toBe('WAVE');
    expect(bytes.getUint16(22, true)).toBe(1); // mono
    expect(bytes.getUint32(24, true)).toBe(16000);
    expect(bytes.getUint16(34, true)).toBe(16);
    expect(bytes.getUint32(40, true)).toBe(32000);
    expect(bytes.byteLength).toBe(44 + 32000);
  });
});

// ---------- review 2026-10-21: regressions (browser audio stubbed: tests run in node) ----------

function stubAudio() {
  const tracks: Array<{ stopped: boolean; stop(): void }> = [];
  let release: (() => void) | null = null;
  const getUserMedia = vi.fn(
    () =>
      new Promise((resolve) => {
        const track = {
          stopped: false,
          stop() {
            this.stopped = true;
          },
        };
        tracks.push(track);
        release = () => resolve({ getTracks: () => [track] });
      }),
  );
  class FakeContext {
    audioWorklet = { addModule: async () => {} };
    createMediaStreamSource = () => ({ connect() {} });
    close = vi.fn(async () => {});
  }
  class FakeNode {
    port: { onmessage: unknown } = { onmessage: null };
    disconnect() {}
  }
  vi.stubGlobal('navigator', { mediaDevices: { getUserMedia } });
  vi.stubGlobal('AudioContext', FakeContext);
  vi.stubGlobal('AudioWorkletNode', FakeNode);
  vi.stubGlobal('document', { baseURI: 'app://universe/index.html' });
  return { getUserMedia, tracks, release: () => release?.() };
}

describe('the microphone', () => {
  afterEach(() => {
    vi.unstubAllGlobals();
    useVoice.getState().set({ micOn: false });
  });

  it('opens once even if you click twice', async () => {
    const audio = stubAudio();
    const client = new VoiceClient(async () => 'ws://x');
    const first = client.startMic();
    const second = client.startMic();
    audio.release();
    await Promise.all([first, second]);
    expect(audio.getUserMedia).toHaveBeenCalledTimes(1);
    client.stopMic();
    expect(audio.tracks.every((t) => t.stopped)).toBe(true);
  });

  it('turning it off while the browser is still opening it leaves nothing open', async () => {
    const audio = stubAudio();
    const client = new VoiceClient(async () => 'ws://x');
    const starting = client.startMic();
    client.stopMic(); // consent revoked (tray, kill switch) before getUserMedia answered
    audio.release();
    await starting;
    expect(audio.tracks[0]!.stopped).toBe(true);
    expect(useVoice.getState().micOn).toBe(false);
  });
});

describe('speech that was cut off', () => {
  it('never plays later, even after a new answer starts', () => {
    const client = new VoiceClient(async () => 'ws://x');
    const played: string[] = [];
    const internals = client as unknown as {
      play(samples: Float32Array, rate: number): void;
      onMessage(data: string | ArrayBuffer): void;
    };
    internals.play = () => played.push('audio');
    const receive = (id: string) => {
      internals.onMessage(JSON.stringify({ type: 'audio', id, seq: 0, rate: 24000 }));
      internals.onMessage(new ArrayBuffer(4));
    };
    client.speak('Old one.');
    client.speak('Old two.');
    client.stopSpeaking(); // "stop" / barge-in
    const next = client.speak('New answer.');
    receive('s2'); // the voice process was still synthesising the old answer
    expect(played).toEqual([]);
    receive(next);
    expect(played).toEqual(['audio']);
  });
});
