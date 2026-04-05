import { test, expect } from '@playwright/test';

/**
 * Plan Workflow — Research Phase Validation Test
 *
 * Tests the research phase of the plan workflow, validating:
 * - Context phase completion (forms filled and submitted)
 * - Analysis review feedback submission
 * - Research approval gate handling
 * - Transition to planning phase
 *
 * This test runs through context and analysis review to reach research phase.
 */

import {
  FEDEX_PLAN_CONTEXT,
  FEDEX_REFERENCE_URLS,
  FEDEX_ANALYSIS_FEEDBACK,
  FEDEX_RESEARCH_FEEDBACK,
  FEDEX_DOCS,
} from './fixtures/plan-fedex-data';
import {
  PAUSE,
  navigateToChat,
  startPlanWorkflow,
  fillContextForm,
  handleAnalysisReview,
  handleApprovalGate,
} from './helpers/plan';

test.describe.configure({ timeout: 600_000 });

test.describe('Plan Workflow — Research Phase', () => {
  test('research phase: context → analysis → research approval', async ({ page }) => {
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
    console.log('  ✓ Plan workflow started');

    // ═══════════════════════════════════════════════════
    // STEP 2: CONTEXT FORM — FILL ALL FIELDS
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 2: CONTEXT FORM ══');

    await fillContextForm(page, FEDEX_PLAN_CONTEXT, {
      referenceUrls: FEDEX_REFERENCE_URLS,
      primaryDoc: FEDEX_DOCS.primary,
      supportingDocs: FEDEX_DOCS.supporting,
    });

    const continueBtn = page.getByRole('button', { name: 'Continue' }).first();
    await expect(continueBtn).toBeEnabled({ timeout: 5_000 });
    await continueBtn.click();
    console.log('  ✓ Context form submitted');
    await page.waitForTimeout(PAUSE);

    // ═══════════════════════════════════════════════════
    // STEP 3: ANALYSIS REVIEW — FILL ALL FEEDBACK
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 3: ANALYSIS REVIEW ══');

    await expect(
      page.getByRole('heading', { name: 'Context Analysis Review' }),
    ).toBeVisible({ timeout: 180_000 });

    // Completeness score badge should be visible
    const completenessBadge = page.locator('text=/Completeness/i').first();
    await expect(completenessBadge).toBeVisible({ timeout: 10_000 });
    console.log('  ✓ Completeness score visible');

    await handleAnalysisReview(page, FEDEX_ANALYSIS_FEEDBACK);
    console.log('  ✓ Analysis review submitted');

    // ═══════════════════════════════════════════════════
    // STEP 4: RESEARCH APPROVAL — VALIDATE GATE
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 4: RESEARCH APPROVAL GATE ══');

    // Wait for the research approval gate to appear (renders as buttons, not select)
    await page.waitForSelector(
      'button:has-text("Approve")',
      { timeout: 300_000 },
    );
    console.log('  ✓ Research approval gate appeared');

    // Verify the heading matches research phase
    await expect(
      page.locator('h2').filter({ hasText: 'Research' }),
    ).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Research heading visible');

    await page.screenshot({ path: 'test-results/research-01-gate-empty.png' });

    // ═══════════════════════════════════════════════════
    // STEP 5: RESEARCH APPROVAL — SUBMIT APPROVAL
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 5: RESEARCH APPROVAL SUBMISSION ══');

    await handleApprovalGate(
      page,
      'Research',
      'approve',
      FEDEX_RESEARCH_FEEDBACK,
    );
    console.log('  ✓ Research approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 6: VALIDATE TRANSITION TO PLANNING
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 6: PLANNING PHASE ══');

    // Wait for planning heading to appear
    await expect(
      page.locator('h2').filter({ hasText: 'Planning' }),
    ).toBeVisible({ timeout: 300_000 });

    await page.screenshot({ path: 'test-results/research-02-planning-visible.png' });
    console.log('  ✓ Successfully transitioned to planning');

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

    console.log('  ═══ RESEARCH PHASE COMPLETE ═══');
  });
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    const ss = await page.screenshot({ fullPage: true });
    testInfo.attach('screenshot', { body: ss, contentType: 'image/png' });

    const logs: string[] = [];
    page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
    if (logs.length > 0) {
      testInfo.attach('console', { body: logs.join('\n'), contentType: 'text/plain' });
    }

    console.log(`\n=== TEST FAILED: ${testInfo.title} ===`);
  }
});
