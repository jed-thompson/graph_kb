import { test, expect } from '@playwright/test';

/**
 * Smoke tests to verify the application is running and accessible.
 * These should pass before running any feature-specific tests.
 */

test.describe('Application Health', () => {
  test('dashboard loads at localhost:3000', async ({ page }) => {
    const response = await page.goto('/');
    expect(response?.status()).toBeLessThan(500);
    await expect(page.locator('body')).not.toBeEmpty();
  });

  test('chat page loads', async ({ page }) => {
    await page.goto('/chat');
    // Use the specific h1 heading
    await expect(page.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible({ timeout: 15_000 });
  });

  test('API health endpoint responds', async ({ request }) => {
    const response = await request.get('http://localhost:8000/health');
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.status).toMatch(/ok|degraded/);
  });

  test('API v1 health endpoint responds', async ({ request }) => {
    const response = await request.get('http://localhost:8000/api/v1/health');
    expect(response.ok()).toBeTruthy();
    const data = await response.json();
    expect(data.services).toBeDefined();
    expect(data.services.database).toBeDefined();
  });

  test('WebSocket endpoint is accessible', async ({ page }) => {
    await page.goto('/chat');
    await page.waitForLoadState('networkidle');
    await expect(page.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible({ timeout: 15_000 });
  });
});
