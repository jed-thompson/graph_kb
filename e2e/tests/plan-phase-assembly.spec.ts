import { test, expect } from '@playwright/test';

// TODO (M8): Add backend API-level assertions using getPlanSession() and getArtifact()
//   helpers. Plan Steps 30 requires:
//   - GET /sessions/{id} → documentManifest.totalDocuments matches task count
//   - GET /sessions/{id}/artifacts/output/index.md → composed index with TOC

/**
 * Plan Workflow — Assembly Phase Validation Test
 *
 * Tests the assembly phase of the plan workflow, validating:
 * - All prior phases completion (context, analysis, research, planning, orchestration)
 * - Assembly approval gate handling
 * - Document generation and review
 * - Final state validation
 *
 * This test runs through all prior phases to reach assembly phase.
 * Note: This test takes the longest as it must complete all previous phases.
 */

import {
  FEDEX_PLAN_CONTEXT,
  FEDEX_REFERENCE_URLS,
  FEDEX_ANALYSIS_FEEDBACK,
  FEDEX_RESEARCH_FEEDBACK,
  FEDEX_PLANNING_FEEDBACK,
  FEDEX_ASSEMBLY_FEEDBACK,
  FEDEX_DOCS,
  FEDEX_EXPECTED_CONTENT,
} from './fixtures/plan-fedex-data';
import {
  PAUSE,
  navigateToChat,
  startPlanWorkflow,
  fillContextForm,
  handleAnalysisReview,
  handleApprovalGate,
  monitorOrchestration,
  validateFinalState,
} from './helpers/plan';

test.describe.configure({ timeout: 600_000 });

test.describe('Plan Workflow — Assembly Phase', () => {
  test('assembly phase: full workflow through assembly approval', async ({ page }) => {
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

    await page.waitForTimeout(PAUSE * 3);

    const thinkingPanel = page.locator('[class*="thinking"], [class*="step"], [class*="progress"]').first();
    if (await thinkingPanel.isVisible({ timeout: 5_000 }).catch(() => false)) {
      console.log('  ✓ Thinking/progress panel visible during orchestration');
    }

    await monitorOrchestration(page);
    console.log('  ✓ Orchestration monitoring complete');

    // ═══════════════════════════════════════════════════
    // STEP 7: ASSEMBLY APPROVAL — VALIDATE GATE
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 7: ASSEMBLY APPROVAL GATE ══');

    // Wait for assembly approval gate to appear (renders as buttons, not select)
    await page.waitForSelector(
      'button:has-text("Approve")',
      { timeout: 300_000 },
    );
    console.log('  ✓ Assembly approval gate appeared');

    await expect(
      page.locator('h2').filter({ hasText: 'Assembly' }),
    ).toBeVisible({ timeout: 5_000 });
    console.log('  ✓ Assembly heading visible');

    // Validate document sections are present
    const docSections = page.locator('text=/document|spec|output|content/i').first();
    if (await docSections.isVisible({ timeout: 5_000 }).catch(() => false)) {
      console.log('  ✓ Document content visible');
    }

    await page.screenshot({ path: 'test-results/assembly-01-gate-empty.png' });

    // ═══════════════════════════════════════════════════
    // STEP 8: ASSEMBLY APPROVAL — SUBMIT APPROVAL
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 8: ASSEMBLY APPROVAL SUBMISSION ══');

    await handleApprovalGate(
      page,
      'Assembly',
      'approve',
      FEDEX_ASSEMBLY_FEEDBACK,
    );
    console.log('  ✓ Assembly approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 9: FINAL STATE VALIDATION
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 9: FINAL STATE VALIDATION ══');

    await page.waitForTimeout(PAUSE * 3);
    await page.screenshot({ path: 'test-results/assembly-02-final-complete.png' });

    // Validate no errors
    const pageContent = await page.evaluate(() => document.body.innerText);
    const hasVisibleErrors = /unhandled|runtime error|fatal/i.test(pageContent);
    expect(hasVisibleErrors).toBeFalsy();
    console.log('  ✓ No visible errors');

    // Validate document output
    const docReferences = [
      'spec',
      'document',
      'download',
      'complete',
      'plan',
    ];
    const lowerContent = pageContent.toLowerCase();
    const docRefFound = docReferences.some(ref => lowerContent.includes(ref));
    expect(docRefFound).toBeTruthy();
    console.log('  ✓ Document reference found in final output');

    // Validate FedEx content is present
    for (const keyword of FEDEX_EXPECTED_CONTENT.keywords) {
      expect(lowerContent).toContain(keyword.toLowerCase());
    }
    console.log(`  ✓ FedEx keywords present: ${FEDEX_EXPECTED_CONTENT.keywords.join(', ')}`);

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

    // Check for spec document URL in stored session
    const specDocUrl =
      sessionData!.state?.specDocumentUrl ||
      sessionData!.specDocumentUrl;
    if (specDocUrl) {
      console.log(`  ✓ Spec document URL: ${specDocUrl}`);
    }

    console.log('  ═══ ASSEMBLY PHASE COMPLETE ═══');
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
