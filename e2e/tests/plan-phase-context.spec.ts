import { test, expect } from '@playwright/test';

// TODO (M8): Add backend API-level assertions using getPlanSession() and getArtifact()
//   helpers. Plan Steps 26 requires:
//   - GET /sessions/{id}/artifacts/context.document_section_index → 3+ doc entries with sections array
//   - GET /sessions/{id}/artifacts/context.uploaded_docs → non-empty markdown

/**
 * Plan Workflow — Context Phase Validation Test
 *
 * Tests the context phase of the plan workflow, validating:
 * - Navigation to chat and starting plan workflow
 * - Context form field population (text fields, textareas, URLs, file uploads)
 * - Form submission and transition to analysis review
 *
 * This is the first phase in the 5-phase plan workflow.
 */

import {
  FEDEX_PLAN_CONTEXT,
  FEDEX_REFERENCE_URLS,
  FEDEX_DOCS,
} from './fixtures/plan-fedex-data';
import {
  PAUSE,
  navigateToChat,
  startPlanWorkflow,
  fillContextForm,
} from './helpers/plan';

test.describe.configure({ timeout: 600_000 });

test.describe('Plan Workflow — Context Phase', () => {
  test('context phase: navigate, start plan, fill form, submit', async ({ page }) => {
    // ═══════════════════════════════════════════════════
    // STEP 0: PAGE SETUP
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 0: PAGE SETUP ══');
    await navigateToChat(page);
    await page.evaluate(() => {
      localStorage.removeItem('graphkb-plan-session');
      localStorage.removeItem('graphkb-plan-resume');
    });
    await page.reload();
    await expect(
      page.getByRole('heading', { name: 'Chat', exact: true }),
    ).toBeVisible({ timeout: 15_000 });
    await page.waitForTimeout(PAUSE);

    // ═══════════════════════════════════════════════════
    // STEP 1: START PLAN WORKFLOW
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 1: START PLAN ══');
    await startPlanWorkflow(page, 'FedEx Carrier Integration');
    await page.screenshot({ path: 'test-results/context-01-plan-started.png' });
    console.log('  ✓ Plan workflow started');

    // ═══════════════════════════════════════════════════
    // STEP 2: CONTEXT FORM — VALIDATE FORM ELEMENTS
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 2: CONTEXT FORM VALIDATION ══');
    await page.screenshot({ path: 'test-results/context-02-form-empty.png' });

    // Validate required field indicators
    const specNameField = page.getByPlaceholder('e.g. New Shipping Integration');
    await expect(specNameField).toBeVisible({ timeout: 30_000 });
    console.log('  ✓ Spec name field visible');

    const descriptionField = page.getByPlaceholder('Brief summary of the feature');
    await expect(descriptionField).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Description field visible');

    const explanationField = page.getByPlaceholder('Describe the feature, its goals, and motivation');
    await expect(explanationField).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Explanation field visible');

    const constraintsField = page.getByPlaceholder('Technical and business constraints');
    await expect(constraintsField).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Constraints field visible');

    // ═══════════════════════════════════════════════════
    // STEP 3: CONTEXT FORM — FILL ALL FIELDS
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 3: CONTEXT FORM POPULATION ══');

    // Fill all fields: text fields, textareas, URLs (file uploads skipped for test)
    await fillContextForm(page, FEDEX_PLAN_CONTEXT, {
      referenceUrls: FEDEX_REFERENCE_URLS,
      primaryDoc: FEDEX_DOCS.primary,
      supportingDocs: FEDEX_DOCS.supporting,
    });

    await page.screenshot({ path: 'test-results/context-03-form-filled.png' });

    // Validate form values were filled
    await expect(specNameField).toHaveValue(FEDEX_PLAN_CONTEXT.spec_name);
    console.log('  ✓ Spec name field filled correctly');

    await expect(descriptionField).toHaveValue(FEDEX_PLAN_CONTEXT.spec_description);
    console.log('  ✓ Description field filled correctly');

    // ═══════════════════════════════════════════════════
    // STEP 4: CONTEXT FORM — SUBMIT
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 4: CONTEXT FORM SUBMISSION ══');

    const continueBtn = page.getByRole('button', { name: 'Continue' }).first();
    await expect(continueBtn).toBeEnabled({ timeout: 5_000 });
    await continueBtn.click();
    console.log('  ✓ Context form submitted');
    await page.waitForTimeout(PAUSE);

    // ═══════════════════════════════════════════════════
    // STEP 5: VALIDATE TRANSITION TO ANALYSIS REVIEW
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 5: ANALYSIS REVIEW PHASE ══');

    // Wait for analysis review heading to appear
    await expect(
      page.getByRole('heading', { name: 'Context Analysis Review' }),
    ).toBeVisible({ timeout: 180_000 });

    await page.screenshot({ path: 'test-results/context-04-analysis-review-visible.png' });
    console.log('  ✓ Successfully transitioned to analysis review');

    // Validate session persistence
    const sessionData = await page.evaluate(() => {
      try {
        const raw = localStorage.getItem('graphkb-plan-session');
        if (!raw) return null;
        return JSON.parse(raw);
      } catch {
        return null;
      }
    });

    expect(sessionData).not.toBeNull();
    const sessionId = sessionData!.state?.sessionId || sessionData!.sessionId;
    expect(sessionId).toBeTruthy();
    console.log(`  ✓ Session persisted: ${sessionId}`);

    // Validate no errors visible
    const errorMessages = page.locator('[class*="error"], [class*="destructive"]').filter({
      hasText: /error|failed|exception/i,
    });
    const errorCount = await errorMessages.count();
    expect(errorCount).toBe(0);
    console.log('  ✓ No errors visible');

    console.log('  ═══ CONTEXT PHASE COMPLETE ═══');
  });
});

// Collect console messages during test execution for failure diagnostics
const consoleLogs: string[] = [];
test.beforeEach(async ({ page }) => {
  consoleLogs.length = 0;
  page.on('console', msg => consoleLogs.push(`[${msg.type()}] ${msg.text()}`));
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    const ss = await page.screenshot({ fullPage: true });
    testInfo.attach('screenshot', { body: ss, contentType: 'image/png' });

    if (consoleLogs.length > 0) {
      testInfo.attach('console', { body: consoleLogs.join('\n'), contentType: 'text/plain' });
    }

    console.log(`\n=== TEST FAILED: ${testInfo.title} ===`);
  }
});
