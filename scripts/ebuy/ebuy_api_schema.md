# GSA eBuy API Response Schemas — Complete Field Reference

Generated from live API responses on 2026-03-25. Every field, data type, and nullable
status documented from actual data (94 MAS RFQs, 4 OASIS+8A RFQs, 274 historical quotes).

## Response Envelope

All eBuy API responses use this wrapper:

```
{ "header": { "status": int }, "response": <varies> }
```

`header.status = 0` means success. Non-zero indicates an error (e.g., `105` = contract mismatch).

---

## 1. GET /seller/activerfqs/{contractNumber}

Returns ALL active RFQs for a contract. No pagination, no filtering. Pre-sorted by closeTime desc.

**Response:** `{ "header": {...}, "response": { "<contractNumber>": [ ...rfq items ] } }`

### RFQ List Item (42 top-level fields)

| Field | Type | Nullable | Description | Example |
|---|---|---|---|---|
| `rfqId` | string | No | Opportunity ID (prefix = type: RFQ/RFI/RFP) | `"RFQ1798776"`, `"RFI1802457"` |
| `title` | string | No | Opportunity title | `"Investigative Case and Data Ecosystem"` |
| `rfqStatus` | int | No | Status code (see enum below) | `3` (Open), `4` (Cancelled) |
| `rfqStatusText` | string | No | Status display text | `"Closed"`, `"Cancelled"` |
| `userId` | string | No | Buyer's eBuy user ID | `"2730862"` |
| `agencyCode` | string | No | Federal agency code | `"15"` (DOJ), `"70"` (DHS), `"97"` (DoD) |
| `userName` | string | No | Buyer's name | `"ROBERT JONES"` |
| `userAgency` | string | No | Buyer's agency name | `"Department of Justice"` |
| `userEmail` | string | No | Buyer's email | `"robert.a.jonesjr@dea.gov"` |
| `issueTime` | epoch_ms | No | When opportunity was posted | `1772638645436` |
| `closeTime` | epoch_ms | No | Response deadline | `1778270400000` |
| `cancelTime` | epoch_ms | No | Cancel timestamp (present even on non-cancelled!) | `1772600400000` |
| `schedule` | string | No | Contract vehicle | `"MAS"`, `"OASIS+8A"` |
| `sin` | string | No | Special Item Number | `"518210C"`, `"20108"` |
| `subcategoryCode` | string | No | Sub-category code (always `"0"` in our data) | `"0"` |
| `subcategoryName` | string | No | Sub-category name (always `"0"` in our data) | `"0"` |
| `quoteStatus` | int | No | Our quote status (0 = no action) | `0`, `9` (Interested) |
| `quoteStatusText` | string | **Yes** | Quote status text (null if no quote) | `null`, `"Interested"` |
| `quoteId` | string | **Yes** | Our quote ID (null if no quote) | `null`, `"RFI1787515-IDX"` |
| `quoteOid` | int | No | Quote internal OID (0 if no quote) | `0`, `30073479` |
| `notified` | boolean | No | Whether we were notified | `false` |
| `awardCount` | int | No | Number of awards made | `0` |
| `lastRfqModVersion` | int | No | Latest amendment version (0 = no amendments) | `0`, `3` |
| `lastRfqModDate` | epoch_ms | **Yes** | Date of last amendment (null if none) | `null`, `1773979200000` |
| `qaDocumentCount` | int | No | Q&A document count | `0`, `1`, `3` |
| `watchRfqDate` | epoch_ms | **Yes** | When we started watching (null if not watching) | `null` |
| `rfq` | object | No | Nested full RFQ detail (see below) | 24 keys |
| `hideInEbuy` | boolean | No | Hidden from eBuy UI | `false` |
| `scheduleTitle` | string | **Yes** | Schedule title — **ALWAYS NULL** | `null` |
| `sinDescription1` | string | **Yes** | SIN description — **ALWAYS NULL** | `null` |
| `sinDescription2` | string | **Yes** | SIN description — **ALWAYS NULL** | `null` |
| `complimentarySinsSelected` | boolean | No | Whether complementary SINs were selected | `false` |
| `oid` | int | No | Internal OID (same as rfq.rfqInfo.oid) | `30227456` |
| `rfqCancelled` | boolean | No | Is this RFQ cancelled | `false` |
| `quoteStatusNoQuote` | boolean | No | Did we submit "no quote" | `false` |
| `quoteSaved` | boolean | No | Is our quote saved (draft) | `true` |
| `cancelTimeDate` | epoch_ms | No | Same as cancelTime (duplicate) | `1772600400000` |
| `rfqNumber` | int | No | Always `0` in our data | `0` |
| `quoted` | boolean | No | Have we submitted a quote | `false` |
| `issueTimeDate` | epoch_ms | No | Same as issueTime (duplicate) | `1772638645436` |
| `closeTimeDate` | epoch_ms | No | Same as closeTime (duplicate) | `1778270400000` |
| `cancelTimeDateFormatted` | string | **Yes** | Formatted cancel date (null for historical) | `"04/03/2026"` |

