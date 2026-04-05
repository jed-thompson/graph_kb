# FedEx Carrier Integration — Platform Specification

> **Version:** 1.0.0  
> **Date:** 2026-03-12  
> **Status:** Draft  
> **Author:** GraphKB Platform Team  
> **FedEx API Version:** RESTful API (v1) — SOAP/WSDL retired June 2026  
> **Sources:** [FedEx Developer Portal](https://developer.fedex.com), [FedEx API Catalog](https://developer.fedex.com/en-us/catalog.html), [FedEx Best Practices](https://developer.fedex.com/api/en-td/guides/best-practices.html)

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [FedEx API Landscape](#2-fedex-api-landscape)
3. [Authentication & Authorization](#3-authentication--authorization)
4. [Environment Configuration](#4-environment-configuration)
5. [Integration Modules](#5-integration-modules)
   - 5.1 [Address Validation](#51-address-validation)
   - 5.2 [Service Availability](#52-service-availability)
   - 5.3 [Rates & Transit Times](#53-rates--transit-times)
   - 5.4 [Shipment Creation (Purchase)](#54-shipment-creation-purchase)
   - 5.5 [Shipment Cancellation](#55-shipment-cancellation)
   - 5.6 [Tracking](#56-tracking)
   - 5.7 [Pickup Scheduling](#57-pickup-scheduling)
   - 5.8 [Drop-Off / Location Search](#58-drop-off--location-search)
   - 5.9 [Hazardous Materials & Dangerous Goods](#59-hazardous-materials--dangerous-goods)
   - 5.10 [Returns & Refunds](#510-returns--refunds)
6. [OpenAPI Specification](#6-openapi-specification)
7. [Data Models](#7-data-models)
8. [Platform Adapter Architecture](#8-platform-adapter-architecture)
9. [Webhook & Event Integration](#9-webhook--event-integration)
10. [Error Handling & Retry Strategy](#10-error-handling--retry-strategy)
11. [Compliance & Regulatory](#11-compliance--regulatory)
12. [Testing Strategy](#12-testing-strategy)
13. [Deployment & Rollout](#13-deployment--rollout)

---

## 1. Executive Summary

This specification defines the full integration of FedEx carrier services into our platform. The integration covers the complete shipment lifecycle: address validation, rate quoting, label purchase, tracking, pickup scheduling, drop-off location lookup, hazardous materials handling, cancellation, returns, and refund processing.

FedEx is retiring its legacy SOAP-based Web Services effective June 1, 2026. This integration targets the current FedEx RESTful APIs exclusively, using OAuth 2.0 bearer token authentication. The REST APIs provide enhanced capabilities, stricter validation, and a streamlined developer experience compared to the legacy WSDL services.

### Scope

| Capability | FedEx API | Priority |
|---|---|---|
| Address Validation | Address Validation API | P0 |
| Service Discovery | Service Availability API | P0 |
| Rate Quoting | Rates and Transit Times API | P0 |
| Label Purchase / Shipment Creation | Ship API | P0 |
| Shipment Cancellation | Ship API (Cancel) | P0 |
| Package Tracking | Track API (Basic Integrated Visibility) | P0 |
| Pickup Scheduling & Cancellation | Pickup Request API | P1 |
| Drop-Off Location Search | Location Search API | P1 |
| Hazardous Materials / Dangerous Goods | Ship API (DG special services) | P1 |
| Returns & Refunds | Ship API (Return labels) + internal refund flow | P1 |
| Freight LTL | Freight LTL API | P2 (future) |
| Document Upload | Upload Document API | P2 (future) |

### FedEx Service Types Supported

- FedEx Express (Priority Overnight, Standard Overnight, 2Day, Express Saver)
- FedEx Ground
- FedEx Home Delivery
- FedEx Ground Economy (formerly SmartPost)
- FedEx International Priority / Economy
- FedEx Freight LTL (future phase)

---

## 2. FedEx API Landscape

FedEx organizes its RESTful APIs into the following catalog. Each API has its own versioned endpoint path under the base URL.

| API Name | Endpoint Prefix | Description |
|---|---|---|
| Authorization | `/oauth/token` | OAuth 2.0 token generation |
| Ship | `/ship/v1/shipments` | Create, cancel shipments; generate labels |
| Rate | `/rate/v1/rates/quotes` | Rate quotes and transit times |
| Track | `/track/v1/trackingnumbers` | Shipment tracking by number, reference, door tag |
| Pickup | `/pickup/v1/pickups` | Schedule, check availability, cancel pickups |
| Address Validation | `/address/v1/addresses/resolve` | Validate and correct addresses |
| Service Availability | `/availability/v1/packageandserviceoptions` | Available services, packaging, special services |
| Location Search | `/location/v1/locations` | Find FedEx drop-off and hold-at locations |
| Freight LTL | `/freight/v1/ltl/shipments` | LTL freight shipments |
| Upload Document | `/documents/v1/lhsimages/upload` | Upload customs/commercial documents |

---

## 3. Authentication & Authorization

FedEx uses OAuth 2.0 with bearer tokens. Tokens expire after 60 minutes and must be regenerated.

### Credential Types

| Customer Type | `grant_type` | Required Fields |
|---|---|---|
| Standard (Third-party) | `client_credentials` | `client_id`, `client_secret` |
| Compatible / Integrator | `csp_credentials` | `client_id`, `client_secret`, `child_key`, `child_secret` |
| Proprietary Parent-Child | `client_pc_credentials` | `client_id`, `client_secret`, `child_key`, `child_secret` |

### Token Request

```http
POST /oauth/token HTTP/1.1
Host: apis.fedex.com
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id={API_KEY}&client_secret={SECRET_KEY}
```

### Token Response

```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "scope": "CXS"
}
```

### Platform Token Management

Our platform adapter must:

1. Cache the token in Redis with a TTL of 55 minutes (5-minute safety margin)
2. Implement a token refresh mutex to prevent thundering herd on expiry
3. Attach `Authorization: Bearer {token}` to every FedEx API call
4. Support multi-tenant credential isolation (each merchant has their own FedEx credentials)

```python
class FedExTokenManager:
    """Manages OAuth tokens with automatic refresh and Redis caching."""
    
    CACHE_KEY_PREFIX = "fedex:token:"
    TOKEN_TTL_SECONDS = 3300  # 55 minutes
    
    async def get_token(self, merchant_id: str) -> str:
        """Get a valid token, refreshing if expired."""
        cache_key = f"{self.CACHE_KEY_PREFIX}{merchant_id}"
        cached = await self.redis.get(cache_key)
        if cached:
            return cached
        
        credentials = await self.get_merchant_credentials(merchant_id)
        token_data = await self._request_token(credentials)
        
        await self.redis.setex(
            cache_key,
            self.TOKEN_TTL_SECONDS,
            token_data["access_token"]
        )
        return token_data["access_token"]
```

---

## 4. Environment Configuration

| Environment | Base URL | Purpose |
|---|---|---|
| Sandbox | `https://apis-sandbox.fedex.com` | Development and integration testing |
| Production | `https://apis.fedex.com` | Live transactions |

### Platform Environment Variables

```env
# FedEx API Configuration
FEDEX_ENV=sandbox                          # sandbox | production
FEDEX_BASE_URL=https://apis-sandbox.fedex.com
FEDEX_CLIENT_ID=your_api_key
FEDEX_CLIENT_SECRET=your_secret_key
FEDEX_ACCOUNT_NUMBER=510087143             # 9-digit FedEx account number
FEDEX_CHILD_KEY=                           # For compatible/integrator customers
FEDEX_CHILD_SECRET=                        # For compatible/integrator customers
FEDEX_TOKEN_CACHE_TTL=3300                 # Token cache TTL in seconds
FEDEX_REQUEST_TIMEOUT=30                   # HTTP timeout in seconds
FEDEX_MAX_RETRIES=3                        # Max retry attempts
FEDEX_LABEL_FORMAT=PDF                     # PDF | PNG | ZPLII
FEDEX_LABEL_SIZE=PAPER_4X6                 # PAPER_4X6 | PAPER_4X675 | STOCK_4X6
FEDEX_HAZMAT_ENABLED=false                 # Enable hazardous materials support
FEDEX_WEBHOOK_SECRET=                      # For webhook signature verification
```

---

## 5. Integration Modules

### 5.1 Address Validation

Validates and corrects recipient addresses before shipment creation. Reduces failed deliveries and address correction surcharges.

**FedEx Endpoint:** `POST /address/v1/addresses/resolve`

**Capabilities:**
- Street-level address matching across 60+ countries
- Business vs. residential classification (US/Canada)
- Incomplete address completion (missing ZIP, city, state)
- Batch validation of up to 100 addresses per request
- Monthly database updates from FedEx

**Platform Integration Point:** Called automatically during checkout address entry and before any shipment creation.

```json
// Request
{
  "addressesToValidate": [
    {
      "address": {
        "streetLines": ["123 Main Street", "Suite 400"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118",
        "countryCode": "US"
      }
    }
  ]
}

// Response
{
  "output": {
    "resolvedAddresses": [
      {
        "streetLinesToken": ["123 MAIN ST STE 400"],
        "city": "MEMPHIS",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118-7423",
        "countryCode": "US",
        "classification": "BUSINESS",
        "attributes": {
          "Resolved": "true",
          "DPV": "true"
        }
      }
    ]
  }
}
```

### 5.2 Service Availability

Determines which FedEx services, packaging types, and special service options are available for a given origin-destination pair.

**FedEx Endpoint:** `POST /availability/v1/packageandserviceoptions`

**Three request types:**
1. **Retrieve Services & Packaging** — All available services and package types for outbound, return, and import shipments
2. **Retrieve Special Service Options** — Delivery signature options, return types, special handling
3. **Retrieve Services & Transit Times** — Services with estimated delivery dates

**Platform Integration Point:** Called when a user selects shipping options at checkout. Results are cached per origin-destination-date tuple for 1 hour.

```json
// Request
{
  "accountNumber": { "value": "510087143" },
  "requestedShipment": {
    "shipper": {
      "address": {
        "postalCode": "38118",
        "countryCode": "US"
      }
    },
    "recipients": [
      {
        "address": {
          "postalCode": "90210",
          "countryCode": "US"
        }
      }
    ],
    "shipDateStamp": "2026-03-15",
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 5.0 }
      }
    ]
  }
}
```

### 5.3 Rates & Transit Times

Retrieves shipping cost estimates and delivery timelines for all available FedEx services.

**FedEx Endpoint:** `POST /rate/v1/rates/quotes`

**Features:**
- Account-specific discounted rates and list rates
- Multi-piece shipment rating
- Duty and tax estimates for international shipments
- Surcharge breakdown (fuel, residential, oversize, etc.)
- Transit time with commit date/time per service

**Rate Request Types:**
- `LIST` — Published list rates
- `ACCOUNT` — Negotiated account rates
- `PREFERRED` — Preferred/incentive rates

**Platform Integration Point:** Called at checkout to display shipping options with prices. Results cached per unique shipment profile for 15 minutes.

```json
// Request
{
  "accountNumber": { "value": "510087143" },
  "rateRequestControlParameters": {
    "returnTransitTimes": true,
    "rateSortOrder": "COMMITASCENDING"
  },
  "requestedShipment": {
    "shipper": {
      "address": {
        "streetLines": ["1020 Orchard St"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118",
        "countryCode": "US",
        "residential": false
      }
    },
    "recipient": {
      "address": {
        "streetLines": ["456 Elm Ave"],
        "city": "Beverly Hills",
        "stateOrProvinceCode": "CA",
        "postalCode": "90210",
        "countryCode": "US",
        "residential": true
      }
    },
    "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
    "rateRequestType": ["ACCOUNT", "LIST"],
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 10.0 },
        "dimensions": {
          "length": 12, "width": 10, "height": 8, "units": "IN"
        }
      }
    ]
  }
}
```

### 5.4 Shipment Creation (Purchase)

Creates a shipment, generates a shipping label, and registers the package with FedEx for tracking.

**FedEx Endpoint:** `POST /ship/v1/shipments`

**Capabilities:**
- Domestic and international shipment creation
- Multi-piece shipments (MPS)
- Label generation in PDF, PNG, or ZPL II formats
- Customs documentation for international (Commercial Invoice, Pro Forma)
- Special services: signature required, hold at location, Saturday delivery, COD
- Alcohol shipments (licensed shippers only)
- Healthcare / Monitoring & Intervention (MI) shipments
- Dangerous goods / hazardous materials declarations

**Pickup Types:**
- `DROPOFF_AT_FEDEX_LOCATION` — Shipper drops off at FedEx location
- `CONTACT_FEDEX_TO_SCHEDULE` — Schedule a pickup separately
- `USE_SCHEDULED_PICKUP` — Use existing regular scheduled pickup

**Label Specifications:**

| Format | Use Case |
|---|---|
| `PDF` | Standard printing, email to customer |
| `PNG` | Web display, thermal printers |
| `ZPLII` | Zebra thermal label printers |

**Label Sizes:** `PAPER_4X6`, `PAPER_4X675`, `PAPER_85X11_TOP_HALF_LABEL`, `STOCK_4X6`

```json
// Request — Domestic Shipment
{
  "accountNumber": { "value": "510087143" },
  "labelResponseOptions": "LABEL",
  "requestedShipment": {
    "shipper": {
      "contact": {
        "personName": "[name]",
        "phoneNumber": "[phone_number]",
        "companyName": "Acme Corp"
      },
      "address": {
        "streetLines": ["1020 Orchard St"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118",
        "countryCode": "US"
      }
    },
    "recipients": [
      {
        "contact": {
          "personName": "[name]",
          "phoneNumber": "[phone_number]"
        },
        "address": {
          "streetLines": ["456 Elm Ave"],
          "city": "Beverly Hills",
          "stateOrProvinceCode": "CA",
          "postalCode": "90210",
          "countryCode": "US",
          "residential": true
        }
      }
    ],
    "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
    "serviceType": "FEDEX_GROUND",
    "packagingType": "YOUR_PACKAGING",
    "shippingChargesPayment": {
      "paymentType": "SENDER",
      "payor": {
        "responsibleParty": {
          "accountNumber": { "value": "510087143" }
        }
      }
    },
    "labelSpecification": {
      "labelFormatType": "COMMON2D",
      "imageType": "PDF",
      "labelStockType": "PAPER_4X6"
    },
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 10.0 },
        "dimensions": {
          "length": 12, "width": 10, "height": 8, "units": "IN"
        },
        "customerReferences": [
          {
            "customerReferenceType": "CUSTOMER_REFERENCE",
            "value": "ORDER-12345"
          }
        ]
      }
    ]
  }
}
```

**Response includes:**
- `masterTrackingNumber` — Primary tracking number
- `pieceResponses[].trackingNumber` — Per-package tracking numbers
- `pieceResponses[].packageDocuments[].encodedLabel` — Base64-encoded label
- `completedShipmentDetail.shipmentRating` — Final charges

### 5.5 Shipment Cancellation

Cancels a shipment before it is tendered to FedEx. Once a package is scanned into the FedEx network, cancellation is no longer possible via API.

**FedEx Endpoint:** `PUT /ship/v1/shipments/cancel`

**Rules:**
- Shipment must not yet be tendered (picked up or dropped off)
- Cancellation voids the tracking number and label
- Multi-piece shipments: cancelling the master cancels all pieces
- No partial cancellation of MPS shipments

```json
// Request
{
  "accountNumber": { "value": "510087143" },
  "trackingNumber": "794644790200"
}

// Response
{
  "output": {
    "cancelledShipment": true,
    "cancelledTrackingNumber": "794644790200"
  }
}
```

**Platform Flow:**
1. User requests cancellation from order management
2. Platform checks internal status — if `LABEL_CREATED` and not `PICKED_UP`, proceed
3. Call FedEx cancel endpoint
4. On success: void label, update order status, trigger refund if prepaid
5. On failure (already tendered): notify user to contact FedEx directly

### 5.6 Tracking

Provides real-time shipment visibility across all FedEx services.

**FedEx Endpoint:** `POST /track/v1/trackingnumbers`

**Tracking Methods:**
- By tracking number (up to 30 per request)
- By door tag number (DT + 12 digits)
- By FedEx Office order number
- By reference number (requires sender account number)

**Tracking Events Include:**
- Pickup scan
- In-transit scans with location
- Out for delivery
- Delivered (with signature if applicable)
- Exception events (delay, address issue, weather)
- Estimated delivery date updates

```json
// Request
{
  "includeDetailedScans": true,
  "trackingInfo": [
    {
      "trackingNumberInfo": {
        "trackingNumber": "794644790200"
      }
    }
  ]
}

// Response (simplified)
{
  "output": {
    "completeTrackResults": [
      {
        "trackingNumber": "794644790200",
        "trackResults": [
          {
            "trackingNumberInfo": {
              "trackingNumber": "794644790200",
              "trackingNumberUniqueId": "12345"
            },
            "latestStatusDetail": {
              "code": "IT",
              "derivedCode": "IT",
              "statusByLocale": "In transit",
              "description": "In transit",
              "scanLocation": {
                "city": "DALLAS",
                "stateOrProvinceCode": "TX",
                "countryCode": "US"
              }
            },
            "dateAndTimes": [
              {
                "type": "ESTIMATED_DELIVERY",
                "dateTime": "2026-03-15T16:00:00-05:00"
              },
              {
                "type": "SHIP",
                "dateTime": "2026-03-12T10:30:00-06:00"
              }
            ],
            "scanEvents": [
              {
                "date": "2026-03-13T08:15:00-05:00",
                "eventType": "IT",
                "eventDescription": "In transit",
                "scanLocation": {
                  "city": "DALLAS",
                  "stateOrProvinceCode": "TX"
                }
              }
            ],
            "packageDetails": {
              "packagingDescription": { "type": "YOUR_PACKAGING" },
              "physicalPackagingType": "PACKAGE",
              "count": "1",
              "weightAndDimensions": {
                "weight": [
                  { "value": "10.0", "unit": "LB" }
                ]
              }
            }
          }
        ]
      }
    ]
  }
}
```

**Platform Polling Strategy:**
- Active shipments: poll every 2 hours
- Out for delivery: poll every 30 minutes
- Delivered/Exception: stop polling, store final state
- Webhook-based tracking preferred when available (see Section 9)

### 5.7 Pickup Scheduling

Schedule a FedEx courier to pick up packages from a specified location.

**FedEx Endpoints:**
- `POST /pickup/v1/pickups` — Check availability
- `POST /pickup/v1/pickups` — Create pickup
- `PUT /pickup/v1/pickups/cancel` — Cancel pickup

**Pickup Types:**
- FedEx Express: same-day or next business day
- FedEx Ground: next business day up to 2 weeks in advance
- Residential pickup: available with surcharge

**Key Constraints:**
- Ready time must be before postal code cutoff time
- Minimum access time window required (varies by location)
- Cannot modify a pickup — must cancel and recreate
- Express pickups: cancel same day only
- Ground pickups: cancel 24 hours after submission

```json
// Check Availability Request
{
  "pickupAddress": {
    "streetLines": ["1020 Orchard St"],
    "city": "Memphis",
    "stateOrProvinceCode": "TN",
    "postalCode": "38118",
    "countryCode": "US",
    "residential": false
  },
  "pickupRequestType": ["SAME_DAY", "FUTURE_DAY"],
  "dispatchDate": "2026-03-15",
  "carriers": ["FDXE", "FDXG"],
  "numberOfBusinessDays": 5
}

// Create Pickup Request
{
  "associatedAccountNumber": { "value": "510087143" },
  "originDetail": {
    "pickupAddressType": "BUSINESS",
    "pickupLocation": {
      "contact": {
        "companyName": "Acme Corp",
        "personName": "[name]",
        "phoneNumber": "[phone_number]"
      },
      "address": {
        "streetLines": ["1020 Orchard St"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118",
        "countryCode": "US"
      }
    },
    "readyDateTimestamp": "2026-03-15T10:00:00",
    "customerCloseTime": "17:00:00",
    "packageLocation": "FRONT",
    "buildingPartDescription": "Suite 400"
  },
  "carrierCode": "FDXE",
  "totalWeight": { "units": "LB", "value": 25.0 },
  "packageCount": 3
}

// Cancel Pickup Request
{
  "associatedAccountNumber": { "value": "510087143" },
  "pickupConfirmationCode": "20260315MEM123456",
  "scheduledDate": "2026-03-15",
  "location": "MEMP"
}
```

### 5.8 Drop-Off / Location Search

Find nearby FedEx locations for package drop-off, hold-at-location, or redirect-to-hold.

**FedEx Endpoint:** `POST /location/v1/locations`

**Location Types:**
- FedEx Office (full service)
- FedEx Ship Center
- FedEx Authorized ShipCenter
- FedEx Drop Box
- Walgreens, Dollar General, and other retail partners
- FedEx OnSite locations

**Search Criteria:**
- By address / postal code with radius
- By geographic coordinates (lat/lng)
- Filter by services offered (drop-off, hold-at, packing, printing)
- Filter by operating hours

```json
// Request
{
  "location": {
    "address": {
      "city": "Memphis",
      "stateOrProvinceCode": "TN",
      "postalCode": "38118",
      "countryCode": "US"
    }
  },
  "locationSearchCriterion": "ADDRESS",
  "locationTypes": ["FEDEX_OFFICE", "FEDEX_SHIP_CENTER", "DROP_BOX"],
  "resultsRequested": 10,
  "radius": { "value": 10, "unit": "MI" },
  "locationCapabilities": [
    { "type": "DROPOFF" }
  ]
}
```

### 5.9 Hazardous Materials & Dangerous Goods

FedEx supports shipping of regulated hazardous materials and dangerous goods through both Express and Ground networks, with specific API fields and compliance requirements.

**Regulatory Frameworks:**
- **Air transport (Express):** IATA Dangerous Goods Regulations (DGR)
- **Ground transport:** US DOT 49 CFR (domestic), ADR (Europe)
- **International:** Country-specific import/export restrictions apply

**FedEx Dangerous Goods Classes:**

| UN Class | Description | FedEx Express | FedEx Ground |
|---|---|---|---|
| 1 | Explosives | Limited | No |
| 2 | Gases (flammable, non-flammable, toxic) | Yes (limited) | Yes (limited) |
| 3 | Flammable Liquids | Yes | Yes |
| 4 | Flammable Solids | Yes | Yes |
| 5 | Oxidizers & Organic Peroxides | Yes | Yes |
| 6 | Toxic & Infectious Substances | Yes (limited) | Yes (limited) |
| 7 | Radioactive Materials | Yes (certified) | No |
| 8 | Corrosives | Yes | Yes |
| 9 | Miscellaneous (lithium batteries, dry ice, magnetized) | Yes | Yes |

**Special Categories:**
- **Dry Ice (UN 1845):** Max 200 kg per package. Only DG type shippable via FedEx International First.
- **Lithium Batteries:** Section II (standalone) requires full DG declaration. Section I (contained in equipment) may ship as non-restricted with proper marking.
- **Alcohol:** Requires enrollment in FedEx alcohol shipping program. Individuals cannot ship alcohol. Wine is the only type shippable direct-to-consumer.

**Ship API — Dangerous Goods Fields:**

```json
{
  "requestedShipment": {
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 15.0 },
        "itemDescriptionForClearance": "Lithium Ion Batteries",
        "dangerousGoodsDetail": {
          "offeror": "Acme Battery Corp",
          "accessibility": "ACCESSIBLE",
          "emergencyContactNumber": "[phone_number]",
          "options": ["HAZARDOUS_MATERIALS"],
          "containers": [
            {
              "containerType": "PACKAGE",
              "numberOfContainers": 1,
              "hazardousCommodities": [
                {
                  "description": {
                    "sequenceNumber": 1,
                    "processingOptions": ["INCLUDE_SPECIAL_PROVISIONS"],
                    "subsidiaryClasses": ["NONE"],
                    "labelText": "LITHIUM ION BATTERIES",
                    "technicalName": "Lithium ion batteries",
                    "packingDetails": {
                      "packingInstructions": "PI966",
                      "cargoAircraftOnly": false
                    },
                    "authorization": "SP188",
                    "quantity": 4,
                    "quantityUnits": "PCS",
                    "hazardClass": "9",
                    "properShippingName": "Lithium ion batteries",
                    "idNumber": "UN3481"
                  },
                  "netWeight": { "units": "KG", "value": 2.5 },
                  "quantity": { "quantityType": "NET", "amount": 4.0, "units": "PCS" }
                }
              ]
            }
          ]
        }
      }
    ]
  }
}
```

**Platform DG Workflow:**
1. Product catalog flags items as hazardous with UN number, class, packing group
2. At checkout, platform detects DG items and validates service eligibility
3. Ship API request includes `dangerousGoodsDetail` block
4. Platform generates required documentation (Shipper's Declaration for Dangerous Goods)
5. Label includes DG markings and handling labels automatically
6. Pickup request flagged for DG handling

**Restrictions enforced by platform:**
- Block DG items from FedEx Ground Economy (not supported)
- Block DG items from residential delivery where prohibited
- Enforce max quantity limits per package and per shipment
- Require shipper DG certification number on file

### 5.10 Returns & Refunds

FedEx supports multiple return shipment methods. Our platform wraps these with a refund workflow.

**Return Label Types:**

| Type | Description | API Field |
|---|---|---|
| Print Return Label | Merchant generates label, includes in outbound package | `shipmentSpecialServices.returnShipmentDetail.returnType: PRINT_RETURN_LABEL` |
| Email Return Label | FedEx emails label to customer | `returnType: PENDING` with email notification |
| FedEx Ground Call Tag | FedEx picks up return from customer | Pickup API + return label |

**Return Shipment Request:**

```json
{
  "accountNumber": { "value": "510087143" },
  "labelResponseOptions": "LABEL",
  "requestedShipment": {
    "shipper": {
      "contact": {
        "personName": "[name]",
        "phoneNumber": "[phone_number]"
      },
      "address": {
        "streetLines": ["456 Elm Ave"],
        "city": "Beverly Hills",
        "stateOrProvinceCode": "CA",
        "postalCode": "90210",
        "countryCode": "US"
      }
    },
    "recipients": [
      {
        "contact": {
          "personName": "[name]",
          "phoneNumber": "[phone_number]",
          "companyName": "Acme Corp Returns"
        },
        "address": {
          "streetLines": ["1020 Orchard St"],
          "city": "Memphis",
          "stateOrProvinceCode": "TN",
          "postalCode": "38118",
          "countryCode": "US"
        }
      }
    ],
    "serviceType": "FEDEX_GROUND",
    "packagingType": "YOUR_PACKAGING",
    "pickupType": "DROPOFF_AT_FEDEX_LOCATION",
    "shipmentSpecialServices": {
      "specialServiceTypes": ["RETURN_SHIPMENT"],
      "returnShipmentDetail": {
        "returnType": "PRINT_RETURN_LABEL",
        "returnAssociation": {
          "trackingNumber": "794644790200"
        }
      }
    },
    "labelSpecification": {
      "labelFormatType": "COMMON2D",
      "imageType": "PDF",
      "labelStockType": "PAPER_4X6"
    },
    "requestedPackageLineItems": [
      {
        "weight": { "units": "LB", "value": 10.0 }
      }
    ]
  }
}
```

**Platform Refund Workflow:**

```
Customer requests return
        │
        ▼
Platform creates return label (Ship API with RETURN_SHIPMENT)
        │
        ▼
Label emailed/displayed to customer
        │
        ▼
Customer drops off at FedEx location (or pickup scheduled)
        │
        ▼
Platform tracks return shipment (Track API polling)
        │
        ▼
Return delivered to warehouse
        │
        ▼
Warehouse inspects & confirms receipt
        │
        ▼
Platform triggers refund (payment gateway)
        │
        ▼
Customer notified of refund
```

**Refund Types:**
- Full refund: entire order amount minus shipping (configurable)
- Partial refund: specific items only
- Shipping refund: if carrier caused the return (damage, wrong item)
- Store credit: alternative to monetary refund

---

## 6. OpenAPI Specification

The following is our platform's carrier adapter OpenAPI spec that wraps the FedEx APIs into a unified interface. This is the contract our internal services use — it abstracts FedEx-specific details behind a carrier-agnostic interface.

The full OpenAPI 3.1 specification is available at:

📄 **[`docs/fedex-carrier-adapter-openapi.yaml`](./fedex-carrier-adapter-openapi.yaml)**

This spec defines 16 endpoints across 8 tag groups covering the complete shipment lifecycle. Key design decisions:

- Carrier-agnostic interface: same endpoint structure works for UPS, USPS, DHL adapters
- Multi-tenant: `merchant_id` on every request for credential isolation
- Hazmat as first-class citizen: dedicated validation endpoint + inline on shipment creation
- Returns decoupled from refunds: return label creation is a shipping operation; refund is a payment operation triggered after warehouse receipt

---

## 7. Data Models

### Platform Shipment Entity

```python
class Shipment(Base):
    __tablename__ = "shipments"
    
    id = Column(UUID, primary_key=True, default=uuid4)
    merchant_id = Column(UUID, ForeignKey("merchants.id"), nullable=False)
    order_id = Column(UUID, ForeignKey("orders.id"), nullable=False)
    carrier = Column(String, default="fedex")  # fedex | ups | usps | dhl
    
    # FedEx-specific
    fedex_account_number = Column(String)
    service_type = Column(String)  # FEDEX_GROUND, PRIORITY_OVERNIGHT, etc.
    packaging_type = Column(String)
    pickup_type = Column(String)
    
    # Tracking
    master_tracking_number = Column(String, index=True)
    tracking_numbers = Column(JSONB)  # Array of per-package tracking numbers
    
    # Status
    status = Column(String, default="LABEL_CREATED")
    # LABEL_CREATED → PICKED_UP → IN_TRANSIT → OUT_FOR_DELIVERY → DELIVERED
    # LABEL_CREATED → CANCELLED
    # IN_TRANSIT → EXCEPTION → IN_TRANSIT → DELIVERED
    
    # Addresses
    origin_address = Column(JSONB)
    destination_address = Column(JSONB)
    
    # Packages
    packages = Column(JSONB)  # Array of {weight, dimensions, hazmat, tracking_number}
    
    # Financials
    total_charge = Column(Numeric(10, 2))
    currency = Column(String, default="USD")
    surcharges = Column(JSONB)
    
    # Labels
    label_format = Column(String, default="PDF")
    label_urls = Column(JSONB)
    
    # Hazmat
    has_hazmat = Column(Boolean, default=False)
    hazmat_details = Column(JSONB)
    
    # Dates
    ship_date = Column(DateTime)
    estimated_delivery = Column(DateTime)
    actual_delivery = Column(DateTime)
    created_at = Column(DateTime, default=func.now())
    updated_at = Column(DateTime, onupdate=func.now())
    
    # Return tracking
    is_return = Column(Boolean, default=False)
    original_shipment_id = Column(UUID, ForeignKey("shipments.id"))
    
    # Pickup
    pickup_confirmation_code = Column(String)
    pickup_date = Column(Date)
```

### FedEx Status Code Mapping

| FedEx Code | FedEx Description | Platform Status |
|---|---|---|
| `OC` | Order Created | `LABEL_CREATED` |
| `PU` | Picked Up | `PICKED_UP` |
| `IT` | In Transit | `IN_TRANSIT` |
| `OD` | Out for Delivery | `OUT_FOR_DELIVERY` |
| `DL` | Delivered | `DELIVERED` |
| `DE` | Delivery Exception | `EXCEPTION` |
| `CA` | Cancelled | `CANCELLED` |
| `RS` | Return to Shipper | `RETURNED` |
| `SE` | Shipment Exception | `EXCEPTION` |
| `HL` | Hold at Location | `HELD_AT_LOCATION` |

---

## 8. Platform Adapter Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Platform Services                         │
│  ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌────────────┐  │
│  │ Checkout │  │  Order   │  │ Returns  │  │  Tracking  │  │
│  │ Service  │  │ Service  │  │ Service  │  │  Service   │  │
│  └────┬─────┘  └────┬─────┘  └────┬─────┘  └─────┬──────┘  │
│       │              │              │               │        │
│  ┌────▼──────────────▼──────────────▼───────────────▼────┐  │
│  │              Carrier Adapter Interface                 │  │
│  │  ┌─────────────────────────────────────────────────┐  │  │
│  │  │  CarrierAdapter (Abstract)                      │  │  │
│  │  │  ├── validate_address()                         │  │  │
│  │  │  ├── get_rates()                                │  │  │
│  │  │  ├── create_shipment()                          │  │  │
│  │  │  ├── cancel_shipment()                          │  │  │
│  │  │  ├── track_shipment()                           │  │  │
│  │  │  ├── create_pickup()                            │  │  │
│  │  │  ├── cancel_pickup()                            │  │  │
│  │  │  ├── search_locations()                         │  │  │
│  │  │  ├── create_return()                            │  │  │
│  │  │  └── validate_hazmat()                          │  │  │
│  │  └─────────────────────────────────────────────────┘  │  │
│  │       │              │              │                  │  │
│  │  ┌────▼────┐   ┌────▼────┐   ┌────▼────┐             │  │
│  │  │  FedEx  │   │   UPS   │   │  USPS   │  ...        │  │
│  │  │ Adapter │   │ Adapter │   │ Adapter │             │  │
│  │  └────┬────┘   └─────────┘   └─────────┘             │  │
│  └───────┼───────────────────────────────────────────────┘  │
│          │                                                   │
└──────────┼───────────────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────┐
    │         FedEx REST API Gateway           │
    │  ┌──────────┐  ┌──────────────────────┐ │
    │  │  Token   │  │  Rate Limiter        │ │
    │  │  Manager │  │  (100 req/sec)       │ │
    │  └──────────┘  └──────────────────────┘ │
    │  ┌──────────────────────────────────┐   │
    │  │  HTTP Client (httpx/aiohttp)     │   │
    │  │  - Connection pooling            │   │
    │  │  - Retry with exponential backoff│   │
    │  │  - Circuit breaker               │   │
    │  │  - Request/response logging      │   │
    │  └──────────────────────────────────┘   │
    └─────────────────────────────────────────┘
           │
    ┌──────▼──────────────────────────────────┐
    │  https://apis.fedex.com                  │
    │  (or https://apis-sandbox.fedex.com)     │
    └──────────────────────────────────────────┘
```

### Adapter Implementation Pattern

```python
from abc import ABC, abstractmethod
from typing import List, Optional

class CarrierAdapter(ABC):
    """Abstract carrier adapter interface."""
    
    @abstractmethod
    async def validate_address(self, address: Address) -> AddressValidationResult: ...
    
    @abstractmethod
    async def get_rates(self, request: RateRequest) -> List[RateQuote]: ...
    
    @abstractmethod
    async def create_shipment(self, request: ShipmentRequest) -> ShipmentResult: ...
    
    @abstractmethod
    async def cancel_shipment(self, tracking_number: str) -> CancelResult: ...
    
    @abstractmethod
    async def track_shipment(self, tracking_number: str) -> TrackingResult: ...
    
    @abstractmethod
    async def create_pickup(self, request: PickupRequest) -> PickupResult: ...
    
    @abstractmethod
    async def cancel_pickup(self, confirmation_code: str) -> CancelResult: ...
    
    @abstractmethod
    async def search_locations(self, request: LocationRequest) -> List[Location]: ...
    
    @abstractmethod
    async def create_return(self, request: ReturnRequest) -> ReturnResult: ...
    
    @abstractmethod
    async def validate_hazmat(self, request: HazmatRequest) -> HazmatValidation: ...


class FedExAdapter(CarrierAdapter):
    """FedEx REST API carrier adapter."""
    
    def __init__(self, config: FedExConfig):
        self.config = config
        self.token_manager = FedExTokenManager(config)
        self.http_client = FedExHttpClient(config)
    
    async def create_shipment(self, request: ShipmentRequest) -> ShipmentResult:
        token = await self.token_manager.get_token(request.merchant_id)
        
        # Validate hazmat if present
        if request.has_hazmat:
            validation = await self.validate_hazmat(request.hazmat_request)
            if not validation.valid:
                raise HazmatValidationError(validation.violations)
        
        # Build FedEx-specific payload
        payload = self._build_ship_payload(request)
        
        # Call FedEx Ship API
        response = await self.http_client.post(
            "/ship/v1/shipments",
            json=payload,
            token=token,
        )
        
        return self._parse_ship_response(response)
```

---

## 9. Webhook & Event Integration

FedEx provides push-based tracking notifications via webhooks (Advanced Integrated Visibility). Our platform should subscribe to these for real-time updates instead of polling.

### Webhook Events

| Event | Description | Platform Action |
|---|---|---|
| `SHIPMENT_CREATED` | Label created | Update status to `LABEL_CREATED` |
| `PICKED_UP` | Package scanned at pickup | Update status to `PICKED_UP` |
| `IN_TRANSIT` | Package in transit | Update status, notify customer |
| `OUT_FOR_DELIVERY` | On delivery vehicle | Update status, notify customer |
| `DELIVERED` | Package delivered | Update status, trigger post-delivery flow |
| `DELIVERY_EXCEPTION` | Delivery issue | Update status, alert operations team |
| `RETURN_TO_SHIPPER` | Package being returned | Update status, alert merchant |

### Webhook Endpoint

```python
@router.post("/webhooks/fedex")
async def fedex_webhook(request: Request):
    """Receive FedEx tracking webhook events."""
    body = await request.body()
    signature = request.headers.get("X-FedEx-Signature")
    
    # Verify webhook signature
    if not verify_fedex_signature(body, signature):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    payload = await request.json()
    tracking_number = payload["trackingNumber"]
    event_type = payload["eventType"]
    
    # Map FedEx event to platform status
    status = FEDEX_EVENT_STATUS_MAP.get(event_type)
    if status:
        await shipment_service.update_tracking_status(
            tracking_number=tracking_number,
            status=status,
            event_data=payload,
        )
    
    return {"status": "ok"}
```

---

## 10. Error Handling & Retry Strategy

### FedEx Error Code Categories

| HTTP Status | Category | Retry? | Action |
|---|---|---|---|
| 400 | Validation error | No | Fix request payload |
| 401 | Auth failure | Yes (refresh token) | Refresh OAuth token, retry once |
| 403 | Forbidden | No | Check account permissions |
| 404 | Not found | No | Invalid tracking number or resource |
| 409 | Conflict | No | Shipment already tendered |
| 429 | Rate limited | Yes (backoff) | Exponential backoff |
| 500 | Server error | Yes (3x) | Retry with exponential backoff |
| 503 | Service unavailable | Yes (3x) | Retry with exponential backoff |

### Retry Configuration

```python
RETRY_CONFIG = {
    "max_retries": 3,
    "initial_backoff_seconds": 1.0,
    "backoff_multiplier": 2.0,
    "max_backoff_seconds": 30.0,
    "retryable_status_codes": [429, 500, 502, 503, 504],
    "retryable_exceptions": [
        "ConnectionError",
        "TimeoutError",
        "ServerDisconnectedError",
    ],
}
```

### Circuit Breaker

```python
CIRCUIT_BREAKER_CONFIG = {
    "failure_threshold": 5,       # Open after 5 consecutive failures
    "recovery_timeout": 60,       # Try again after 60 seconds
    "half_open_max_calls": 2,     # Allow 2 test calls in half-open state
    "monitored_exceptions": [
        "ConnectionError",
        "TimeoutError",
    ],
}
```

---

## 11. Compliance & Regulatory

### Hazardous Materials Compliance

| Requirement | Implementation |
|---|---|
| IATA DGR (air) | Validate UN number, class, packing group, quantity limits |
| 49 CFR (US ground) | Validate DOT requirements for ground shipments |
| Shipper certification | Require DG certification number on merchant profile |
| Documentation | Auto-generate Shipper's Declaration for Dangerous Goods |
| Labeling | FedEx API auto-applies DG labels to shipping labels |
| Training records | Platform tracks merchant DG training expiry dates |

### Data Privacy

| Requirement | Implementation |
|---|---|
| PII handling | Encrypt addresses and contact info at rest (AES-256) |
| Data retention | Purge shipment PII after 7 years (regulatory minimum) |
| GDPR | Support data deletion requests for EU customers |
| Logging | Mask tracking numbers and addresses in application logs |

### FedEx Terms of Service

- Merchants must have a valid FedEx account and accept FedEx Terms and Conditions
- Platform must not store FedEx OAuth credentials in plaintext
- Rate information must not be cached for more than 24 hours
- Label images must not be modified after generation
- Alcohol shipping requires enrollment in FedEx alcohol program

---

## 12. Testing Strategy

### Test Environments

| Environment | Base URL | Credentials | Purpose |
|---|---|---|---|
| Sandbox | `https://apis-sandbox.fedex.com` | Test API key/secret | Integration testing |
| Mock | Local mock server | N/A | Unit testing, CI/CD |

### Test Matrix

| Module | Unit Tests | Integration Tests | E2E Tests |
|---|---|---|---|
| Token Manager | Token caching, refresh, mutex | OAuth flow against sandbox | Full auth → ship flow |
| Address Validation | Payload building, response parsing | Validate real addresses | Checkout address entry |
| Rate Quoting | Rate comparison, surcharge calc | Quote against sandbox | Checkout rate display |
| Shipment Creation | Payload building, label parsing | Create shipment in sandbox | Full purchase flow |
| Cancellation | Status validation, error handling | Cancel in sandbox | Order cancellation flow |
| Tracking | Status mapping, event parsing | Track sandbox shipments | Tracking page updates |
| Pickup | Availability check, scheduling | Schedule in sandbox | Pickup scheduling UI |
| Location Search | Result filtering, distance calc | Search sandbox locations | Location finder UI |
| Hazmat | Validation rules, DG classification | DG shipment in sandbox | Hazmat checkout flow |
| Returns | Return label generation | Return in sandbox | Return request flow |
| Refunds | Refund calculation, payment trigger | Refund with test gateway | Full return-to-refund |

### Sandbox Test Tracking Numbers

FedEx provides test tracking numbers in the sandbox environment:

| Tracking Number | Simulated Status |
|---|---|
| `794644790200` | Delivered |
| `040207084723060` | In Transit |
| `568838414941` | Exception |
| `039813852990618` | Picked Up |

---

## 13. Deployment & Rollout

### Phase 1 — Foundation (Weeks 1-3)
- FedEx developer account setup and sandbox credentials
- Token manager with Redis caching
- HTTP client with retry and circuit breaker
- Address validation integration
- Rate quoting integration

### Phase 2 — Core Shipping (Weeks 4-6)
- Shipment creation with label generation
- Shipment cancellation
- Tracking integration (polling-based)
- Database models and migrations
- Admin UI for shipment management

### Phase 3 — Advanced Features (Weeks 7-9)
- Pickup scheduling and cancellation
- Drop-off location search
- Return label generation
- Refund workflow integration
- Webhook-based tracking (replace polling)

### Phase 4 — Hazmat & Compliance (Weeks 10-11)
- Hazardous materials validation engine
- DG shipment creation
- Compliance documentation generation
- Merchant DG certification tracking

### Phase 5 — Production Launch (Week 12)
- Production credential configuration
- Load testing against FedEx production
- Monitoring and alerting setup
- Merchant onboarding documentation
- Go-live with beta merchants

---

## Appendix A: FedEx Service Type Codes

| Code | Service Name |
|---|---|
| `FEDEX_GROUND` | FedEx Ground |
| `FEDEX_HOME_DELIVERY` | FedEx Home Delivery |
| `GROUND_HOME_DELIVERY` | FedEx Ground Home Delivery (alias) |
| `FEDEX_EXPRESS_SAVER` | FedEx Express Saver |
| `FEDEX_2_DAY` | FedEx 2Day |
| `FEDEX_2_DAY_AM` | FedEx 2Day A.M. |
| `STANDARD_OVERNIGHT` | FedEx Standard Overnight |
| `PRIORITY_OVERNIGHT` | FedEx Priority Overnight |
| `FIRST_OVERNIGHT` | FedEx First Overnight |
| `FEDEX_INTERNATIONAL_PRIORITY` | FedEx International Priority |
| `FEDEX_INTERNATIONAL_ECONOMY` | FedEx International Economy |
| `INTERNATIONAL_FIRST` | FedEx International First |
| `FEDEX_FREIGHT_ECONOMY` | FedEx Freight Economy |
| `FEDEX_FREIGHT_PRIORITY` | FedEx Freight Priority |
| `SMART_POST` | FedEx Ground Economy (legacy code) |
| `FEDEX_GROUND_ECONOMY` | FedEx Ground Economy |

## Appendix B: FedEx Packaging Type Codes

| Code | Description |
|---|---|
| `YOUR_PACKAGING` | Customer-supplied packaging |
| `FEDEX_ENVELOPE` | FedEx Envelope |
| `FEDEX_PAK` | FedEx Pak |
| `FEDEX_BOX` | FedEx Box |
| `FEDEX_TUBE` | FedEx Tube |
| `FEDEX_SMALL_BOX` | FedEx Small Box |
| `FEDEX_MEDIUM_BOX` | FedEx Medium Box |
| `FEDEX_LARGE_BOX` | FedEx Large Box |
| `FEDEX_EXTRA_LARGE_BOX` | FedEx Extra Large Box |
| `FEDEX_10KG_BOX` | FedEx 10kg Box |
| `FEDEX_25KG_BOX` | FedEx 25kg Box |

## Appendix C: Referenced Documentation

- [FedEx Developer Portal](https://developer.fedex.com)
- [FedEx API Catalog](https://developer.fedex.com/en-us/catalog.html)
- [FedEx Ship API Docs](https://developer.fedex.com/api/en-us/catalog/ship/v1/docs.html)
- [FedEx Track API Docs](https://developer.fedex.com/api/en-us/catalog/track/docs.html)
- [FedEx Rate API Docs](https://developer.fedex.com/api/en-us/catalog/rate/v1/docs.html)
- [FedEx Pickup API Docs](https://developer.fedex.com/api/en-us/catalog/pickup/docs.html)
- [FedEx Address Validation Docs](https://developer.fedex.com/api/en-us/catalog/address-validation/docs.html)
- [FedEx Service Availability Docs](https://developer.fedex.com/api/en-us/catalog/service-availability/docs.html)
- [FedEx Authorization Docs](https://developer.fedex.com/api/en-us/catalog/authorization/docs.html)
- [FedEx Best Practices](https://developer.fedex.com/api/en-td/guides/best-practices.html)
- [FedEx Dangerous Goods Guide](https://www.fedex.com/en-us/service-guide/dangerous-goods/how-to-ship.html)
- [FedEx Hazardous Materials Guide](https://www.fedex.com/en-us/shipping/hazardous-materials/how-to-ship.html)

> Content was rephrased for compliance with licensing restrictions. All API details sourced from the [FedEx Developer Portal](https://developer.fedex.com).
