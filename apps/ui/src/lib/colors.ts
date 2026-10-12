import { tokens } from '@universe/design-tokens';

const HUES = ['cyan', 'violet', 'amber', 'rose', 'green', 'blue', 'slate'] as const;
export type Hue = (typeof HUES)[number];

/** Agent/project colors are token names (or #RRGGBB from YAML); resolve to a hex value. */
export function hueHex(color: string | null | undefined): string {
  if (color && (HUES as readonly string[]).includes(color)) return tokens.color[color as Hue];
  if (color && /^#[0-9a-fA-F]{6}$/.test(color)) return color;
  return tokens.color.slate;
}
