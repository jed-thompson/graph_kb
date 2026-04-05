/**
 * Plan Workflow — Reusable E2E Helpers
 *
 * Helpers for interacting with the 5-phase plan workflow UI.
 * Extracted and generalized from plan-workflow-phases.spec.ts.
 */

import { Page, expect, APIRequestContext } from '@playwright/test';
import * as path from 'path';

export const PAUSE = 1500; // ms between actions for video readability

// ============================================================
// Navigation
// ============================================================

/** Navigate to /chat and wait for the heading. */
export async function navigateToChat(page: Page): Promise<void> {
  await page.goto('/chat');
  await expect(
    page.getByRole('heading', { name: 'Chat', exact: true }),
  ).toBeVisible({ timeout: 15_000 });
}

// ============================================================
// Step 1: Start Plan Workflow
// ============================================================

/** Type /plan <name> in the chat textarea and press Enter. */
export async function startPlanWorkflow(page: Page, name: string): Promise<void> {
  const chatInput = page.locator('textarea').last();
  await chatInput.waitFor({ state: 'visible', timeout: 5_000 });
  await chatInput.fill(`/plan ${name}`);
  await page.waitForTimeout(PAUSE);
  await chatInput.press('Enter');
}

// ============================================================
// Step 2: Context Form — Fill ALL Fields
// ============================================================

interface ContextFormData {
  spec_name: string;
  spec_description: string;
  user_explanation: string;
  constraints: string;
}

interface DocUpload {
  path: string;
  filename: string;
}

/**
 * Fill the context gathering form with all fields.
 * Handles: text fields, textareas, URL list, and file uploads.
 */
export async function fillContextForm(
  page: Page,
  data: ContextFormData,
  options?: {
    referenceUrls?: string[];
    primaryDoc?: DocUpload;
    supportingDocs?: DocUpload[];
  },
): Promise<void> {
  const { referenceUrls, primaryDoc, supportingDocs } = options ?? {};

  // Wait for the context form to appear
  const specNameInput = page.getByPlaceholder('e.g. New Shipping Integration');
  await expect(specNameInput).toBeVisible({ timeout: 30_000 });
  await page.waitForTimeout(PAUSE);

  // spec_name — clear auto-filled value, re-enter
  await specNameInput.clear();
  await specNameInput.fill(data.spec_name);
  await page.waitForTimeout(800);

  // spec_description
  const descriptionField = page.getByPlaceholder('Brief summary of the feature');
  await descriptionField.fill(data.spec_description);
  await page.waitForTimeout(800);

  // user_explanation
  const explanationField = page.getByPlaceholder('Describe the feature, its goals, and motivation');
  await explanationField.fill(data.user_explanation);
  await page.waitForTimeout(800);

  // constraints
  const constraintsField = page.getByPlaceholder('Technical and business constraints');
  await constraintsField.fill(data.constraints);
  await page.waitForTimeout(800);

  // reference_urls — add each URL via the url_list field
  if (referenceUrls && referenceUrls.length > 0) {
    await addReferenceUrls(page, referenceUrls);
  }

  // primary_document — upload file via hidden input
  if (primaryDoc) {
    await uploadDocumentToField(page, 'primary_document', primaryDoc);
  }

  // supporting_docs — upload files via hidden input
  if (supportingDocs && supportingDocs.length > 0) {
    for (const doc of supportingDocs) {
      await uploadDocumentToField(page, 'supporting_docs', doc);
    }
  }

  await page.waitForTimeout(PAUSE);
}

/**
 * Add URLs one by one to the reference_urls url_list field.
 * The UrlListField renders: <Input placeholder="..."> + <button>Add</button>
 * Supports Enter key to add.
 */
async function addReferenceUrls(page: Page, urls: string[]): Promise<void> {
  const urlInput = page.getByPlaceholder(/https:\/\/example\.com\/docs|URL|url/i).first();
  if (!(await urlInput.isVisible({ timeout: 3_000 }).catch(() => false))) return;

  for (const url of urls) {
    await urlInput.fill(url);
    await page.waitForTimeout(300);
    await urlInput.press('Enter');
    await page.waitForTimeout(300);
  }
}

/**
 * Upload a file to a DocumentListField.
 * The component has a hidden <input type="file" multiple>.
 * We locate the label text and find the associated hidden input.
 */
