/**
 * FedEx Shipping Carrier Integration — Test Data Fixtures
 *
 * Derived from the platform integration spec:
 *   docs/fedex-carrier-integration-spec.md
 *   docs/fedex-carrier-adapter-openapi.yaml
 *
 * All sessions now use the v3 7-phase engine.
 * Gate-based exports have been removed — use contextPhaseInput and getPhaseInput() instead.
 *
 * Covers all 10 integration modules:
 *   Address Validation, Service Availability, Rates, Shipment (Purchase),
 *   Cancellation, Tracking, Pickup, Drop-Off, Hazmat, Returns & Refunds
 */

// ============================================================
// CONTEXT PHASE INPUT DATA (consolidated from former gates 1-5)
// ============================================================

/** Feature name for the FedEx integration spec */
const FEATURE_NAME = 'FedEx Carrier Integration';

/** Short description for the FedEx integration spec */
const FEATURE_DESCRIPTION =
  'Full FedEx REST API integration covering shipment purchase, cancellation, ' +
  'tracking, pickup, drop-off, hazardous materials, returns, and refunds — ' +
  'replacing deprecated SOAP services before June 2026 retirement.';

/** Primary requirements document description */
const PRIMARY_DOCUMENT = [
  'Full FedEx REST API carrier integration per docs/fedex-carrier-integration-spec.md.',
  '',
  '10 Integration Modules (P0/P1):',
  '1. Address Validation — POST /address/v1/addresses/resolve — validate & correct addresses, business/residential classification, batch up to 100',
  '2. Service Availability — POST /availability/v1/packageandserviceoptions — available services, packaging, special services, transit times',
  '3. Rates & Transit Times — POST /rate/v1/rates/quotes — account & list rates, surcharge breakdown, duty/tax for international',
  '4. Shipment Creation (Purchase) — POST /ship/v1/shipments — domestic/international labels, multi-piece, PDF/PNG/ZPLII, customs docs',
  '5. Shipment Cancellation — PUT /ship/v1/shipments/cancel — void before tender, voids tracking number and label',
  '6. Tracking — POST /track/v1/trackingnumbers — up to 30 numbers, door tag, reference, detailed scan events',
  '7. Pickup Scheduling — POST /pickup/v1/pickups — availability check, create, cancel; Express same-day, Ground next-day to 2 weeks',
  '8. Drop-Off / Location Search — POST /location/v1/locations — FedEx Office, Ship Center, Drop Box, retail partners; filter by capabilities',
  '9. Hazardous Materials — Ship API dangerousGoodsDetail — UN classes 1-9, lithium batteries (PI966/PI967), dry ice, IATA DGR / 49 CFR',
  '10. Returns & Refunds — Ship API RETURN_SHIPMENT + platform refund workflow — print-return, email-return, call-tag; full/partial/shipping/store-credit refunds',
  '',
  'Auth: OAuth 2.0 bearer token, 60-min expiry, Redis-cached with 55-min TTL, multi-tenant credential isolation.',
  'Environments: Sandbox https://apis-sandbox.fedex.com | Production https://apis.fedex.com',
  'OpenAPI spec: docs/fedex-carrier-adapter-openapi.yaml (16 endpoints, 8 tag groups)',
].join('\n');

/** Business and technical context explanation */
const CONTEXT_EXPLANATION = [
  'E-commerce fulfillment platform processing 50,000+ shipments/month.',
  'Replacing legacy SOAP integration — FedEx Web Services retiring June 1, 2026.',
  '$2.3M annual FedEx spend, 89% Ground, 11% Express/International.',
  'Average 150 refund requests/month, 200+ support tickets/week about shipping status.',
  '',
  'Target outcomes:',
  '- 40% reduction in support tickets via real-time tracking + webhook notifications',
  '- 95% refund automation (currently manual 3-5 day process)',
  '- Self-service pickup scheduling for warehouse team',
  '- Hazmat compliance for lithium battery and dry ice shipments',
  '- Sub-3-second label generation at 500 concurrent requests',
  '',
  'Platform stack: FastAPI (Python), PostgreSQL, Redis, Neo4j, ChromaDB, MinIO.',
  'Carrier adapter pattern: abstract CarrierAdapter interface with FedExAdapter, UPSAdapter, USPSAdapter implementations.',
  'HTTP client: httpx with connection pooling, retry (3x exponential backoff), circuit breaker (5 failures → 60s open).',
  'Token management: FedExTokenManager with Redis cache, 55-min TTL, refresh mutex to prevent thundering herd.',
  'Rate limiting: respect FedEx 1,400 req/10sec, queue-based request management.',
  '',
  'Integration points per spec Section 8:',
  '- Checkout Service → address validation + rate quoting',
  '- Order Service → shipment creation + cancellation',
  '- Returns Service → return label generation + refund trigger',
  '- Tracking Service → polling (2h active, 30m OFD) + webhook receiver',
].join('\n');

