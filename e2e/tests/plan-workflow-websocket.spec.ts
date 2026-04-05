import { test, expect, Page } from '@playwright/test';

/**
 * E2E tests for the Plan Workflow WebSocket Protocol.
 *
 * Tests the `plan.*` event protocol over raw WebSocket connections,
 * verifying: plan.start → plan.phase.prompt, plan.pause → plan.paused,
 * plan.phase.input validation, and session isolation.
 *
 * Plan phases: context, research, planning, orchestrate, assembly
 *
 * Validates: Requirements 20.1–20.6, 21.1, 21.7, 29.3
 */

const WS_URL = process.env.WS_URL || 'ws://localhost:8000/ws';

// ── Types ───────────────────────────────────────────────────────

interface WsMessage {
  type: string;
  data?: Record<string, unknown>;
  [key: string]: unknown;
}

// ── Helpers ─────────────────────────────────────────────────────

/**
 * Open a persistent WebSocket inside the browser and return helpers
 * to send messages and collect responses.
 */
async function openPersistentWs(page: Page) {
  await page.evaluate((wsUrl) => {
    return new Promise<void>((resolve, reject) => {
      const ws = new WebSocket(wsUrl);
      const msgs: Record<string, unknown>[] = [];

      ws.onopen = () => {
        (window as any).__testWs = ws;
        (window as any).__testWsMsgs = msgs;
        resolve();
      };

      ws.onmessage = (e) => {
        try { msgs.push(JSON.parse(e.data)); } catch { msgs.push({ raw: e.data }); }
      };

      ws.onerror = () => reject(new Error('WS connection failed'));
      setTimeout(() => reject(new Error('WS connection timeout')), 10_000);
    });
  }, WS_URL);

  return {
    send: async (msg: { type: string; payload: Record<string, unknown> }) => {
      await page.evaluate((m) => {
        (window as any).__testWs.send(JSON.stringify(m));
      }, msg);
    },
    collectMessages: async (waitMs = 3000): Promise<WsMessage[]> => {
      await page.waitForTimeout(waitMs);
      return page.evaluate(() => {
        const msgs = [...(window as any).__testWsMsgs];
        (window as any).__testWsMsgs.length = 0;
        return msgs;
      }) as Promise<WsMessage[]>;
    },
    close: async () => {
      await page.evaluate(() => {
        try { (window as any).__testWs.close(); } catch { /* noop */ }
      });
    },
  };
}

function findEvent(msgs: WsMessage[], type: string): WsMessage | undefined {
  return msgs.find((m) => m.type === type);
}

function findAllEvents(msgs: WsMessage[], type: string): WsMessage[] {
  return msgs.filter((m) => m.type === type);
}

// ── Test Suite ──────────────────────────────────────────────────

