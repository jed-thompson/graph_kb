import { defineConfig, devices } from '@playwright/test';

/** Mock config — uses pre-recorded LLM responses for fast test replay. */
export default defineConfig({
  testDir: './tests',
  testMatch: /plan-phase-|plan-full-workflow/,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report' }]],
  timeout: 60_000,
  expect: { timeout: 15_000 },
  outputDir: './test-results',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    screenshot: 'on',
    trace: 'retain-on-failure',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1920, height: 1080 },
      },
    },
  ],
});
