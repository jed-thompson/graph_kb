/**
 * Plan Workflow — FedEx Carrier Integration Test Data
 *
 * Production-like input for the 5-phase plan workflow e2e test.
 * Reuses shared constants from fedex-test-data.ts where possible.
 *
 * Derived from:
 *   docs/fedex-carrier-integration-spec.md (1396 lines, 13 sections, 10 modules)
 *   docs/fedex-carrier-adapter-openapi.yaml (1352 lines, 16 endpoints, 8 tag groups)
 */

import {
  contextPhaseInput,
  getFeatureName,
} from './fedex-test-data';

const FEATURE_NAME = getFeatureName();

// ============================================================
// CONTEXT PHASE INPUT — maps to the CollectContextNode form fields
// ============================================================

export const FEDEX_PLAN_CONTEXT = {
  spec_name: FEATURE_NAME,
  spec_description: contextPhaseInput.description,
  user_explanation: contextPhaseInput.explanation,
  constraints: contextPhaseInput.constraints,
};

// ============================================================
// REFERENCE URLs — from spec Appendix C
// ============================================================

export const FEDEX_REFERENCE_URLS = [
  'https://developer.fedex.com/api/en-us/catalog/authorization/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/ship/v1/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/rate/v1/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/track/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/pickup/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/address-validation/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/service-availability/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/location/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/freight/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/returns/docs.html',
  'https://developer.fedex.com/api/en-us/catalog/dangerous-goods/docs.html',
  'https://developer.fedex.com/api/en-us/openapi.html',
  'https://www.fedex.com/en-us/service-guide/dangerous-goods/how-to-ship.html',
];

// ============================================================
// ANALYSIS REVIEW FEEDBACK — for FeedbackReviewNode
// ============================================================

export const FEDEX_ANALYSIS_FEEDBACK = {
  additional_context: [
    'Platform already has existing Checkout, Order, Returns, and Tracking microservices.',
    'Integration should follow the CarrierAdapter pattern defined in Section 8 of the spec.',
    'Existing httpx client with connection pooling and retry logic can be extended for FedEx.',
  ].join('\n'),

  answers: [
    // Generic answers that work regardless of what the AI generates
    'Redis with 55-minute TTL (5-minute safety margin before 60-min FedEx expiry). Refresh mutex prevents thundering herd. Token cache keys prefixed by merchant_id for multi-tenant isolation.',
    '5 consecutive failures open the circuit breaker for 60s. 2 half-open test calls probe recovery. Uses httpx transport adapter pattern. Retryable: 429, 500, 502, 503, 504 with 1s/2x/30s backoff.',
    'Each merchant has dedicated FedEx credentials (client_id, client_secret, account_number). Token cache keys scoped to fedex:token:{merchant_id}. No cross-merchant data access. Credential rotation supported without downtime.',
  ],

  architecture_feedback: [
    'httpx async client with connection pooling, retry via tenacity, circuit breaker via custom transport adapter.',
    'FedExTokenManager with Redis backend, 55-min TTL, refresh mutex, per-merchant key isolation.',
    'PostgreSQL shipments table with UUID PK, tracking_numbers JSONB, status state machine (10 FedEx codes mapped).',
    'CarrierAdapter abstract interface with validate_address, get_rates, create_shipment, cancel_shipment, track_shipment, create_pickup, cancel_pickup, search_locations, create_return, validate_hazmat.',
    'FedExAdapter concrete implementation, RateLimiter (1400 req/10sec queue), ResponseParser for FedEx-specific JSON schemas.',
  ],

  suggested_actions_feedback: [
    'Prioritize address validation and rate quoting for Phase 1 (checkout integration).',
    'Add webhook receiver for Advanced Integrated Visibility tracking before Phase 3.',
    'Consider dry-run mode for sandbox testing with 4 known tracking numbers from Section 12.',
  ],
};

// ============================================================
// APPROVAL GATE FEEDBACK — for Research, Planning, Assembly
// ============================================================

export const FEDEX_RESEARCH_FEEDBACK = [
  'Research covers all 10 integration modules comprehensively.',
  'OAuth token lifecycle (60-min expiry, Redis 55-min TTL, refresh mutex) and circuit breaker pattern (5 failures → 60s open, 2 half-open probes) well-documented.',
  'Key gap: webhook event retry strategy and idempotency requirements for shipment creation need more detail.',
  'Rate caching strategy (15-min per shipment profile, 24h max per FedEx ToS) is appropriate.',
  'Multi-tenant credential isolation via merchant_id prefix is correctly architected.',
].join(' ');

export const FEDEX_PLANNING_FEEDBACK = [
  'Task breakdown aligns with the 5-phase rollout timeline from Section 13 (12 weeks).',
  'DAG dependencies correctly sequence address validation before rate quoting, and shipment creation before tracking.',
  'Verify hazmat validation (Section 5.9) is gated after shipment creation and blocked for Ground Economy.',
  'Agent assignments appropriate — suggest adding a security-reviewer agent for token management (Section 3) and PII handling (Section 11) tasks.',
  'Consider explicit task for FedEx sandbox test environment setup with 4 known tracking numbers from Section 12.',
].join(' ');

export const FEDEX_ASSEMBLY_FEEDBACK = [
  'Generated spec document covers all required sections.',
  'Verify OpenAPI endpoint parity with the 16 endpoints across 8 tag groups defined in the companion YAML.',
  'Confirm data model includes all 10 FedEx status code mappings from Section 7 (OC→LABEL_CREATED, PU→PICKED_UP, IT→IN_TRANSIT, OD→OUT_FOR_DELIVERY, DL→DELIVERED, DE→DELIVERY_EXCEPTION, CA→CANCELLED, RS→RETURNED, SE→EXCEPTION, HL→HELD_AT_LOCATION).',
  'Error handling matrix from Section 10 (400/401/403/404/409/429/500/503) should be fully represented with retry semantics.',
  'Deployment timeline (Section 13, 5 phases over 12 weeks) should be reflected in the implementation roadmap.',
].join(' ');

// ============================================================
// DOCUMENT PATHS — for UI file upload via DocumentListField
// ============================================================

export const FEDEX_DOCS = {
  primary: {
    path: 'docs/fedex-carrier-integration-spec.md',
    filename: 'fedex-carrier-integration-spec.md',
  },
  supporting: [
    {
      path: 'docs/fedex-carrier-adapter-openapi.yaml',
      filename: 'fedex-carrier-adapter-openapi.yaml',
    },
  ],
};

// ============================================================
// EXPECTED OUTPUT — for final state validation
// ============================================================

export const FEDEX_EXPECTED_CONTENT = {
  /** Keywords from the primary requirements doc (fedex-carrier-integration-spec.md) */
  keywords: ['FedEx', 'shipment', 'tracking', 'rate'],
  /** Minimum document length (characters) */
  minContentLength: 500,
  /** Integration module names that should appear in headings or task descriptions */
  moduleNames: [
    'Address Validation',
    'Service Availability',
    'Rates',
    'Shipment',
    'Cancellation',
    'Tracking',
    'Pickup',
    'Location',
    'Hazmat',
    'Returns',
  ],
  /** Key OpenAPI endpoints from the supporting doc (fedex-carrier-adapter-openapi.yaml) */
  openapiEndpoints: [
    '/shipments',
    '/tracking',
    '/rates/quote',
    '/address/validate',
    '/hazmat/validate',
  ],
};
