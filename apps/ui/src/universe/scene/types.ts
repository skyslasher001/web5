// The celestial mapping (SPEC §7): what each item type looks like in the universe. Every shape comes with
// its type's semantic hue (ARCHITECTURE.md §6.2), so colour is never the only cue.
import type { ItemType } from '@universe/shared-types';
import { ITEM_TYPES } from '../../lib/itemTypes';

export const TYPE_ORDER = Object.keys(ITEM_TYPES) as ItemType[];
export const TYPE_CODE = new Map<string, number>(TYPE_ORDER.map((t, i) => [t, i]));

/** Shapes the point shader draws (keep in sync with `SHAPE_*` in shaders.ts). */
export const Shape = {
  star: 0,
  planet: 1,
  pulsar: 2,
  moon: 3,
  station: 4,
  satellite: 5,
  nebula: 6,
  protostar: 7,
} as const;
export type ShapeCode = (typeof Shape)[keyof typeof Shape];

export interface CelestialStyle {
  shape: ShapeCode;
  /** World-space size before importance scaling. */
  size: number;
  /** What it is called in labels and screen-reader text. */
  body: string;
}

const STYLES: Record<ItemType, CelestialStyle> = {
  note: { shape: Shape.star, size: 1.4, body: 'star' },
  transcript: { shape: Shape.star, size: 1.2, body: 'star' },
  idea: { shape: Shape.nebula, size: 2.4, body: 'nebula' },
  song: { shape: Shape.pulsar, size: 1.6, body: 'pulsar' },
  audio: { shape: Shape.pulsar, size: 1.3, body: 'pulsar' },
  voice_memo: { shape: Shape.pulsar, size: 1.2, body: 'pulsar' },
  photo: { shape: Shape.planet, size: 1.8, body: 'planet' },
  screenshot: { shape: Shape.planet, size: 1.4, body: 'planet' },
  video: { shape: Shape.planet, size: 2.0, body: 'planet' },
  document: { shape: Shape.moon, size: 1.2, body: 'moon' },
  pdf: { shape: Shape.moon, size: 1.3, body: 'moon' },
  spreadsheet: { shape: Shape.moon, size: 1.2, body: 'moon' },
  file: { shape: Shape.moon, size: 0.9, body: 'asteroid' },
  folder: { shape: Shape.moon, size: 1.0, body: 'asteroid' },
  code_repo: { shape: Shape.station, size: 2.6, body: 'space station' },
  code_file: { shape: Shape.station, size: 1.1, body: 'station module' },
  link: { shape: Shape.satellite, size: 1.0, body: 'satellite' },
};

/** An idea matures: nebula → protostar → star (SPEC §7). */
export function styleFor(type: ItemType, ideaStage: string | null): CelestialStyle {
  if (type === 'idea') {
    if (ideaStage === 'protostar') return { shape: Shape.protostar, size: 1.9, body: 'protostar' };
    if (ideaStage === 'star' || ideaStage === 'promoted')
      return { shape: Shape.star, size: 1.7, body: 'star' };
  }
  return STYLES[type];
}

export const IDEA_STAGES = ['', 'nebula', 'protostar', 'star', 'promoted'] as const;
