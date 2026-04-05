import { defineConfig, devices } from '@playwright/test';

/** Recording config — video + screenshots for the plan workflow test only. */
export default defineConfig({
  testDir: './tests',
  testMatch: /plan-workflow-phases|debug-context/,
  fullyParallel: false,
  workers: 1,
  reporter: [['list'], ['html', { outputFolder: 'playwright-report' }]],
  timeout: 600_000,
  expect: { timeout: 15_000 },
  outputDir: './test-results',
  use: {
    baseURL: process.env.BASE_URL || 'http://localhost:3000',
    video: 'on',
    screenshot: 'on',
    trace: 'on',
  },
  projects: [
    {
      name: 'chromium',
      use: {
        ...devices['Desktop Chrome'],
        viewport: { width: 1920, height: 1080 },
        video: { mode: 'on', size: { width: 1920, height: 1080 } },
      },
    },
  ],
});