**Field coverage (94 MAS RFQs):**
- Always null: `quoteId`, `quoteStatusText`, `watchRfqDate`, `scheduleTitle`, `sinDescription1`, `sinDescription2`
- Sometimes null: `lastRfqModDate` (56/94 null = no amendments), `cancelTimeDateFormatted`
- Never null: all other 34 fields

---

## 2. Nested rfq Object (inside list item)

The `rfq` field in each list item contains 24 keys. Several sub-objects are partially
populated in the list response vs fully populated in the detail response.

### rfq.rfqInfo (46 fields)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `oid` | int | No | Internal object ID |
| `rfqId` | string | No | Same as parent rfqId |
| `title` | string | No | Same as parent title |
| `rfqDaysOpen` | int | No | Number of days open |
| `rfqShipInd` | int | No | Shipping indicator (always `1`) |
| `issueTime` | epoch_ms | No | Issue timestamp |
| `closeTime` | epoch_ms | No | Close timestamp |
| `lastModTime` | epoch_ms | No | Last modification timestamp |
| `cancelTime` | epoch_ms | No | Cancel timestamp |
| `cancelReason` | string | **Yes** | Cancellation reason (null if not cancelled) |
| `referenceNum` | string | **Yes** | External reference number (e.g., `"RFQ 15DDHQ26Q00000040"`) |
| `description` | string | No | Full description text (up to ~500 chars) |
| `deliveryDays` | int | No | Delivery days (0 for POP-based) |
| `leadTime` | string | No | Lead time type (always `"POP"` in our data) |
| `rfqPassword` | string | **Yes** | Password for accessing RFQ (null if none) |
| `sourceSought` | boolean | No | Is this a sources sought notice |
| `rfqExtended` | boolean | No | Was the deadline extended |
| `popStartDate` | epoch_ms | **Yes** | Period of performance start (null = not specified) |
| `popEndDate` | epoch_ms | **Yes** | Period of performance end |
| `quoteCount` | int | No | Total quotes received |
| `rfqHistory` | boolean | No | Has history |
| `awardNote` | string | **Yes** | Award note text |
| `userId` | string | No | Buyer user ID |
| `rfqStatus` | int | No | Status code |
| `serviceType` | object | No | `{value: int, enumClass: string, name: string}` |
| `serviceType.value` | int | No | `0` = Schedule (MAS), `5` = IDIQ (OASIS+) |
| `serviceType.name` | string | No | `"Schedule"` or `"IDIQ"` |
| `overseas` | boolean | No | Overseas requirement |
| `source` | string | **Yes** | Source (always null) |
| `rfqProgramsList` | array | **Yes** | Programs list (null or empty) |
| `closeDate` | epoch_ms | No | Same as closeTime (duplicate) |
| `closeHour` | int | No | Close hour (e.g., `16`) |
| `closeHourAmPm` | string | No | `"am"` or `"pm"` |
| `validationErrors` | object | No | Empty `{}` |
| `valid` | boolean | No | Validation status |
| `awardCount` | int | No | Number of awards |
| `requestType` | int | No | **UNRELIABLE** — use rfqId prefix instead. `0` or `1` for RFQ, `2` for RFI, `3` for RFP |
| `rfqOpen` | boolean | No | Is currently open |
| `rfqClosed` | boolean | No | Is closed |
| `issueTimeDate` | epoch_ms | No | Duplicate of issueTime |
| `closeTimeDate` | epoch_ms | No | Duplicate of closeTime |
| `gwac` | boolean | No | Is GWAC |
| `rfqStatusDescription` | string | No | `"Open"`, `"Closed"` |
| `cancelTimeDate` | epoch_ms | No | Duplicate of cancelTime |
| `rfqSubmitted` | boolean | No | Was submitted by buyer |
| `rfqSaved` | boolean | No | Is saved (draft) |
| `connectRfq` | boolean | No | Is eBuy Connect RFQ |
| `connectAwardableRfq` | boolean | No | Is awardable via Connect |

