import { defineConfig } from 'vitest/config';

export default defineConfig({
  test: {
    projects: [
      { test: { name: 'ui', include: ['apps/ui/src/**/*.test.ts'], environment: 'node' } },
      { test: { name: 'desktop', include: ['apps/desktop/src/**/*.test.ts'], environment: 'node' } },
      { test: { name: 'scripts', include: ['scripts/**/*.test.mjs'], environment: 'node' } },
      { test: { name: 'design-tokens', include: ['packages/design-tokens/*.test.ts'], environment: 'node' } },
    ],
  },
});
