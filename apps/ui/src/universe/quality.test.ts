import { describe, expect, it } from 'vitest';
import { detectQuality, stepDown } from './quality';

describe('quality presets', () => {
  it('picks a preset from the graphics hardware', () => {
    expect(detectQuality('ANGLE (NVIDIA GeForce RTX 4070 Direct3D11 vs_5_0 ps_5_0)', true)).toBe('high');
    expect(detectQuality('ANGLE (AMD Radeon RX 7800 XT Direct3D11)', true)).toBe('high');
    expect(detectQuality('ANGLE (Intel(R) UHD Graphics 770 Direct3D11)', true)).toBe('balanced');
    expect(
      detectQuality('ANGLE (Google, Vulkan 1.3.0 (SwiftShader Device (Subzero)), SwiftShader driver)', true),
    ).toBe('lite');
    expect(detectQuality('llvmpipe (LLVM 15.0.7, 256 bits)', true)).toBe('lite');
    expect(detectQuality(null, true)).toBe('balanced');
    expect(detectQuality('anything', false)).toBe('lite');
  });

  it('steps down one preset at a time, never below Lite', () => {
    expect(stepDown('ultra')).toBe('high');
    expect(stepDown('balanced')).toBe('lite');
    expect(stepDown('lite')).toBe('lite');
  });
});
