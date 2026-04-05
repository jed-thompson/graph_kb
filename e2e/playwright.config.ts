import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for GraphKB E2E tests.
 *
 * Prerequisites:
 *   1. docker compose up          (starts API on :8000 + Postgres, Neo4j, Chroma, MinIO)
 *   2. cd graph_kb_dashboard && npm run dev   (starts Next.js dashboard on :3000)
 *   3. cd e2e && npx playwright test
 */
export default defineConfig({
  testDir: './tests',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  timeout: 900_000,
  expect: {
    timeout: 30_000,
  },
  use: {
    // Dashboard served by `npm run dev` in graph_kb_dashboard/
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    trace: 'on-first-retry',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