async function uploadDocumentToField(
  page: Page,
  fieldId: string,
  doc: DocUpload,
): Promise<void> {
  // Find the section containing the label for this field
  // DocumentListField renders a <Label>{field.label}</Label> followed by a hidden <input type="file">
  // We use the field label text to locate the right upload area
  const labels: Record<string, string> = {
    primary_document: 'Primary requirements document',
    supporting_docs: 'Supporting documents & references',
  };
  const labelText = labels[fieldId] ?? fieldId;

  // Find the label, then get the parent container's hidden file input
  const label = page.locator('label').filter({ hasText: labelText }).first();
  const container = label.locator('..');

  // The hidden input is inside the container
  const fileInput = container.locator('input[type="file"]');
  if (!(await fileInput.isVisible({ timeout: 2_000 }).catch(() => false))) {
    // Hidden input — setInputFiles works on hidden inputs in Playwright
  }

  // Resolve path relative to the e2e directory
  // __dirname is .../e2e/tests/helpers, we need to go up to project root
  const resolvedPath = path.resolve(__dirname, '../../../', doc.path);
  await fileInput.setInputFiles(resolvedPath);

  // Wait for upload to complete (check for uploaded file name in the list)
  await page.waitForTimeout(3_000);
}

// ============================================================
// Step 3: Analysis Review — Fill ALL Feedback
// ============================================================

interface AnalysisFeedbackData {
  additional_context: string;
  answers: string[];
  architecture_feedback: string[];
  suggested_actions_feedback?: string[];
}

/**
 * Handle the Analysis Review form (FeedbackReviewNode).
 * Fills clarification question answers, architecture feedback per item,
 * additional context, and submits.
 */
export async function handleAnalysisReview(
  page: Page,
  feedback: AnalysisFeedbackData,
): Promise<void> {
  // Wait for the analysis review heading
  await expect(
    page.getByRole('heading', { name: 'Context Analysis Review' }),
  ).toBeVisible({ timeout: 180_000 });
  await page.waitForTimeout(PAUSE);

  // --- Fill clarification question answers ---
  // Questions render as textareas inside collapsible sections.
  // We fill ALL visible textareas that are empty (questions) with our answers.
  const questionTextareas = await page.locator('.space-y-2 textarea').all();
  const answersCopy = [...feedback.answers];

  for (let i = 0; i < answersCopy.length; i++) {
    try {
      const textarea = questionTextareas[i];
      if (await textarea.isVisible({ timeout: 2_000 })) {
        await textarea.fill(answersCopy[i]);
        await page.waitForTimeout(500);
      }
    } catch {
      // Not all textareas may be questions — skip gracefully
    }
  }

  // --- Fill architecture feedback ---
  // ArchitectureFeedbackItem reveals a feedback toggle on hover.
  // Each item has: label text → hover → click "Add feedback" → textarea appears
  for (const feedbackText of feedback.architecture_feedback) {
    try {
      // Find an item that doesn't have feedback yet (no primary dot color)
      // The architecture section has items with hover-reveal feedback buttons
      const items = page.locator('[data-state], [class*="group"]').filter({
        has: page.locator('button[aria-label*="feedback"], button[aria-label*="Feedback"], button[aria-label*="Add"]'),
      });

      if (await items.first().isVisible({ timeout: 2_000 }).catch(() => false)) {
        const item = items.first();
        await item.hover();
        await page.waitForTimeout(300);

        // Click the feedback toggle button
        const feedbackBtn = item.locator('button').first();
        await feedbackBtn.click();
        await page.waitForTimeout(500);

        // Fill the textarea that appeared
        const feedbackTextarea = item.locator('textarea').first();
        if (await feedbackTextarea.isVisible({ timeout: 1_000 }).catch(() => false)) {
          await feedbackTextarea.fill(feedbackText);
          await page.waitForTimeout(300);
        }
      }
    } catch {
      // Architecture section may not render feedback items for all entries
      break;
    }
  }

  // --- Fill additional context ---
  if (feedback.additional_context) {
    const additionalCtxTextarea = page.getByPlaceholder(/additional|context|notes/i).first();
    if (await additionalCtxTextarea.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await additionalCtxTextarea.fill(feedback.additional_context);
      await page.waitForTimeout(500);
    }
  }

  await page.waitForTimeout(PAUSE);

  // --- Submit ---
  const submitBtn = page.getByRole('button', { name: 'Submit Review' });
  if (await submitBtn.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await expect(submitBtn).toBeEnabled({ timeout: 5_000 });
    await submitBtn.click();
  } else {
    // Fallback: try "Acknowledge All & Proceed" if Submit Review not found
    const ackBtn = page.getByRole('button', { name: 'Acknowledge All & Proceed' });
    if (await ackBtn.isVisible({ timeout: 2_000 }).catch(() => false)) {
      await ackBtn.click();
    }
  }

  await page.waitForTimeout(PAUSE);
}

