import { defineConfig, devices } from '@playwright/test';

/**
 * Playwright config for GraphKB Dashboard E2E tests.
 *
 * Prerequisites:
 *   1. Start the API backend (e.g., docker compose up)
 *   2. cd graph_kb_dashboard && npm run dev   (starts Next.js on :3000)
 *   3. npx playwright test
 */
export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 2 : 0,
  workers: 1,
  reporter: 'html',
  timeout: 60_000,
  expect: {
    timeout: 10_000,
  },
  use: {
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
