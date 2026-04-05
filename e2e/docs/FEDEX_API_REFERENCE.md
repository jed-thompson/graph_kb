# FedEx API Reference for Shipping Carrier Integration

> Source: FedEx Developer Portal (https://developer.fedex.com/api/en-us/home.html)

## Overview

This document provides comprehensive reference information for integrating FedEx shipping APIs into a shipping carrier platform. It covers all major API endpoints required for label purchases, cancellations, refunds, tracking, and pickup/drop-off services.

---

## Authentication

### OAuth 2.0 Client Credentials Flow

All FedEx APIs use OAuth 2.0 for authentication.

```http
POST https://apis.fedex.com/oauth/token
Content-Type: application/x-www-form-urlencoded

grant_type=client_credentials&client_id=YOUR_API_KEY&client_secret=YOUR_SECRET_KEY
```

**Response:**
```json
{
  "access_token": "eyJhbGciOiJSUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "expires_in": 3600,
  "scope": "CXS"
}
```

### Environment URLs

| Environment | Base URL |
|------------|----------|
| Sandbox/Test | `https://apis-sandbox.fedex.com` |
| Production | `https://apis.fedex.com` |

### Rate Limits

- **Daily Quota**: Organization-based daily transaction limit
- **Project Quota**: Per-capability daily limit (e.g., Track: 100K/day)
- **Rate Limit**: 1,400 transactions per 10 seconds
- **Burst Limit**: 3 hits/second (IP-based), 1 hit/second average

---

## API Catalog

### 1. Ship API

**Purpose**: Create shipments, generate shipping labels, and manage shipment lifecycle.

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/ship/v1/shipments` | POST | Create shipment and generate label |
| `/ship/v1/shipments/cancel` | PUT | Cancel a shipment |
| `/ship/v1/shipments/packages` | POST | Validate package details |

**Supported Services:**
- FedEx Express (First, Priority, Priority Express)
- FedEx Ground
- FedEx Ground Economy
- FedEx International (International First, Priority, Economy)
- FedEx Freight

**Sample Request - Create Shipment:**
```json
{
  "mergeLabelDocOption": "LABELS_AND_DOCS",
  "requestedShipment": {
    "shipDatestamp": "2025-01-15",
    "totalDeclaredValue": {
      "amount": 150.00,
      "currency": "USD"
    },
    "shipper": {
      "address": {
        "streetLines": ["123 Shipper Street"],
        "city": "Memphis",
        "stateOrProvinceCode": "TN",
        "postalCode": "38118",
        "countryCode": "US"
      },
      "contact": {
        "personName": "John Shipper",
        "companyName": "ShipCo Inc",
        "phoneNumber": "9015551234"
      }
    },
    "recipients": [{
      "address": {
        "streetLines": ["456 Receiver Ave"],
        "city": "New York",
        "stateOrProvinceCode": "NY",
        "postalCode": "10001",
        "countryCode": "US"
      },
      "contact": {
        "personName": "Jane Receiver",
        "companyName": "ReceiveCorp",
        "phoneNumber": "2125555678"
      }
    }],
    "serviceType": "FEDEX_GROUND",
    "packagingType": "YOUR_PACKAGING",
    "pickupType": "USE_SCHEDULED_PICKUP",
    "blockInsightVisibility": false,
    "shippingChargesPayment": {
      "paymentType": "SENDER"
    },
    "labelSpecification": {
      "labelFormatType": "PDF",
      "labelStockType": "PAPER_4X6",
      "imageType": "PDF",
      "labelOrder": "SHIPPING_LABEL_FIRST"
    },
    "requestedPackageLineItems": [{
      "weight": {
        "units": "LB",
        "value": 10.5
      },
      "dimensions": {
        "length": 12,
        "width": 8,
        "height": 6,
        "units": "IN"
      },
      "itemDescription": "Electronics",
      "customerReferences": [{
        "customerReferenceType": "CUSTOMER_REFERENCE",
        "value": "ORDER-12345"
      }]
    }]
  },
  "accountNumber": {
    "value": "123456789"
  }
}
```

**Sample Response:**
```json
{
  "transactionId": "624deea6-b709-470c-8c39-4b5511281492",
  "output": {
    "transactionShipments": [{
      "masterTrackingNumber": "794644790300",
      "serviceType": "FEDEX_GROUND",
      "shipDatestamp": "2025-01-15",
      "packagingType": "YOUR_PACKAGING",
      "totalWeight": {
        "units": "LB",
        "value": 10.5
      },
      "completedShipmentDetail": {
        "completedPackageDetails": [{
          "sequenceNumber": 1,
          "trackingIds": [{
            "trackingIdType": "EXPRESS",
            "trackingNumber": "794644790300"
          }],
          "label": {
            "labelType": "OUTBOUND_LABEL",
            "imageType": "PDF",
            "encodedLabel": "JVBERi0xLjQKJeLjz9MKMSAwIG9iago8PC..."
          }
        }]
      },
      "shipmentRating": {
        "totalBillingWeight": {
          "units": "LB",
          "value": 11.0
        },
        "totalNetCharge": {
          "amount": 15.42,
          "currency": "USD"
        }
      }
    }]
  }
}
```

### 2. Track API (Basic Integrated Visibility)

**Purpose**: Obtain tracking information for FedEx shipments.

**Key Features:**
- Track by tracking number
- Get estimated delivery dates
- View scan events and status history

**Usage Limit:** 10,000 API calls per day

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/track/v1/trackingnumbers` | POST | Track shipments by tracking numbers |

**Event Codes:**
| Code | Description |
|------|-------------|
| AE | Shipment arriving early |
| AO | Shipment arriving on-time |
| IT | In transit |
| DE | Delivered |
| OD | Out for delivery |
| PU | Picked up |

**Sample Request:**
```json
{
  "trackingInfo": [{
    "trackingNumberInfo": {
      "trackingNumber": "794644790300"
    }
  }],
  "includeDetailedScans": true
}
```

**Sample Response:**
```json
{
  "transactionId": "39d0e5eb-0f0b-4a1b-8c0a-4f8b8e0b0e0b",
  "output": {
    "completeTrackResults": [{
      "trackingNumber": "794644790300",
      "trackResults": [{
        "trackingNumberInfo": {
          "trackingNumber": "794644790300",
          "trackingNumberUniqueId": "12024~794644790300~FDEG"
        },
        "additionalTrackingInfo": {
          "nickname": "Customer Package",
          "packageIdentifiers": [{
            "type": "CUSTOMER_REFERENCE",
            "value": "ORDER-12345"
          }]
        },
        "latestStatusDetail": {
          "code": "IT",
          "derivedCode": "IN_TRANSIT",
          "description": "In transit",
          "location": {
            "city": "Newark",
            "stateOrProvinceCode": "NJ",
            "countryCode": "US"
          }
        },
        "estimatedDeliveryTimeWindow": {
          "window": {
            "begins": "2025-01-18",
            "ends": "2025-01-18"
          }
        },
        "scanEvents": [{
          "date": "2025-01-15T10:30:00-06:00",
          "eventType": "PU",
          "eventDescription": "Picked up",
          "location": {
            "city": "Memphis",
            "stateOrProvinceCode": "TN",
            "countryCode": "US"
          }
        }, {
          "date": "2025-01-16T03:15:00-05:00",
          "eventType": "IT",
          "eventDescription": "In transit",
          "location": {
            "city": "Newark",
            "stateOrProvinceCode": "NJ",
            "countryCode": "US"
          }
        }]
      }]
    }]
  }
}
```

### 3. Pickup Request API

**Purpose**: Schedule courier pickups for shipments.

**Key Features:**
- Check pickup availability
- Schedule pickups
- Cancel scheduled pickups

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/pickup/v1/pickups/availabilities` | POST | Check pickup availability |
| `/pickup/v1/pickups` | POST | Schedule a pickup |
| `/pickup/v1/pickups/cancel` | PUT | Cancel a pickup |

**Sample Request - Schedule Pickup:**
```json
{
  "associatedAccountNumber": {
    "value": "123456789"
  },
  "originDetail": {
    "pickupAddress": {
      "streetLines": ["123 Shipper Street"],
      "city": "Memphis",
      "stateOrProvinceCode": "TN",
      "postalCode": "38118",
      "countryCode": "US"
    },
    "pickupLocationType": "HOME",
    "readyDateTimestamp": "2025-01-16T09:00:00-06:00",
    "customerCloseTime": "17:00:00",
    "pickupType": "ON_CALL"
  },
  "totalWeight": {
    "units": "LB",
    "value": 50.0
  },
  "packageCount": 5,
  "carrierCode": "FDXG",
  "countryRelationships": ["DOMESTIC"]
}
```

**Sample Response:**
```json
{
  "transactionId": "a1b2c3d4-e5f6-7890-abcd-ef1234567890",
  "output": {
    "pickupConfirmationNumber": "PU123456789012",
    "scheduledTimeBuffer": {
      "earliestTime": "09:00:00",
      "latestTime": "13:00:00"
    },
    "location": {
      "city": "Memphis",
      "stateOrProvinceCode": "TN",
      "countryCode": "US"
    },
    "message": "Your pickup has been scheduled."
  }
}
```

### 4. Rates and Transit Times API

**Purpose**: Get rate quotes and delivery estimates for shipments.

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/rate/v1/rates/quotes` | POST | Get rate quotes |
| `/rate/v1/transittimes` | POST | Get transit times |

**Sample Request - Rate Quote:**
```json
{
  "accountNumber": {
    "value": "123456789"
  },
  "requestedShipment": {
    "shipper": {
      "address": {
        "postalCode": "38118",
        "countryCode": "US"
      }
    },
    "recipient": {
      "address": {
        "postalCode": "10001",
        "countryCode": "US"
      }
    },
    "pickupType": "DROP_OFF",
    "serviceType": "FEDEX_GROUND",
    "requestedPackageLineItems": [{
      "weight": {
        "units": "LB",
        "value": 10.5
      },
      "dimensions": {
        "length": 12,
        "width": 8,
        "height": 6,
        "units": "IN"
      }
    }]
  }
}
```

**Sample Response:**
```json
{
  "transactionId": "rate-123-456",
  "output": {
    "rateReplyDetails": [{
      "serviceType": "FEDEX_GROUND",
      "serviceName": "FedEx Ground",
      "packagingType": "YOUR_PACKAGING",
      "commit": {
        "date": "2025-01-18",
        "dayOfWeek": "SAT"
      },
      "ratedShipmentDetails": [{
        "totalNetCharge": {
          "amount": 15.42,
          "currency": "USD"
        },
        "totalBillingWeight": {
          "units": "LB",
          "value": 11.0
        },
        "shipmentRateDetail": {
          "rateType": "ACCOUNT",
          "totalSurcharges": {
            "amount": 2.50,
            "currency": "USD"
          },
          "totalTaxes": {
            "amount": 0.00,
            "currency": "USD"
          }
        }
      }]
    }]
  }
}
```

### 5. Address Validation API

**Purpose**: Validate shipping addresses and determine residential vs business.

**Key Features:**
- Validate domestic and international addresses
- Classify as business or residential
- Improve rate quote accuracy

**Key Endpoints:**

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/address/v1/addresses/resolve` | POST | Validate addresses |

**Sample Request:**
```json
{
  "addressesToValidate": [{
    "address": {
      "streetLines": ["123 Main Street"],
      "city": "Memphis",
      "stateOrProvinceCode": "TN",
      "postalCode": "38118",
      "countryCode": "US"
    }
  }]
}
```

**Sample Response:**
```json
{
  "transactionId": "addr-123",
  "output": {
    "resolvedAddresses": [{
      "streetLines": ["123 MAIN ST"],
      "city": "MEMPHIS",
      "stateOrProvinceCode": "TN",
      "postalCode": "38118-1234",
      "countryCode": "US",
      "classification": "BUSINESS",
      "attributes": [{
        "name": "CountrySupported",
        "value": "true"
      }, {
        "name": "Resolved",
        "value": "true"
      }]
    }]
  }
}
```

### 6. Returns API

**Purpose**: Create and manage return shipments.

**Key Features:**
- Generate return labels
- Track return shipments
- Manage return authorizations

**Common Patterns:**
- Email return labels to customers
- Include return labels in outbound shipments
- Generate QR codes for labelless returns

---

## Error Handling

### HTTP Status Codes

| Code | Description |
|------|-------------|
| 200 | Success |
| 400 | Bad Request - Invalid request body |
| 401 | Unauthorized - Invalid credentials |
| 403 | Forbidden - Permission denied |
| 404 | Not Found - Resource unavailable |
| 409 | Conflict - Request conflict |
| 429 | Too Many Requests - Rate limit exceeded |
| 500 | Internal Server Error |
| 503 | Service Unavailable |

### Error Response Structure
```json
{
  "transactionId": "abc123",
  "errors": [{
    "code": "SHIPMENT.INVALID.REQUEST",
    "message": "Invalid ship date - cannot be in the past",
    "parameterList": [{
      "key": "shipDatestamp",
      "value": "2024-01-01"
    }]
  }]
}
```

---

## Webhooks (Advanced Integrated Visibility)

For real-time tracking updates, use webhooks instead of polling the Track API.

**Features:**
- Near real-time delivery predictions
- Track events and status changes
- Picture Proof of Delivery
- GPS coordinates of delivered packages

---

## Best Practices

1. **Token Caching**: Cache OAuth tokens for their full 1-hour validity
2. **Idempotency**: Use unique correlation IDs for retry scenarios
3. **Rate Limiting**: Implement exponential backoff for 429 errors
4. **Label Storage**: Store labels securely with proper retention policies
5. **Address Validation**: Validate addresses before creating shipments
6. **Webhooks**: Prefer webhooks over polling for tracking updates

---

## Service Types Reference

### FedEx Express
| Code | Service |
|------|---------|
| FIRST_OVERNIGHT | FedEx First Overnight |
| PRIORITY_OVERNIGHT | FedEx Priority Overnight |
| STANDARD_OVERNIGHT | FedEx Standard Overnight |
| FEDEX_2_DAY | FedEx 2Day |
| FEDEX_2_DAY_AM | FedEx 2Day AM |
| FEDEX_EXPRESS_SAVER | FedEx Express Saver |

### FedEx Ground
| Code | Service |
|------|---------|
| FEDEX_GROUND | FedEx Ground |
| GROUND_HOME_DELIVERY | FedEx Home Delivery |
| SMART_POST | FedEx Ground Economy (SmartPost) |

### FedEx International
| Code | Service |
|------|---------|
| INTERNATIONAL_FIRST | FedEx International First |
| INTERNATIONAL_PRIORITY | FedEx International Priority |
| INTERNATIONAL_ECONOMY | FedEx International Economy |
| FEDEX_INTERNATIONAL_PRIORITY_EXPRESS | FedEx International Priority Express |

---

## Packaging Types

| Code | Description |
|------|-------------|
| FEDEX_ENVELOPE | FedEx Envelope |
| FEDEX_PAK | FedEx Pak |
| FEDEX_BOX_SMALL | FedEx Small Box |
| FEDEX_BOX_MEDIUM | FedEx Medium Box |
| FEDEX_BOX_LARGE | FedEx Large Box |
| FEDEX_TUBE | FedEx Tube |
| YOUR_PACKAGING | Customer-provided packaging |

---

## References

- [FedEx Developer Portal](https://developer.fedex.com/api/en-us/home.html)
- [Ship API Documentation](https://developer.fedex.com/api/en-us/catalog/ship.html)
- [Track API Documentation](https://developer.fedex.com/api/en-us/catalog/track.html)
- [Pickup API Documentation](https://developer.fedex.com/api/en-us/catalog/pickup.html)
- [Rate API Documentation](https://developer.fedex.com/api/en-us/catalog/rate.html)
- [Address Validation API](https://developer.fedex.com/api/en-us/catalog/address-validation.html)
- [Rate Limits Guide](https://developer.fedex.com/api/en-us/guides/ratelimits.html)
- [Best Practices Guide](https://developer.fedex.com/api/en-us/guides/best-practices.html)