> **WARNING**: `requestType` is inconsistent between list and detail responses. Active RFQs
> show `requestType=1`, but historical quotes for the SAME rfqId show `requestType=0`.
> **Always derive request type from the rfqId prefix** (RFQ/RFI/RFP), not from this field.

### rfq.rfqAdditionalInfo (18 fields)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | int | No | Always `0` |
| `followOnRequirement` | string | No | `"Y"` or `"N"` |
| `historicalTaskOrderNumber` | string | **Yes** | Historical TO number |
| `isRfiPosted` | string | No | `"Y"` or `"N"` — was RFI posted for this |
| `rfiDetails` | string | **Yes** | RFI details text |
| `commercialType` | string | No | `"C"` (commercial) or `"N"` (non-commercial) |
| `contractType` | string | No | `"firm-fixed-price"`, `"time-materials"` |
| `awardMethod` | string | No | `"best-value"`, `"lowest-price"` |
| `ocoName` | string | No | Ordering Contracting Officer name |
| `ocoTitle` | string | No | OCO title (e.g., `"Contracting Officer"`) |
| `ocoAgency` | string | No | OCO agency (e.g., `"Drug Enforcement Administration"`) |
| `ocoPhone` | string | No | OCO phone (may be `" "` = blank) |
| `ocoAacCode` | string | No | OCO AAC code (e.g., `"H92400"`) |
| `ocsName` | string | No | Contract Specialist name |
| `ocsTitle` | string | No | OCS title |
| `ocsAgency` | string | No | OCS agency |
| `ocsPhone` | string | No | OCS phone |
| `ocsAacCode` | string | No | OCS AAC code |

### rfq.rfqProps (19 fields) — Buyer Details

| Field | Type | Nullable | Description |
|---|---|---|---|
| `userAgencyCode` | string | **Yes** | Agency code (null in list, populated in detail) |
| `userName` | string | **Yes** | Buyer name |
| `userAgency` | string | **Yes** | Agency name |
| `userBureau` | string | **Yes** | Bureau name |
| `userOrgLevel1Name` | string | **Yes** | Org level 1 (always null) |
| `userOrgLevel2Name` | string | **Yes** | Org level 2 (always null) |
| `userEmail` | string | **Yes** | Buyer email |
| `userPhone` | string | **Yes** | Buyer phone |
| `numberOfAwards` | int | No | Award count |
| `quoteCount` | int | No | Quote count |
| `awardNote` | string | **Yes** | Award note |
| `vendorCount` | int | No | Vendor count |
| `recoveryPurchase` | boolean | No | Recovery Act purchase |
| `forwardEmailId` | string | **Yes** | Forwarded email ID |
| `forwardComments` | string | **Yes** | Forward comments |
| `setAsideBusinessIndicator` | string | **Yes** | Set-aside indicator |
| `os3` | boolean | No | OS3 flag |
| `rfqMetricsOid` | int | **Yes** | Metrics OID |
| `rfqProgramSelected` | string | **Yes** | Selected program |