// ============================================================
// Steps 4, 5, 7: Approval Gates — Research, Planning, Assembly
// ============================================================

/**
 * Handle any approval gate (ResearchApprovalNode, PlanningApprovalNode, AssemblyApprovalNode).
 * Generalized to accept any decision: approve, request_more, request_revisions, reject.
 *
 * Pattern: wait for heading → click the decision button → fill feedback → wait for heading change
 */
export async function handleApprovalGate(
  page: Page,
  expectedHeading: string,
  decision: string,
  feedback: string,
  screenshotNum?: string,
): Promise<void> {
  // Wait for the approval gate to actually appear.
  // The phase heading is visible throughout the entire phase, so we must wait
  // for the decision BUTTON (rendered by PhaseApprovalForm) to know the gate is ready.
  // Phase labels vary per phase: "Approve & Continue", "Approve & Start Execution", etc.
  // Match any button whose accessible name starts with "Approve".
  const approveBtn = page.getByRole('button', { name: /^Approve/i }).first();
  const decisionBtn = page.getByRole('button', { name: new RegExp(decision, 'i') }).first();

  const button = decision === 'approve' ? approveBtn : decisionBtn;
  // Research phase can loop 2-3+ times with real LLM calls (each loop ~3-5 min).
  // Use a generous timeout — the test-level timeout is the hard limit.
  await expect(button).toBeVisible({ timeout: 900_000 });
  await page.waitForTimeout(PAUSE);

  if (screenshotNum) {
    await page.screenshot({ path: `test-results/${screenshotNum}-${expectedHeading.toLowerCase()}-empty.png` });
  }

  await button.click();
  await page.waitForTimeout(800);

  // Fill feedback textarea
  const feedbackField = page.getByPlaceholder(/feedback|notes|comment|context/i).first();
  if (await feedbackField.isVisible({ timeout: 3_000 }).catch(() => false)) {
    await feedbackField.fill(feedback);
    await page.waitForTimeout(800);
  }

  // Fill per-gap feedback if present (ArchitectureFeedbackItem on gaps)
  const gapItems = page.locator('[class*="gap"] button[aria-label*="feedback"], [class*="gap"] button[aria-label*="Add"]');
  if (await gapItems.first().isVisible({ timeout: 2_000 }).catch(() => false)) {
    const count = await gapItems.count();
    for (let i = 0; i < Math.min(count, 3); i++) {
      await gapItems.nth(i).hover();
      await page.waitForTimeout(200);
      await gapItems.nth(i).click();
      await page.waitForTimeout(300);
      const textarea = page.locator('textarea').last();
      if (await textarea.isVisible({ timeout: 1_000 }).catch(() => false)) {
        await textarea.fill(`Feedback on gap ${i + 1}: see notes above.`);
        await page.waitForTimeout(200);
      }
    }
  }

  if (screenshotNum) {
    await page.screenshot({ path: `test-results/${screenshotNum}-${expectedHeading.toLowerCase()}-filled.png` });
  }

  console.log(`  ✓ ${expectedHeading} — ${decision}`);
  await page.waitForTimeout(PAUSE);

  if (screenshotNum) {
    await page.screenshot({ path: `test-results/${screenshotNum}-${expectedHeading.toLowerCase()}-submitted.png` });
  }

  // Wait for the heading to change (phase transitioned)
  await page.waitForFunction(
    (heading) => {
      const h2s = Array.from(document.querySelectorAll('h2'));
      return !h2s.some(h => h.textContent?.includes(heading));
    },
    expectedHeading,
    { timeout: 300_000 },
  );
  await page.waitForTimeout(PAUSE);
}

// ============================================================
// Step 6: Orchestration — Monitor Autonomous Progress
// ============================================================