test.describe('Plan Workflow — WebSocket Protocol E2E', () => {

  test.beforeEach(async ({ page }) => {
    await page.goto('about:blank');
  });

  // ── 1. plan.start → plan.phase.prompt for context phase ───────

  test('plan.start returns plan.phase.prompt for context phase', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      await ws.send({
        type: 'plan.start',
        payload: { name: 'E2E Plan Test', description: 'Automated E2E validation' },
      });

      const msgs = await ws.collectMessages(15_000);

      // Should receive at least one message
      expect(msgs.length).toBeGreaterThan(0);

      // Should get a plan.phase.prompt (not spec.phase.prompt)
      const prompt = findEvent(msgs, 'plan.phase.prompt');
      expect(prompt).toBeDefined();

      const data = prompt!.data as Record<string, unknown>;
      expect(data.session_id).toBeTruthy();
      expect(data.phase).toBe('context');
      expect(Array.isArray(data.fields)).toBe(true);

      // Verify NO spec.* events were emitted
      const specEvents = msgs.filter((m) => typeof m.type === 'string' && m.type.startsWith('spec.'));
      expect(specEvents).toHaveLength(0);
    } finally {
      await ws.close();
    }
  });

  // ── 2. plan.pause → plan.paused ───────────────────────────────

  test('plan.pause returns plan.paused event', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      // Start a session first
      await ws.send({
        type: 'plan.start',
        payload: { name: 'Pause Test Plan' },
      });

      const startMsgs = await ws.collectMessages(15_000);
      const prompt = findEvent(startMsgs, 'plan.phase.prompt');
      expect(prompt).toBeDefined();

      const sessionId = (prompt!.data as Record<string, unknown>).session_id as string;
      expect(sessionId).toBeTruthy();

      // Pause the session
      await ws.send({
        type: 'plan.pause',
        payload: { session_id: sessionId },
      });

      const pauseMsgs = await ws.collectMessages(5_000);

      // Should get plan.paused (not spec.paused)
      const paused = findEvent(pauseMsgs, 'plan.paused');
      expect(paused).toBeDefined();

      const pausedData = paused!.data as Record<string, unknown>;
      expect(pausedData.status).toBe('paused');
      expect(pausedData.session_id).toBe(sessionId);

      // Verify NO spec.paused was emitted
      const specPaused = findEvent(pauseMsgs, 'spec.paused');
      expect(specPaused).toBeUndefined();
    } finally {
      await ws.close();
    }
  });

  // ── 3. plan.resume → plan.state + plan.phase.prompt ───────────

  test('plan.resume returns plan.state and plan.phase.prompt', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      // Start a session
      await ws.send({
        type: 'plan.start',
        payload: { name: 'Resume Test Plan' },
      });

      const startMsgs = await ws.collectMessages(15_000);
      const prompt = findEvent(startMsgs, 'plan.phase.prompt');
      expect(prompt).toBeDefined();

      const sessionId = (prompt!.data as Record<string, unknown>).session_id as string;

      // Resume the session
      await ws.send({
        type: 'plan.resume',
        payload: { session_id: sessionId },
      });

      const resumeMsgs = await ws.collectMessages(5_000);

      // Should get plan.state with budget and phase info
      const stateEvt = findEvent(resumeMsgs, 'plan.state');
      expect(stateEvt).toBeDefined();

      const stateData = stateEvt!.data as Record<string, unknown>;
      expect(stateData.session_id).toBe(sessionId);
      expect(stateData.current_phase).toBeTruthy();
      expect(stateData.completed_phases).toBeDefined();
      expect(stateData.budget).toBeDefined();

      const budget = stateData.budget as Record<string, unknown>;
      expect(typeof budget.remaining_llm_calls).toBe('number');
      expect(typeof budget.tokens_used).toBe('number');

      // Should also get a plan.phase.prompt for the current phase
      const resumePrompt = findEvent(resumeMsgs, 'plan.phase.prompt');
      expect(resumePrompt).toBeDefined();

      // Verify NO spec.plan.state was emitted
      const specState = findEvent(resumeMsgs, 'spec.plan.state');
      expect(specState).toBeUndefined();
    } finally {
      await ws.close();
    }
  });

  // ── 4. plan.navigate without confirm → plan.cascade.warning ───

  test('plan.navigate without confirm returns plan.cascade.warning', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      // Start a session
      await ws.send({
        type: 'plan.start',
        payload: { name: 'Navigate Test Plan' },
      });

      const startMsgs = await ws.collectMessages(15_000);
      const prompt = findEvent(startMsgs, 'plan.phase.prompt');
      expect(prompt).toBeDefined();

      const sessionId = (prompt!.data as Record<string, unknown>).session_id as string;

      // Navigate backward to context without confirming cascade
      await ws.send({
        type: 'plan.navigate',
        payload: {
          session_id: sessionId,
          target_phase: 'context',
          // confirm_cascade intentionally omitted (defaults to false)
        },
      });

      const navMsgs = await ws.collectMessages(5_000);

      // Should get plan.cascade.warning (not spec.cascade.warning)
      const warning = findEvent(navMsgs, 'plan.cascade.warning');
      expect(warning).toBeDefined();

      const warningData = warning!.data as Record<string, unknown>;
      expect(warningData.session_id).toBe(sessionId);
      expect(Array.isArray(warningData.affectedPhases)).toBe(true);

      const affected = warningData.affectedPhases as string[];
      // context's downstream: research, planning, orchestrate, assembly
      expect(affected).toContain('research');
      expect(affected).toContain('planning');
      expect(affected).toContain('orchestrate');
      expect(affected).toContain('assembly');

      // Verify the affected phases use NEW names (not old spec names)
      expect(affected).not.toContain('plan');
      expect(affected).not.toContain('completeness');
      expect(affected).not.toContain('generate');
      expect(affected).not.toContain('review');

      // Verify NO spec.cascade.warning was emitted
      const specWarning = findEvent(navMsgs, 'spec.cascade.warning');
      expect(specWarning).toBeUndefined();
    } finally {
      await ws.close();
    }
  });

  // ── 5. Invalid payload → plan.error with VALIDATION_ERROR ─────

  test('plan.start with empty name returns plan.error VALIDATION_ERROR', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      await ws.send({
        type: 'plan.start',
        payload: { name: '' },
      });

      const msgs = await ws.collectMessages(8_000);

      // Should get plan.error (not spec.error)
      const error = findEvent(msgs, 'plan.error');
      expect(error).toBeDefined();

      const errorData = error!.data as Record<string, unknown>;
      expect(errorData.code).toBe('VALIDATION_ERROR');
      expect(errorData.message).toBeTruthy();

      // Verify NO spec.error was emitted
      const specError = findEvent(msgs, 'spec.error');
      expect(specError).toBeUndefined();
    } finally {
      await ws.close();
    }
  });

  test('plan.phase.input with invalid phase returns plan.error VALIDATION_ERROR', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      await ws.send({
        type: 'plan.phase.input',
        payload: {
          session_id: 'nonexistent-session',
          phase: 'bogus_phase',
          data: {},
        },
      });

      const msgs = await ws.collectMessages(8_000);

      const error = findEvent(msgs, 'plan.error');
      expect(error).toBeDefined();

      const errorData = error!.data as Record<string, unknown>;
      expect(errorData.code).toBe('VALIDATION_ERROR');
    } finally {
      await ws.close();
    }
  });

  // ── 6. All plan.* events use plan prefix, never spec prefix ───

  test('all events from plan workflow use plan.* prefix, never spec.*', async ({ page }) => {
    const ws = await openPersistentWs(page);

    try {
      // Start a plan session and collect ALL events
      await ws.send({
        type: 'plan.start',
        payload: { name: 'Prefix Validation Plan', description: 'Verify event prefixes' },
      });

      const msgs = await ws.collectMessages(15_000);

      // Every event should start with "plan."
      const typedMsgs = msgs.filter((m) => typeof m.type === 'string');
      expect(typedMsgs.length).toBeGreaterThan(0);

      for (const msg of typedMsgs) {
        expect(msg.type).toMatch(/^plan\./);
      }

      // Explicitly verify no spec.* events leaked through
      const specEvents = typedMsgs.filter((m) => (m.type as string).startsWith('spec.'));
      expect(specEvents).toHaveLength(0);
    } finally {
      await ws.close();
    }
  });

  // ── 7. Session isolation ──────────────────────────────────────

  test('two plan sessions do not receive each other\'s events', async ({ browser }) => {
    test.setTimeout(90_000);
    const ctx1 = await browser.newContext();
    const ctx2 = await browser.newContext();
    const page1 = await ctx1.newPage();
    const page2 = await ctx2.newPage();

    await page1.goto('about:blank');
    await page2.goto('about:blank');

    try {
      const ws1 = await openPersistentWs(page1);
      const ws2 = await openPersistentWs(page2);

      // Start session 1
      await ws1.send({
        type: 'plan.start',
        payload: { name: 'Isolation Session A' },
      });
      const msgs1 = await ws1.collectMessages(15_000);
      const prompt1 = findEvent(msgs1, 'plan.phase.prompt');
      expect(prompt1).toBeDefined();
      const sid1 = (prompt1!.data as Record<string, unknown>).session_id as string;

      // Start session 2
      await ws2.send({
        type: 'plan.start',
        payload: { name: 'Isolation Session B' },
      });
      const msgs2 = await ws2.collectMessages(15_000);
      const prompt2 = findEvent(msgs2, 'plan.phase.prompt');
      expect(prompt2).toBeDefined();
      const sid2 = (prompt2!.data as Record<string, unknown>).session_id as string;

      // Sessions should have different IDs
      expect(sid1).not.toBe(sid2);

      // Session 1 messages should only reference session 1
      for (const msg of msgs1) {
        const data = msg.data as Record<string, unknown> | undefined;
        if (data?.session_id) {
          expect(data.session_id).toBe(sid1);
        }
      }

      // Session 2 messages should only reference session 2
      for (const msg of msgs2) {
        const data = msg.data as Record<string, unknown> | undefined;
        if (data?.session_id) {
          expect(data.session_id).toBe(sid2);
        }
      }

      await ws1.close();
      await ws2.close();
    } finally {
      await ctx1.close();
      await ctx2.close();
    }
  });
});
