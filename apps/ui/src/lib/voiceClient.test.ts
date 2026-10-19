import { describe, expect, it } from 'vitest';
import { encodeWav, fromPcm16, toPcm16 } from './voiceClient';

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