/** Constraints (technical + business) */
const CONSTRAINTS = [
  'API Rate Limits: 1,400 req/10sec (FedEx enforced), implement queue-based management.',
  'Security: OAuth tokens in Redis (encrypted at rest), no PII in logs, TLS 1.3 only.',
  'Performance: label gen <3s P95, tracking lookup <1s P95, 500 concurrent label requests.',
  'Retry: 3x exponential backoff (1s, 2s, 4s) for 429/500/502/503/504.',
  'Circuit breaker: open after 5 consecutive failures, 60s recovery, 2 half-open test calls.',
  'Hazmat: block DG from Ground Economy, enforce max quantity per package, require shipper DG cert.',
  'Data retention: 7-year shipping records, GDPR deletion support for EU customers.',
  '',
  'Timeline: Phase 1 (foundation + rates) weeks 1-3, Phase 2 (core shipping) weeks 4-6,',
  '  Phase 3 (pickup/returns/webhooks) weeks 7-9, Phase 4 (hazmat) weeks 10-11, Phase 5 (launch) week 12.',
  'Budget: $150K development, <$5K/month operational.',
  'Compatibility: existing order workflow, backward-compatible label formats, sandbox + production.',
  'Vendor: FedEx Developer Portal sandbox for testing, maintain certification compliance.',
  'Multi-tenant: each merchant has own FedEx credentials, isolated token cache.',
].join('\n');

/** Supporting documents and stakeholder input */
const SUPPORTING_DOCS = [
  'Platform spec: docs/fedex-carrier-integration-spec.md (1,200+ lines, 13 sections)',
  'OpenAPI spec: docs/fedex-carrier-adapter-openapi.yaml (1,295 lines, 16 endpoints)',
  '',
  'FedEx Developer Portal: https://developer.fedex.com',
  'Ship API: https://developer.fedex.com/api/en-us/catalog/ship/v1/docs.html',
  'Track API: https://developer.fedex.com/api/en-us/catalog/track/docs.html',
  'Rate API: https://developer.fedex.com/api/en-us/catalog/rate/v1/docs.html',
  'Pickup API: https://developer.fedex.com/api/en-us/catalog/pickup/docs.html',
  'Address Validation: https://developer.fedex.com/api/en-us/catalog/address-validation/docs.html',
  'Service Availability: https://developer.fedex.com/api/en-us/catalog/service-availability/docs.html',
  'Authorization: https://developer.fedex.com/api/en-us/catalog/authorization/docs.html',
  'Best Practices: https://developer.fedex.com/api/en-td/guides/best-practices.html',
  'Dangerous Goods: https://www.fedex.com/en-us/service-guide/dangerous-goods/how-to-ship.html',
  '',
  'Warehouse: bulk label printing (100+), thermal 4x6 support, pickup scheduling in WMS.',
  'Customer Service: instant tracking lookup, proactive delay notifications, refund status visibility.',
  'Finance: shipping cost reconciliation, refund tracking for accounting, weekly cost reports.',
  'Engineering: TypeScript/Python implementation, >90% test coverage, clear API docs.',
  'Compliance: IATA DGR for air, 49 CFR for ground, shipper DG certification tracking.',
].join('\n');

// ============================================================
// CONSOLIDATED CONTEXT PHASE INPUT (v3 — single multi-field form)
// ============================================================

/**
 * Consolidated context phase input for the 7-phase architecture.
 * Maps former gates 1-5 → single context phase multi-field form.
 */
export const contextPhaseInput = {
  /** spec_name */
  name: FEATURE_NAME,
  /** spec_description */
  description: FEATURE_DESCRIPTION,
  /** primary_document */
  primaryDocument: PRIMARY_DOCUMENT,
  /** user_explanation */
  explanation: CONTEXT_EXPLANATION,
  /** constraints */
  constraints: CONSTRAINTS,
  /** supporting_docs */
  supportingDocs: SUPPORTING_DOCS,
};

// ============================================================
// SAMPLE DATA — Derived from spec appendices & sandbox config
// ============================================================

/** Sandbox tracking numbers from spec Section 12 */
export const sampleTrackingNumbers = [
  { number: '794644790200', status: 'Delivered' },
  { number: '040207084723060', status: 'In Transit' },
  { number: '568838414941', status: 'Exception' },
  { number: '039813852990618', status: 'Picked Up' },
];

