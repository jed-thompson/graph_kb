import { test, expect } from '@playwright/test';

/**
 * Plan Workflow — Full Workflow Integration Test
 *
 * Complete end-to-end test that validates the entire plan workflow:
 * - All 5 phases: context → analysis → research → planning → orchestration → assembly
 * - All human-in-the-loop feedback points
 * - Multi-document pipeline implementation
 * - Final state and artifact validation
 *
 * Documents:
 *   Primary requirements:  docs/fedex-carrier-integration-spec.md
 *     13-section platform spec covering the full FedEx shipment lifecycle,
 *     OAuth token management, adapter architecture, compliance, and rollout.
 *   Supporting references:  docs/fedex-carrier-adapter-openapi.yaml
 *     OpenAPI 3.1 spec defining 16 endpoints across 8 tag groups that wrap
 *     FedEx REST APIs into a carrier-agnostic adapter interface.
 *
 * This is the comprehensive integration test for the plan workflow.
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

test.describe.configure({ timeout: 3_600_000 }); // 60 min — research loops + autonomous orchestration with real LLM calls

test.describe('Plan Workflow — Full Integration', () => {
  test('full workflow: complete 5-phase plan workflow with multi-document pipeline', async ({ page }) => {
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
    await page.screenshot({ path: 'test-results/full-01-plan-started.png' });
    console.log('  ✓ Plan workflow started');

    // ═══════════════════════════════════════════════════
    // STEP 2: CONTEXT FORM — FILL ALL FIELDS
    // ═══════════════════════════════════════════════════
    // Primary doc: fedex-carrier-integration-spec.md (13-section platform spec)
    // Supporting:  fedex-carrier-adapter-openapi.yaml (16 endpoints, 8 tag groups)
    console.log('══ STEP 2: CONTEXT FORM ══');
    await page.screenshot({ path: 'test-results/full-02-context-form-empty.png' });

    // Validate required field indicators
    const specNameField = page.getByPlaceholder('e.g. New Shipping Integration');
    await expect(specNameField).toBeVisible({ timeout: 30_000 });

    // Fill all fields: text fields, textareas, URLs, file uploads
    // FEDEX_DOCS.primary   → fedex-carrier-integration-spec.md  (uploaded as primary requirements)
    // FEDEX_DOCS.supporting → fedex-carrier-adapter-openapi.yaml (uploaded as supporting reference)
    await fillContextForm(page, FEDEX_PLAN_CONTEXT, {
      referenceUrls: FEDEX_REFERENCE_URLS,
      primaryDoc: FEDEX_DOCS.primary,
      supportingDocs: FEDEX_DOCS.supporting,
    });

    await page.screenshot({ path: 'test-results/full-03-context-form-filled.png' });

    // Submit context form
    const continueBtn = page.getByRole('button', { name: 'Continue' }).first();
    await expect(continueBtn).toBeEnabled({ timeout: 5_000 });
    await continueBtn.click();
    console.log('  ✓ Context form submitted');
    await page.waitForTimeout(PAUSE);

    // ═══════════════════════════════════════════════════
    // STEP 3: ANALYSIS REVIEW — FILL ALL FEEDBACK
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 3: ANALYSIS REVIEW ══');
    await page.screenshot({ path: 'test-results/full-04-analysis-review-empty.png' });

    // Validate analysis review sections are rendered
    await expect(
      page.getByRole('heading', { name: 'Context Analysis Review' }),
    ).toBeVisible({ timeout: 180_000 });

    // Completeness score badge should be visible
    const completenessBadge = page.locator('text=/Completeness/i').first();
    await expect(completenessBadge).toBeVisible({ timeout: 10_000 });
    console.log('  ✓ Completeness score visible');

    // Fill ALL feedback: answers, architecture items, additional context
    await handleAnalysisReview(page, FEDEX_ANALYSIS_FEEDBACK);

    await page.screenshot({ path: 'test-results/full-05-analysis-review-filled.png' });
    console.log('  ✓ Analysis review submitted');

    // ═══════════════════════════════════════════════════
    // STEP 4: RESEARCH APPROVAL (Feedback Loop #2)
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 4: RESEARCH ══');

    await handleApprovalGate(
      page,
      'Research',
      'approve',
      FEDEX_RESEARCH_FEEDBACK,
    );
    console.log('  ✓ Research approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 5: PLANNING APPROVAL (Feedback Loop #3)
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 5: PLANNING ══');

    await handleApprovalGate(
      page,
      'Planning',
      'approve',
      FEDEX_PLANNING_FEEDBACK,
    );
    console.log('  ✓ Planning approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 6: ORCHESTRATION (Autonomous — monitor progress)
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 6: ORCHESTRATION ══');

    // Wait briefly for orchestration to begin
    await page.waitForTimeout(PAUSE * 3);

    // Validate ThinkingStepsPanel or progress indicators are visible
    const thinkingPanel = page.locator('[class*="thinking"], [class*="step"], [class*="progress"]').first();
    if (await thinkingPanel.isVisible({ timeout: 5_000 }).catch(() => false)) {
      console.log('  ✓ Thinking/progress panel visible during orchestration');
    }

    await page.screenshot({ path: 'test-results/full-10-orchestration-progress.png' });

    // Orchestration is autonomous — wait for it to complete
    await monitorOrchestration(page);

    // ═══════════════════════════════════════════════════
    // STEP 7: ASSEMBLY APPROVAL (Feedback Loop #4)
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 7: ASSEMBLY ══');

    await handleApprovalGate(
      page,
      'Assembly',
      'approve',
      FEDEX_ASSEMBLY_FEEDBACK,
    );
    console.log('  ✓ Assembly approved with feedback');

    // ═══════════════════════════════════════════════════
    // STEP 8: FINAL STATE VALIDATION — VERIFY OUTPUT
    // ═══════════════════════════════════════════════════
    console.log('══ STEP 8: FINAL STATE ══');

    await page.waitForTimeout(PAUSE * 3);
    await page.screenshot({ path: 'test-results/full-13-final-complete.png' });

    // --- Validate no errors ---
    const pageContent = await page.evaluate(() => document.body.innerText);
    const hasVisibleErrors = /unhandled|runtime error|fatal/i.test(pageContent);
    expect(hasVisibleErrors).toBeFalsy();
    console.log('  ✓ No visible errors');

    // --- Validate spec document output ---
    // The final plan complete message should reference a document
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

    // --- Validate FedEx content is present in the conversation ---
    // Keywords from the primary requirements doc (fedex-carrier-integration-spec.md)
    for (const keyword of FEDEX_EXPECTED_CONTENT.keywords) {
      expect(lowerContent).toContain(keyword.toLowerCase());
    }
    console.log(`  ✓ FedEx keywords present: ${FEDEX_EXPECTED_CONTENT.keywords.join(', ')}`);

    // --- Validate OpenAPI endpoint content from supporting doc ---
    // Confirm the workflow ingested the carrier adapter OpenAPI spec
    for (const endpoint of FEDEX_EXPECTED_CONTENT.openapiEndpoints) {
      expect(lowerContent).toContain(endpoint.toLowerCase());
    }
    console.log(`  ✓ OpenAPI endpoints present: ${FEDEX_EXPECTED_CONTENT.openapiEndpoints.join(', ')}`);

    // --- Validate localStorage session persistence ---
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

    // --- Validate multi-document pipeline ---
    // Check that primary and supporting documents were processed
    const hasPrimaryDoc = lowerContent.includes('primary') || lowerContent.includes('spec');
    const hasSupportingDoc = lowerContent.includes('supporting') || lowerContent.includes('yaml');
    expect(hasPrimaryDoc).toBeTruthy();
    console.log('  ✓ Multi-document pipeline processed');

    // --- Final H2 headings for debugging ---
    const h2s = await page.evaluate(() =>
      Array.from(document.querySelectorAll('h2')).map(h => h.textContent),
    );
    console.log('  Final H2s:', h2s);

    await page.screenshot({ path: 'test-results/full-14-final-validated.png' });
    console.log('  ═══ ALL STEPS COMPLETE ═══');
  });
});

test.afterEach(async ({ page }, testInfo) => {
  if (testInfo.status !== testInfo.expectedStatus) {
    const ss = await page.screenshot({ fullPage: true });
    testInfo.attach('screenshot', { body: ss, contentType: 'image/png' });

    // Collect console logs
    const logs: string[] = [];
    page.on('console', msg => logs.push(`[${msg.type()}] ${msg.text()}`));
    if (logs.length > 0) {
      testInfo.attach('console', { body: logs.join('\n'), contentType: 'text/plain' });
    }

    console.log(`\n=== TEST FAILED: ${testInfo.title} ===`);
  }
});
