import { readFileSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { describe, expect, it } from 'vitest';
import { tokens } from './generated/tokens';

function luminance(hex: string): number {
  const [r, g, b] = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  }) as [number, number, number];
  return 0.2126 * r + 0.7152 * g + 0.0722 * b;
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x) as [number, number];
  return (hi + 0.05) / (lo + 0.05);
}

describe('design tokens', () => {
  it('text colors meet WCAG AA on every surface', () => {
    for (const surface of Object.values(tokens.color.space)) {
      expect(contrast(tokens.color.ink['1'], surface)).toBeGreaterThanOrEqual(7);
      expect(contrast(tokens.color.ink['2'], surface)).toBeGreaterThanOrEqual(4.5);
      expect(contrast(tokens.color.ink['3'], surface)).toBeGreaterThanOrEqual(4.5);
    }
  });

  it('stays within the eight-hue budget', () => {
    const hues = ['cyan', 'violet', 'amber', 'rose', 'green', 'blue', 'slate', 'danger'] as const;
    expect(new Set(hues.map((h) => tokens.color[h])).size).toBe(8);
  });

  it('generated files match tokens.json', async () => {
    // @ts-expect-error -- plain ESM build script without type declarations
    const build = (await import('./build.mjs')) as {
      renderCss: (t: unknown) => string;
      renderTs: (t: unknown) => string;
    };
    const here = (file: string) => fileURLToPath(new URL(file, import.meta.url));
    const source = JSON.parse(readFileSync(here('./tokens.json'), 'utf8'));
    expect(readFileSync(here('./generated/tokens.css'), 'utf8')).toBe(build.renderCss(source));
    expect(readFileSync(here('./generated/tokens.ts'), 'utf8')).toBe(build.renderTs(source));
  });
});
