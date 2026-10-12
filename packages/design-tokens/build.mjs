// Generates CSS (Tailwind v4 @theme + :root vars) and TypeScript constants from tokens.json.
// `node build.mjs --check` fails if the committed output is stale (run in CI).
import { readFileSync, writeFileSync, mkdirSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

const here = dirname(fileURLToPath(import.meta.url));
const tokens = JSON.parse(readFileSync(join(here, 'tokens.json'), 'utf8'));
const HEADER = '/* GENERATED from packages/design-tokens/tokens.json by build.mjs. Do not edit. */\n';

function flatten(obj, prefix = []) {
  return Object.entries(obj).flatMap(([key, value]) =>
    key.startsWith('$')
      ? []
      : typeof value === 'object'
        ? flatten(value, [...prefix, key])
        : [[[...prefix, key].join('-'), value]],
  );
}

export function renderCss(t) {
  const theme = [
    '  --color-*: initial; /* only token colors exist: no ad-hoc palette */',
    ...flatten(t.color).map(([k, v]) => `  --color-${k}: ${v};`),
    ...flatten(t.font).map(([k, v]) => `  --font-${k}: ${v};`),
    ...flatten(t.text).map(([k, v]) => `  --text-${k}: ${v};`),
    ...flatten(t.radius).map(([k, v]) => `  --radius-${k}: ${v};`),
    ...flatten(t.blur).map(([k, v]) => `  --blur-${k}: ${v};`),
    `  --ease-hud: ${t.motion.ease};`,
  ];
  const root = [
    ...flatten(t.motion)
      .filter(([k]) => k !== 'ease')
      .map(([k, v]) => `  --motion-${k}: ${v};`),
    ...flatten(t.z).map(([k, v]) => `  --z-${k}: ${v};`),
  ];
  return `${HEADER}@theme {\n${theme.join('\n')}\n}\n\n:root {\n${root.join('\n')}\n}\n`;
}

export function renderTs(t) {
  const { $description: _description, ...rest } = t;
  return `${HEADER}export const tokens = ${JSON.stringify(rest, null, 2)} as const;\n\nexport type Tokens = typeof tokens;\n`;
}

const outputs = {
  'generated/tokens.css': renderCss(tokens),
  'generated/tokens.ts': renderTs(tokens),
};

if (process.argv.includes('--check')) {
  const stale = Object.entries(outputs).filter(
    ([file, content]) => !existsSync(join(here, file)) || readFileSync(join(here, file), 'utf8') !== content,
  );
  if (stale.length) {
    console.error(`design tokens are stale: ${stale.map(([f]) => f).join(', ')}. Run: pnpm tokens`);
    process.exit(1);
  }
} else if (import.meta.url === `file://${process.argv[1]}` || process.argv[1]?.endsWith('build.mjs')) {
  mkdirSync(join(here, 'generated'), { recursive: true });
  for (const [file, content] of Object.entries(outputs)) writeFileSync(join(here, file), content);
  console.log('design tokens generated');
}