/** Sample shipments derived from spec Section 5.4 */
export const sampleShipments = [
  {
    id: 'SHIP-001',
    serviceType: 'FEDEX_GROUND',
    trackingNumber: '794644790200',
    origin: { city: 'Memphis', state: 'TN', zip: '38118' },
    destination: { city: 'Beverly Hills', state: 'CA', zip: '90210' },
    weight: { value: 10.0, units: 'LB' },
    labelFormat: 'PDF',
    status: 'DELIVERED',
  },
  {
    id: 'SHIP-002',
    serviceType: 'PRIORITY_OVERNIGHT',
    trackingNumber: '040207084723060',
    origin: { city: 'Memphis', state: 'TN', zip: '38118' },
    destination: { city: 'New York', state: 'NY', zip: '10001' },
    weight: { value: 5.0, units: 'LB' },
    labelFormat: 'ZPLII',
    status: 'IN_TRANSIT',
  },
  {
    id: 'SHIP-003',
    serviceType: 'FEDEX_2_DAY',
    trackingNumber: '568838414941',
    origin: { city: 'Dallas', state: 'TX', zip: '75201' },
    destination: { city: 'Chicago', state: 'IL', zip: '60601' },
    weight: { value: 15.0, units: 'LB' },
    labelFormat: 'PNG',
    status: 'EXCEPTION',
  },
];

/** Sample pickups derived from spec Section 5.7 */
export const samplePickups = [
  {
    confirmationCode: '20260315MEM123456',
    carrierCode: 'FDXE',
    scheduledDate: '2026-03-15',
    readyTime: '10:00:00',
    closeTime: '17:00:00',
    packageCount: 3,
    totalWeight: { value: 25.0, units: 'LB' },
    location: 'MEMP',
    type: 'EXPRESS',
  },
  {
    confirmationCode: '20260316MEM789012',
    carrierCode: 'FDXG',
    scheduledDate: '2026-03-16',
    readyTime: '08:00:00',
    closeTime: '16:00:00',
    packageCount: 10,
    totalWeight: { value: 120.0, units: 'LB' },
    location: 'MEMP',
    type: 'GROUND',
  },
];

// ============================================================
// WIZARD FLOW EXPECTATIONS
// ============================================================

export const wizardFlowExpectations = {
  totalPhases: 7,
  phaseIds: ['context', 'review', 'research', 'plan', 'orchestrate', 'completeness', 'generate'] as const,
  phaseLabels: ['Context', 'Review', 'Research', 'Plan', 'Orchestrate', 'Completeness', 'Generate'],
};

// ============================================================
// MODULE-SPECIFIC SCENARIO DATA
// ============================================================

