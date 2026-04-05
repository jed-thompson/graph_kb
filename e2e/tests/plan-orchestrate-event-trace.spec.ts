import { test, expect } from '@playwright/test';

import {
  FEDEX_ANALYSIS_FEEDBACK,
  FEDEX_DOCS,
  FEDEX_PLAN_CONTEXT,
  FEDEX_PLANNING_FEEDBACK,
  FEDEX_REFERENCE_URLS,
  FEDEX_RESEARCH_FEEDBACK,
} from './fixtures/plan-fedex-data';
import {
  fillContextForm,
  handleAnalysisReview,
  handleApprovalGate,
  navigateToChat,
  PAUSE,
  startPlanWorkflow,
} from './helpers/plan';

test.describe('Plan Workflow - Orchestrate Event Trace', () => {
  test.setTimeout(1_200_000);

  test('captures plan task websocket events during orchestration', async ({ page }) => {
    const consoleLines: string[] = [];
    const wsFrames: string[] = [];

    page.on('console', (msg) => {
      const text = msg.text();
      if (text.includes('[WS]') || text.includes('WebSocket') || text.includes('plan.')) {
        consoleLines.push(`[console:${msg.type()}] ${text}`);
        console.log(`[console:${msg.type()}] ${text}`);
      }
    });

    page.on('websocket', (ws) => {
      console.log(`[ws] open ${ws.url()}`);
      ws.on('framereceived', (event) => {
        const payload = String(event.payload ?? '');
        if (payload.includes('plan.')) {
          wsFrames.push(payload);
          console.log(`[ws:in] ${payload.slice(0, 600)}`);
        }
      });
      ws.on('framesent', (event) => {
        const payload = String(event.payload ?? '');
        if (payload.includes('plan.')) {
          console.log(`[ws:out] ${payload.slice(0, 600)}`);
        }
      });
      ws.on('close', () => console.log(`[ws] close ${ws.url()}`));
    });

    await navigateToChat(page);
    await page.evaluate(() => {
      localStorage.removeItem('graphkb-plan-session');
      localStorage.removeItem('graphkb-plan-resume');
    });
    await page.reload();
    await expect(page.getByRole('heading', { name: 'Chat', exact: true })).toBeVisible({
      timeout: 15_000,
    });
    await page.waitForTimeout(PAUSE);

    await startPlanWorkflow(page, 'FedEx Carrier Integration');
    await fillContextForm(page, FEDEX_PLAN_CONTEXT, {
      referenceUrls: FEDEX_REFERENCE_URLS,
      primaryDoc: FEDEX_DOCS.primary,
      supportingDocs: FEDEX_DOCS.supporting,
    });

    await page.getByRole('button', { name: 'Continue' }).first().click();
    await page.waitForTimeout(PAUSE);

    await expect(
      page.getByRole('heading', { name: 'Context Analysis Review' }),
    ).toBeVisible({ timeout: 180_000 });

    await handleAnalysisReview(page, FEDEX_ANALYSIS_FEEDBACK);
    await handleApprovalGate(page, 'Research', 'approve', FEDEX_RESEARCH_FEEDBACK);
    await handleApprovalGate(page, 'Planning', 'approve', FEDEX_PLANNING_FEEDBACK);

    const tasksHeader = page.getByRole('heading', { name: /Generative Tasks/i });
    await expect(tasksHeader).toBeVisible({ timeout: 120_000 });

    const startedAt = Date.now();
    let sawDag = false;
    let sawTaskStart = false;
    let sawTaskComplete = false;
    let sawManifestUpdate = false;

    while (Date.now() - startedAt < 180_000) {
      const completionLine = await page.evaluate(() => {
        return document.body.innerText.match(/\d+ \/ \d+ Completed/)?.[0] ?? 'no-completion-line';
      });
      console.log(`[dom] ${completionLine}`);

      sawDag ||= wsFrames.some((frame) => frame.includes('plan.tasks.dag'));
      sawTaskStart ||= wsFrames.some((frame) => frame.includes('plan.task.start'));
      sawTaskComplete ||= wsFrames.some((frame) => frame.includes('plan.task.complete'));
      sawManifestUpdate ||= wsFrames.some((frame) => frame.includes('plan.manifest.update'));

      if (sawDag && sawTaskStart) {
        break;
      }

      await page.waitForTimeout(10_000);
    }

    await page.screenshot({ path: 'test-results/orchestrate-event-trace.png', fullPage: true });

    console.log(`[summary] sawDag=${sawDag} sawTaskStart=${sawTaskStart} sawTaskComplete=${sawTaskComplete} sawManifestUpdate=${sawManifestUpdate}`);
    console.log(`[summary] consoleLines=${consoleLines.length} wsFrames=${wsFrames.length}`);

    test.info().attach('console-lines', {
      body: consoleLines.join('\n'),
      contentType: 'text/plain',
    });
    test.info().attach('ws-frames', {
      body: wsFrames.join('\n\n'),
      contentType: 'text/plain',
    });

    expect(sawDag).toBeTruthy();
    expect(sawTaskStart).toBeTruthy();
  });
});
