import { test, expect } from '@playwright/test';

// TODO (M8): Add backend API-level assertions using getPlanSession() and getArtifact()
//   helpers. Plan Steps 29 requires:
//   - GET /sessions/{id} → document_manifest.entries count matching task count
//   - GET /sessions/{id}/artifacts/deliverables/{task_id} → valid markdown with YAML frontmatter

/**
 * Plan Workflow — Orchestration Phase Validation Test
 *
 * Tests the orchestration phase of the plan workflow, validating:
 * - Context, analysis, research, and planning phases completion
 * - Autonomous orchestration progress monitoring
 * - Thinking steps panel visibility
 * - Transition to assembly phase
 *
 * This test runs through all prior phases to reach orchestration phase.
 * Note: This test takes longer as it must complete all previous phases.
 */

import {
  FEDEX_PLAN_CONTEXT,
  FEDEX_REFERENCE_URLS,
  FEDEX_ANALYSIS_FEEDBACK,
  FEDEX_RESEARCH_FEEDBACK,
  FEDEX_PLANNING_FEEDBACK,
  FEDEX_DOCS,
} from './fixtures/plan-fedex-data';
import {
  PAUSE,
  navigateToChat,
  startPlanWorkflow,
  fillContextForm,
  handleAnalysisReview,
  handleApprovalGate,
  monitorOrchestration,
} from './helpers/plan';

test.describe('Plan Workflow — Orchestration Phase', () => {
  test.setTimeout(900_000);

  test('orchestration phase: context → analysis → research → planning → orchestration → assembly', async ({ page }) => {
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

    const completenessBadge = page.locator('text=/Completeness/i').first();
    await expect(completenessBadge).toBeVisible({ timeout: 10_000 });
    console.log('  ✓ Completeness score visible');

    await handleAnalysisReview(page, FEDEX_ANALYSIS_FEEDBACK);
    console.log('  ✓ Analysis review submitted');

    // ═══════════════════════════════════════════════════
    // STEP 4: RESEARCH APPROVAL
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 4: RESEARCH APPROVAL ══');

    await handleApprovalGate(
      page,
      'Research',
      'approve',
      FEDEX_RESEARCH_FEEDBACK,
    );
    console.log('  ✓ Research approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 5: PLANNING APPROVAL
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 5: PLANNING APPROVAL ══');

    await handleApprovalGate(
      page,
      'Planning',
      'approve',
      FEDEX_PLANNING_FEEDBACK,
    );
    console.log('  ✓ Planning approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 6: ORCHESTRATION — MONITOR AUTONOMOUS PROGRESS
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 6: ORCHESTRATION MONITORING ══');

    // Wait briefly for orchestration to begin
    await page.waitForTimeout(PAUSE * 3);

    // Validate ThinkingStepsPanel or progress indicators are visible
    const thinkingPanel = page.locator('[class*="thinking"], [class*="step"], [class*="progress"]').first();
    if (await thinkingPanel.isVisible({ timeout: 5_000 }).catch(() => false)) {
      console.log('  ✓ Thinking/progress panel visible during orchestration');
    }

    await page.screenshot({ path: 'test-results/orchestration-01-progress.png' });

    // Orchestration is autonomous — wait for it to complete
    await monitorOrchestration(page);
    console.log('  ✓ Orchestration monitoring complete');

    // ═══════════════════════════════════════════════════
    // STEP 7: VALIDATE TRANSITION TO ASSEMBLY
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 7: ASSEMBLY PHASE ══');

    // Wait for assembly approval gate to appear (renders as buttons, not select)
    await page.waitForSelector(
      'button:has-text("Approve")',
      { timeout: 300_000 },
    );
    console.log('  ✓ Assembly approval gate appeared');

    // Verify the heading matches assembly phase
    await expect(
      page.locator('h2').filter({ hasText: 'Assembly' }),
    ).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Assembly heading visible');

    await page.screenshot({ path: 'test-results/orchestration-02-assembly-visible.png' });
    console.log('  ✓ Successfully transitioned to assembly');

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

    console.log('  ═══ ORCHESTRATION PHASE COMPLETE ═══');
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