export const moduleScenarios = {
  addressValidation: {
    name: 'FedEx Address Validation Integration',
    description:
      'FedEx Address Validation API (POST /address/v1/addresses/resolve). ' +
      'Validates and corrects recipient addresses, classifies business vs residential, ' +
      'batch up to 100 addresses per request. Reduces failed deliveries and address correction surcharges.',
    context: 'Checkout flow needs address validation to prevent shipping errors and reduce surcharges.',
  },
  serviceAvailability: {
    name: 'FedEx Service Availability Integration',
    description:
      'FedEx Service Availability API (POST /availability/v1/packageandserviceoptions). ' +
      'Determines available services, packaging types, and special service options for origin-destination pairs. ' +
      'Three request types: retrieve services & packaging, special service options, and transit times.',
    context: 'Checkout service needs to display available shipping options with transit times per destination.',
  },
  rates: {
    name: 'FedEx Rates & Transit Times Integration',
    description:
      'FedEx Rate API (POST /rate/v1/rates/quotes). Account-specific discounted rates and list rates, ' +
      'multi-piece shipment rating, duty/tax for international, surcharge breakdown (fuel, residential, oversize). ' +
      'Rate types: LIST, ACCOUNT, PREFERRED. Results cached per shipment profile for 15 minutes.',
    context: 'Checkout displays shipping options with prices. 50,000+ monthly shipments, $2.3M annual FedEx spend.',
  },
  shipmentCreation: {
    name: 'FedEx Shipment Creation (Label Purchase) Integration',
    description:
      'FedEx Ship API (POST /ship/v1/shipments). Domestic and international labels, multi-piece shipments, ' +
      'PDF/PNG/ZPLII label formats, customs docs for international. Special services: signature required, ' +
      'hold at location, Saturday delivery, COD. Pickup types: DROPOFF, CONTACT_FEDEX, USE_SCHEDULED.',
    context: 'Order service needs automated label generation for 10,000+ daily orders with sub-3s P95 latency.',
  },
  cancellation: {
    name: 'FedEx Shipment Cancellation Integration',
    description:
      'FedEx Ship API Cancel (PUT /ship/v1/shipments/cancel). Void shipments before tender to FedEx network. ' +
      'Cancellation voids tracking number and label. Multi-piece: cancelling master cancels all pieces. ' +
      'No partial cancellation of MPS. Platform checks LABEL_CREATED status before calling API.',
    context: 'Order management needs cancellation workflow: check status → call FedEx → void label → trigger refund.',
  },
  tracking: {
    name: 'FedEx Real-Time Tracking Integration',
    description:
      'FedEx Track API (POST /track/v1/trackingnumbers). Up to 30 numbers per request, door tag, reference tracking. ' +
      'Events: pickup scan, in-transit, out for delivery, delivered, exceptions. ' +
      'Polling: 2h active, 30m OFD. Webhook-based tracking preferred (Advanced Integrated Visibility).',
    context: 'Customer service portal needs instant tracking lookup and proactive delay notifications. 200+ tickets/week.',
  },
  pickup: {
    name: 'FedEx Pickup Scheduling Integration',
    description:
      'FedEx Pickup API: availability check, create, cancel (POST /pickup/v1/pickups, PUT cancel). ' +
      'Express same-day or next-day, Ground next-day to 2 weeks. Cannot modify — must cancel and recreate. ' +
      'Ready time must be before postal code cutoff. Residential pickup available with surcharge.',
    context: 'Warehouse team needs self-service pickup scheduling integrated into WMS. 3+ daily pickups.',
  },
  dropOff: {
    name: 'FedEx Drop-Off Location Search Integration',
    description:
      'FedEx Location Search API (POST /location/v1/locations). Find FedEx Office, Ship Center, Drop Box, ' +
      'Walgreens, Dollar General, and retail partners. Search by address/postal code with radius or lat/lng. ' +
      'Filter by capabilities: drop-off, hold-at, packing, printing. Filter by operating hours.',
    context: 'Customer-facing location finder for package drop-off and hold-at-location redirect.',
  },
  hazmat: {
    name: 'FedEx Hazardous Materials & Dangerous Goods Integration',
    description:
      'Ship API dangerousGoodsDetail for UN classes 1-9. Lithium batteries (PI966/PI967 packing instructions), ' +
      'dry ice (UN 1845, max 200kg/package), alcohol (enrolled shippers only). ' +
      'Regulatory: IATA DGR for air, 49 CFR for ground. Block DG from Ground Economy. ' +
      'Require shipper DG certification. Enforce max quantity per package.',
    context: 'Hazmat compliance for lithium battery and dry ice shipments. Product catalog flags items with UN numbers.',
  },
  returnsRefunds: {
    name: 'FedEx Returns & Refunds Integration',
    description:
      'Ship API RETURN_SHIPMENT + platform refund workflow. Return types: print-return label, email-return (PENDING), ' +
      'FedEx Ground call tag. Refund types: full, partial, shipping-only, store credit. ' +
      'Workflow: create return label → customer drops off → track return → warehouse confirms → trigger refund.',
    context: 'Returns service needs 95% refund automation. Currently manual 3-5 day process, 150 refund requests/month.',
  },
};

// ============================================================
// HELPER FUNCTIONS
// ============================================================

/** Get the feature name */
export function getFeatureName(): string {
  return FEATURE_NAME;
}

/** Get the feature description */
export function getFeatureDescription(): string {
  return FEATURE_DESCRIPTION;
}

/**
 * Get the context phase form fields for a given phase.
 *
 * Returns a record of field-id → value suitable for `fillPhaseForm()`.
 * The `name` field is omitted when `autoFilledName` is true (i.e. the
 * wizard was started via `/spec <name>` and the name is pre-filled).
 */
export function getPhaseInput(
  phase: 'context' | 'review' | 'research' | 'plan' | 'orchestrate' | 'completeness' | 'generate',
  options?: { autoFilledName?: boolean },
): Record<string, string> {
  switch (phase) {
    case 'context': {
      const fields: Record<string, string> = {
        spec_description: contextPhaseInput.description,
        primary_document: contextPhaseInput.primaryDocument,
        user_explanation: contextPhaseInput.explanation,
        constraints: contextPhaseInput.constraints,
        supporting_docs: contextPhaseInput.supportingDocs,
      };
      if (!options?.autoFilledName) {
        fields.spec_name = contextPhaseInput.name;
      }
      return fields;
    }
    case 'review':
      return { action: 'approve' };
    case 'research':
      return { action: 'approve' };
    case 'plan':
      return { action: 'approve' };
    case 'orchestrate':
      return { action: 'approve' };
    case 'completeness':
      return { action: 'approve' };
    case 'generate':
      return {}; // generate runs autonomously
    default:
      return {};
  }
}