> **NOTE**: `rfqProps` fields are mostly null in the list response. They are populated
> in the detail response (`GET /seller/rfq/{rfqId}/{contract}`).

---

## 3. GET /seller/rfq/{rfqId}/{contractNumber} — Detail Response

Same structure as nested `rfq` object, but with fully populated sub-objects.

### response.rfqAttachments[] (7 fields per attachment)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `docName` | string | No | Display filename | `"02 S-TRIG SOW.docx"` |
| `docPath` | string | No | Server path for download | `"/ebuy_upload/202603/..."` |
| `docSeqNum` | int | No | Sequence number (unique per attachment) | `3614836` |
| `docType` | int | No | Document type code (always `0` in our data) | `0` |
| `docSessionId` | int | No | Session ID (always `0`) | `0` |
| `docSessionDate` | epoch_ms | No | Upload timestamp | `1774297190577` |
| `seqNum` | int | No | Same as docSeqNum (duplicate) | `3614836` |

### response.rfqModifications[] (4 fields per modification)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `versionNumber` | int | No | Amendment version (1, 2, 3...) | `1` |
| `modificationNote` | string | No | Amendment description text | `"The purpose of this Amendment..."` |
| `modificationTime` | epoch_ms | No | When amendment was issued | `1774373764706` |
| `amendIdentifier` | string | **Yes** | Amendment identifier (always null in our data) | `null` |

### response.rfqCategories[] (16 fields per category)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `schedule` | string | No | Contract vehicle | `"OASIS+8A"` |
| `sin` | string | No | Special Item Number | `"20108"` |
| `subCategory` | int | No | Sub-category code | `0` |
| `subCategoryDescription` | string | **Yes** | Sub-category description | `null` |
| `categoryId` | string | No | Composite key | `"OASIS+8A:20108"` |
| `categoryDescription` | string | **Yes** | Category description | `null` |
| `vendorCount` | int | No | Number of invited vendors | `258` |
| `rfqVendors` | array | No | List of invited vendors (see below) | |
| `alreadyExists` | boolean | No | | `true` |
| `validationErrors` | object | No | Empty `{}` | |
| `valid` | boolean | No | | `true` |
| `hideInEbuy` | boolean | No | | `false` |
| `scheduleTitle` | string | **Yes** | Always null | `null` |
| `sinDescription1` | string | **Yes** | Always null | `null` |
| `sinDescription2` | string | **Yes** | Always null | `null` |
| `scheduleTypeId` | int | No | | `0` |

### rfqCategories[].rfqVendors[] — Competitor List (11 fields)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `categoryId` | string | No | Parent category | `"OASIS+8A:20108"` |
| `contractNum` | string | No | Vendor's contract number | `"47QRCA25DA081"` |
| `schedule` | string | No | Vehicle | `"OASIS+8A"` |
| `sin` | string | No | SIN | `"20108"` |
| `subCategory` | int | No | Sub-category | `0` |
| `email` | string | No | Vendor contact email | `"jwhitlow@amivero.com"` |
| `vendorCategoryKey` | string | No | Composite key | `"47QRCA25DA081#20108#"` |
| `companyName` | string | **Yes** | Company name (null for some vendors) | `"AMIVERO LLC"` |
| `otherCategories` | string | No | Other categories (usually empty `""`) | `""` |
| `contractCloseDate` | epoch_ms | **Yes** | Contract expiration | `null` |
| `arravendor` | boolean | No | ARRA vendor flag | `false` |

### response.rfqLineItems[] — CLINs (18 fields, IDIQ only)

