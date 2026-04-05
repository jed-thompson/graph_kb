# FedEx Shipping Carrier Integration - E2E Test Guide

## Overview

Comprehensive end-to-end test suite for the FedEx Shipping Carrier Integration spec wizard flow. Tests validate the complete wizard experience from feature identification through all 5 gates, covering all 10 FedEx integration modules defined in the platform spec.

## Source Documents

All test data is derived from these platform specifications:

| Document | Lines | Content |
|----------|-------|---------|
| [`docs/fedex-carrier-integration-spec.md`](../../docs/fedex-carrier-integration-spec.md) | 1,200+ | 13-section spec covering 10 integration modules |
| [`docs/fedex-carrier-adapter-openapi.yaml`](../../docs/fedex-carrier-adapter-openapi.yaml) | 1,295 | OpenAPI 3.1 spec with 16 endpoints, 8 tag groups |

## Test Files

| File | Description |
|------|-------------|
| [`spec-wizard-fedex-integration.spec.ts`](../tests/spec-wizard-fedex-integration.spec.ts) | Main test suite — 18 test cases |
| [`fixtures/fedex-test-data.ts`](../tests/fixtures/fedex-test-data.ts) | Test data fixtures for all gates + 10 module scenarios |
| [`FEDEX_API_REFERENCE.md`](./FEDEX_API_REFERENCE.md) | FedEx API documentation reference |

## Test Coverage (18 Tests)

### Full Flow Test (1)
- Complete FedEx Integration spec wizard flow through all 5 gates with all 10 modules

### Gate-by-Gate Tests (5)
1. Gate 1: Identity — feature name input
2. Gate 2: Primary Document — describe option with all 10 FedEx modules
3. Gate 3: Context — business and technical context for shipping platform
4. Gate 4: Constraints — skip optional gate
5. Gate 5: Supporting Context — skip optional gate

### Module Scenario Tests (10)
Each module runs a full wizard flow with spec-derived descriptions:

| # | Module | FedEx Endpoint | Spec Section |
|---|--------|---------------|--------------|
| 1 | Address Validation | `POST /address/v1/addresses/resolve` | 5.1 |
| 2 | Service Availability | `POST /availability/v1/packageandserviceoptions` | 5.2 |
| 3 | Rates & Transit Times | `POST /rate/v1/rates/quotes` | 5.3 |
| 4 | Shipment Creation (Label Purchase) | `POST /ship/v1/shipments` | 5.4 |
| 5 | Shipment Cancellation | `PUT /ship/v1/shipments/cancel` | 5.5 |
| 6 | Tracking | `POST /track/v1/trackingnumbers` | 5.6 |
| 7 | Pickup Scheduling | `POST /pickup/v1/pickups` | 5.7 |
| 8 | Drop-Off / Location Search | `POST /location/v1/locations` | 5.8 |
| 9 | Hazardous Materials & Dangerous Goods | Ship API `dangerousGoodsDetail` | 5.9 |
| 10 | Returns & Refunds | Ship API `RETURN_SHIPMENT` + refund workflow | 5.10 |

### Validation Tests (2)
- Long description handling
- Session persistence
- Fixture data integrity (all exports well-formed)

## Fixture Data Structure

### Gate Inputs (gates 1-5)
Spec-derived content for each wizard gate, including all 10 integration modules, OAuth 2.0 auth flow, environment URLs, rate limits, hazmat compliance, and deployment timeline.

### Sample Data
- `sampleTrackingNumbers` — 4 sandbox tracking numbers from spec Section 12
- `sampleShipments` — 3 shipments (Ground, Priority Overnight, 2Day) from spec Section 5.4
- `samplePickups` — 2 pickups (Express, Ground) from spec Section 5.7
- `moduleScenarios` — 10 module-specific scenario objects with name, description, context

### Helper Functions
- `getGateInput(gateNumber)` — returns full text for any gate
- `getFeatureName()` — returns gate 1 feature name
- `getFeatureDescription()` — returns gate 1 short description

## Running Tests

```bash
# All FedEx integration tests
cd e2e
npx playwright test spec-wizard-fedex-integration.spec.ts --reporter=list --timeout=120000

# Specific module test
npx playwright test -g "Module 9: Hazardous Materials"

# Full suite (all wizard tests)
npx playwright test spec-wizard-integration.spec.ts spec-wizard-flow.spec.ts spec-wizard-fedex-integration.spec.ts --reporter=list --timeout=120000
```

## Prerequisites

- Docker Compose services running (API, Dashboard, Postgres, Neo4j, Chroma, MinIO)
- Next.js dashboard on port 3000
- FastAPI backend on port 8000

```bash
# Verify services
curl http://localhost:8000/health
curl http://localhost:3000
```

## Failure Diagnostics

On test failure, the following artifacts are automatically captured:
- Full-page screenshot
- Browser console logs (last 30 entries)
- API container logs (last 50 lines)

All artifacts are attached to the Playwright test report.

## Troubleshooting

| Issue | Check |
|-------|-------|
| Wizard panel not appearing | WebSocket connection, `docker logs graphkb-api-1 --tail 50` |
| Gate prompts not rendering | localStorage session data, chat store hydration |
| Continue button not clickable | Textarea fill state, validation errors |
| Timeout on gate transition | Backend processing, WebSocket message delivery |

## Related Documentation

- [FedEx Carrier Integration Spec](../../docs/fedex-carrier-integration-spec.md)
- [FedEx Carrier Adapter OpenAPI](../../docs/fedex-carrier-adapter-openapi.yaml)
- [FEDEX_API_REFERENCE.md](./FEDEX_API_REFERENCE.md)