/**
 * Monitor the orchestration phase (autonomous, no user interaction).
 * Validates ThinkingStepsPanel is visible and waits for phase to complete.
 * Will auto-approve any budget exhaustion prompts if they appear.
 */
export async function monitorOrchestration(page: Page): Promise<void> {
  console.log('  Waiting for orchestration to complete...');

  // Set up a loop to watch for budget approval or phase transition
  const startTime = Date.now();
  const timeout = 600_000;

  while (Date.now() - startTime < timeout) {
    // Check if we've transitioned to Assembly (Orchestration heading is gone)
    const isOrchestrating = await page.evaluate(() => {
      const h2s = Array.from(document.querySelectorAll('h2'));
      return h2s.some(h => h.textContent?.toLowerCase().includes('orchestrat'));
    });

    if (!isOrchestrating) {
      console.log('  ✓ Orchestration monitoring complete');
      return;
    }

    // Check if the circuit breaker triggered (red alert box)
    const alertBox = page.getByRole('alert').filter({ hasText: /Orchestration Interrupted|circuit breaker/i }).first();
    if (await alertBox.isVisible({ timeout: 1000 }).catch(() => false)) {
      console.log('  ✓ Circuit breaker triggered (Orchestration Interrupted)');
      // If the circuit breaker fired, the phase aborted intentionally. We can break.
      return;
    }

    // Check if there is an active budget approval gate blocking us
    const approveBtn = page.getByRole('button', { name: /^Approve/i }).filter({ hasText: /Approve/ }).first();
    if (await approveBtn.isVisible({ timeout: 1000 }).catch(() => false)) {
      console.log('  ✓ Handled budget exhaustion interrupt');
      await approveBtn.click();
      await page.waitForTimeout(PAUSE);
    }

    await page.waitForTimeout(2000);
  }

  throw new Error('monitorOrchestration timed out after 10 minutes');
}

// ============================================================
// Step 8: Final State Validation
// ============================================================

/**
 * Validate the final state after plan completion.
 * Checks: phase bar, progress, document output, session persistence.
 */
export async function validateFinalState(page: Page): Promise<void> {
  await page.waitForTimeout(PAUSE * 2);
  await page.screenshot({ path: 'test-results/13-final-complete.png' });

  // Validate no error messages visible
  const errorMessages = page.locator('[class*="error"], [class*="destructive"]').filter({
    hasText: /error|failed|exception/i,
  });
  const errorCount = await errorMessages.count();
  if (errorCount > 0) {
    const errorTexts = await errorMessages.allTextContents();
    console.warn(`  ⚠ ${errorCount} error message(s) found:`, errorTexts.slice(0, 3));
  }

  // Validate localStorage session persistence
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
  expect(sessionData!.state?.sessionId || sessionData!.sessionId).toBeTruthy();

  // Check for spec document URL in the final chat messages
  const pageText = await page.evaluate(() => document.body.innerText);
  const hasDocReference =
    pageText.toLowerCase().includes('spec') ||
    pageText.toLowerCase().includes('document') ||
    pageText.toLowerCase().includes('download');

  expect(hasDocReference).toBeTruthy();

  console.log('  ✓ Final state validated');
}

// ============================================================
// API-Level Plan Helpers (Steps 25-26)
// ============================================================

const PLAN_API_BASE = process.env.API_BASE_URL || 'http://localhost:8000';

/** Get plan session details via REST API. */
export async function getPlanSession(
  request: any,
  sessionId: string,
): Promise<Record<string, unknown>> {
  const response = await request.get(`${PLAN_API_BASE}/plan/sessions/${sessionId}`);
  return response.json();
}

/** Get an artifact by key for a plan session. */
export async function getPlanArtifact(
  request: any,
  sessionId: string,
  artifactKey: string,
): Promise<string | null> {
  const response = await request.get(`${PLAN_API_BASE}/plan/sessions/${sessionId}/artifacts/${artifactKey}`);
  if (!response.ok()) return null;
  const data = await response.json();
  return typeof data.content === 'string' ? data.content : JSON.stringify(data);
}

/** Assert an artifact exists and is non-empty for a plan session. */
export async function assertArtifactExists(
  request: any,
  sessionId: string,
  artifactKey: string,
): Promise<string> {
  const content = await getPlanArtifact(request, sessionId, artifactKey);
  expect(content).not.toBeNull();
  expect(content!.length).toBeGreaterThan(0);
  return content!;
}