Only populated for IDIQ/OASIS+ opportunities. Empty for MAS/Schedule.

| Field | Type | Nullable | Description |
|---|---|---|---|
| `manufactureName` | string | No | Period label | `"Base Year"`, `"Option Year 1"` |
| `manufacturePartNum` | string | No | CLIN number | `"0001"`, `"1001"` |
| `productDescription` | string | No | Line item description | `"Time and Materials"` |
| `quantity` | int | No | Quantity | `1` |
| `unit` | string | No | Unit of measure | `"LT"` (Lot), `"CO"` (Cost) |
| `price` | float | No | Price (0.0 for RFPs — vendor fills in) | `0.0` |
| `addressIndex` | int | No | Delivery address index | `1` |
| `rfqItemId` | string | No | Item ID | `"1"`, `"2"` |
| `quoteItemId` | string | **Yes** | Our quote item ID | `null` |
| `awarded` | boolean | **Yes** | Whether this CLIN was awarded | `null` |
| `fromRfq` | boolean | No | | `false` |
| `displayed` | boolean | No | | `false` |
| `referenceItemId` | string | **Yes** | Reference item | `null` |
| `validationErrors` | object | No | | `{}` |
| `valid` | boolean | No | | `true` |
| `selected` | boolean | No | | `true` |
| `deleted` | boolean | No | | `false` |
| `quoted` | boolean | No | Whether we quoted this CLIN | `false` |

### response.rfqAddresses[] — Place of Performance (34 fields)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `addressType` | string | No | `"D"` (delivery) |
| `addressName` | string | No | Location name | `"HQ USSOCOM"`, `"DEA"` |
| `agencyName` | string | No | Agency at this address | `"SOCS-SOOR"` |
| `addressLine1` | string | No | Street | `"7701 Tampa Point Blvd"` |
| `addressLine2` | string | **Yes** | | `null` |
| `city` | string | No | City | `"Tampa"`, `"Arlington"` |
| `state` | string | No | State | `"FL"`, `"VA"` |
| `zip` | string | No | ZIP code | `"33621"` |
| `country` | string | No | Country (empty string = USA) | `""` |
| `irsData` | object | No | Point of contact at this address | |
| `irsData.name` | string | No | Contact name | `"Sherri Ashby"` |
| `irsData.email` | string | No | Contact email | `"sherri.ashby@socom.mil"` |
| `irsData.phone` | string | No | Contact phone | `"813-597-9971"` |
| `dodAAC` | string | **Yes** | DoD Activity Address Code | `null` |
| `shippingAacId` | string | **Yes** | Shipping AAC | `null` |
| `addressId` | int | No | Address index | `1` |
| (+ 18 more fields) | various | various | Validation, billing, freight flags |

### response top-level flags (boolean)

| Field | Type | Description |
|---|---|---|
| `mas` | boolean | Is MAS/Schedule opportunity |
| `idiq` | boolean | Is IDIQ (OASIS+) opportunity |
| `bpa` | boolean | Is BPA |
| `gwac` | boolean | Is GWAC |
| `nst` | boolean | Is non-standard |

---

## 4. GET /seller/notifications/{contractNumber}

**Response:** `{ "header": {...}, "response": { "<contractNumber>": [ ...notifications ] } }`

### Notification (5 fields)

| Field | Type | Nullable | Description |
|---|---|---|---|
| `id` | string | No | RFQ/RFI/RFP ID | `"RFI1802458"` |
| `issueTime` | epoch_ms | No | Original issue timestamp | `1774388434360` |
| `scheduleNumber` | string | No | Schedule/vehicle | `"MAS"`, `"OASIS+8A"` |
| `messageType` | string | No | Event type (see below) | `"Quote Requested"` |
| `calendar` | epoch_ms | No | Event timestamp (may differ from issueTime for amendments) | `1774388434360` |

**messageType values observed:**

| messageType | Meaning | Count (MAS) | Count (OASIS+8A) |
|---|---|---|---|
| `Quote Requested` | New opportunity posted | 33 | 2 |
| `modified` | Opportunity amended | 3 | 1 |
| `cancelled` | Opportunity cancelled | 1 | 1 |

---

## 5. POST /seller/searchactiverfqs

**Request:**
```json
{
  "contractnumber": "47QTCA20D001V",
  "query": "artificial intelligence",
  "matchtype": 1,
  "sortspec": "CloseDate dsc"
}
```

**Response:** `{ "header": {...}, "response": { "suggestedKeyword": "", "rfqList": { "<contract>": [...] } } }`

RFQ items in the `rfqList` have the **same schema** as `activerfqs` list items (42 fields).

Empty query returns `null` for the contract key (not an empty array).

---

## 6. GET /seller/getquotes/h/{contractNumber} — Historical Quotes

Same response structure as `activerfqs`: `{ "response": { "<contract>": [...] } }`

Items have the **same 42-field schema** as active RFQ list items, but with populated quote fields:

| Field | Notes (vs activerfqs) |
|---|---|
| `quoteStatus` | Populated: `9` (Interested), `2` (Saved), `3` (Submitted), etc. |
| `quoteStatusText` | Populated: `"Interested"`, `"No Quote"`, `"Awarded"`, `"Pending Response"` |
| `quoteId` | Populated: `"RFI1787515-IDX"` (format: `{rfqId}-{suffix}`) |
| `quoteOid` | Non-zero when quote exists |
| `cancelTime` | **NULL** for non-cancelled historical items (unlike activerfqs where it's always present) |

**Quote status distribution (274 MAS historical):**

| Status | Count |
|---|---|
| No Quote | 242 |
| Interested | 18 |
| Pending Response | 5 |
| Sources Sought | 3 |
| Saved to Draft | 2 |
| Not Awarded | 2 |
| Cancelled | 1 |
| Awarded | 1 |

---

## 7. GET /seller/rfqawardinfo/{rfqId}/{contractNumber}

**Response:** `{ "header": { "status": 0 }, "response": null }`

Returns `null` when no award has been made. Schema TBD when an awarded RFQ is available.

---

## 8. Cross-Contract Analysis

| Metric | MAS (47QTCA20D001V) | OASIS+8A (47QRCA25DA081) |
|---|---|---|
| Active RFQs | 94 | 4 |
| Historical quotes | 274 | 3 |
| Notifications | 37 | 4 |
| SINs seen | 518210C, 54151HACS, 54151S, 541611 | 20101, 20106, 20108, 20205 |
| Request types | RFQ (88), RFI (4), RFP (2) | RFI (2), RFP (2) |
| Cross-contract overlap | 0 rfqIds shared | 0 rfqIds shared |
| serviceType | Schedule (value=0) | IDIQ (value=5) |
| rfqLineItems | Always empty | 12 CLINs (S-TRIG) |

---

## 9. Key Data Integrity Notes

1. **requestType is unreliable** — active list shows `1` for RFQs, historical shows `0` for the same prefix. **Derive from rfqId prefix.**
2. **cancelTime is always populated in activerfqs** even for non-cancelled items. Not meaningful unless `rfqCancelled=true`.
3. **Duplicate date fields** — `issueTime`/`issueTimeDate`, `closeTime`/`closeTimeDate`, `cancelTime`/`cancelTimeDate` are identical. Use the shorter names.
4. **scheduleTitle, sinDescription1, sinDescription2** are always `null` — not populated by the API.
5. **rfqProps** fields are mostly null in list responses, only populated in detail responses.
6. **rfq.rfqInfo.rfqPassword** — some RFQs have passwords (e.g., `"newICDErequirement"`, `"KHAOS"`). May be needed for attachment access.
7. **companyName in rfqVendors** can be `null` for some vendors.
