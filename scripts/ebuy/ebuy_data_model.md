# GSA eBuy Data Model & Sync Design

## Overview

This document defines the database models, sync configuration, and search integration
for the GSA eBuy connector, following the established SAM.gov connector architecture.

## Mapping: eBuy Concepts → SAM.gov Equivalents

| eBuy Concept | SAM.gov Equivalent | Notes |
|---|---|---|
| RFQ/RFP/RFI (opportunity) | SamSolicitation | Top-level procurement opportunity |
| Notifications | SamNotice | Alerts about new/modified opportunities |
| Modifications (amendments) | SamNotice (versioned) | Tracked via `rfqModifications[]` |
| Attachments (SOWs, etc.) | SamAttachment | Documents attached to an opportunity |
| Quotes (vendor responses) | (no equivalent) | eBuy-specific — vendor bid tracking |
| Contracts (MAS, OASIS+, etc.) | (no equivalent) | eBuy-specific — JWT is scoped per contract |

## Key Architectural Differences from SAM.gov

| Aspect | SAM.gov | eBuy |
|---|---|---|
| Authentication | Static API key | Okta 2FA → OIDC PKCE → eBuy JWT |
| Token scope | Global | Per-contract (need JWT per contract) |
| Token lifetime | Indefinite | ~30 min (Okta access token: 1 hour) |
| API style | Public REST API | Authenticated SPA backend |
| Pagination | Server-side (pageNumber/pageSize) | Client-side (full result set returned) |
| Rate limiting | 1,000 calls/day | Unknown — treat conservatively |
| Opportunity ID format | notice_id (UUID) | rfqId (e.g., RFQ1798776, RFI1802457) |
| Classification | NAICS + PSC + set-aside | Schedule + SIN (Special Item Number) |
| Agency hierarchy | fullParentPathName | agencyCode + userAgency + bureau (from rfqAdditionalInfo) |
| Attachments | Direct download URL | POST with FormData (docPath + fileName) |

## Data Models

### EbuySyncConfig (equivalent to SamSyncConfig)

Defines which opportunities to sync and how often.

```python
class EbuySyncConfig(Base):
    __tablename__ = "ebuy_sync_configs"

    id: UUID
    organization_id: UUID (FK → organizations)
    name: str                          # e.g., "MAS IT Opportunities"
    slug: str                          # e.g., "mas-it-opportunities"

    # Sync filters
    sync_config: JSONB                 # Filter configuration (see below)
    contract_numbers: list[str]        # Contracts to sync (e.g., ["47QTCA20D001V", "47QRCA25DA081"])

    # Sync schedule
    sync_frequency: str                # manual, hourly, daily
    is_active: bool
    status: str                        # active, paused, archived

    # Tracking
    last_sync_at: datetime
    last_sync_status: str
    last_sync_run_id: UUID

    # Automation
    automation_config: JSONB           # before/after procedure triggers
```

**sync_config JSONB structure:**
```json
{
  "schedules": ["MAS", "OASIS+8A"],
  "sins": ["518210C", "541611"],
  "keywords": ["AI", "machine learning"],
  "agencies": ["Department of Defense"],
  "include_rfis": true,
  "include_rfqs": true,
  "include_rfps": true,
  "min_days_open": 0
}
```

### EbuyOpportunity (equivalent to SamSolicitation)

Top-level procurement opportunity (RFQ, RFI, or RFP).

```python
class EbuyOpportunity(Base):
    __tablename__ = "ebuy_opportunities"

    id: UUID
    organization_id: UUID (FK → organizations)

    # eBuy identifiers
    rfq_id: str (unique)               # "RFQ1798776", "RFI1802457", "RFP1796687"
    oid: int                           # eBuy internal OID (e.g., 30227456)
    reference_num: str                 # External ref (e.g., "RFQ 15DDHQ26Q00000040")

    # Content
    title: str
    description: str
    request_type: str                  # "RFQ", "RFI", "RFP" (derived from rfqId prefix)

    # Classification
    schedule: str                      # "MAS", "OASIS+8A", etc.
    sin: str                           # Special Item Number (e.g., "518210C", "20108")
    service_type: str                  # From ServiceTypeEnum: "Schedule" (MAS) or "IDIQ" (OASIS+)
    service_type_code: int             # Raw enum value (0=Schedule, 5=IDIQ)
    request_type_code: int             # Raw requestType (1=RFQ, 3=RFP; RFI TBD)

    # Agency / Buyer info
    agency_code: str                   # "15" (DOJ), "70" (DHS), etc.
    agency_name: str                   # "Department of Justice"
    bureau_name: str                   # "Drug Enforcement Administration"
    buyer_name: str                    # "ROBERT JONES"
    buyer_email: str                   # "robert.a.jonesjr@dea.gov"

    # Contracting officer (from rfqAdditionalInfo)
    oco_name: str                      # Ordering Contracting Officer
    oco_title: str                     # e.g., "Contracting Officer"
    oco_agency: str                    # e.g., "HQ USSOCOM"
    oco_phone: str
    oco_aac_code: str                  # AAC code (e.g., "H92400")
    ocs_name: str                      # Contract Specialist
    ocs_title: str                     # e.g., "Senior Contract Specialist"
    ocs_agency: str
    ocs_phone: str
    ocs_aac_code: str                  # AAC code

    # Place of performance (from rfqAddresses)
    performance_address: JSONB         # {addressName, agencyName, addressLine1, city, state, zip, country}

    # Dates (stored as datetime, converted from epoch ms)
    issue_date: datetime               # When posted
    close_date: datetime               # Response deadline
    cancel_date: datetime              # Cancellation date (if any)
    pop_start_date: datetime           # Period of performance start
    pop_end_date: datetime             # Period of performance end
    last_mod_date: datetime            # Last modification

    # Status
    status: str                        # open, closed, cancelled, awarded
    rfq_status: int                    # Raw eBuy status code (1=Open, 2=Closed, 3=Open, 4=Cancelled)
    rfq_status_description: str        # "Open", "Closed", "Cancelled"
    days_open: int                     # rfqDaysOpen

    # Contract details (from rfqAdditionalInfo)
    contract_type: str                 # "firm-fixed-price", "time-and-materials", etc.
    award_method: str                  # "best-value", "lowest-price"
    commercial_type: str               # "C" (commercial)
    is_follow_on: bool                 # followOnRequirement == "Y"
    is_source_sought: bool             # sourceSought
    is_overseas: bool                  # overseas

    # Counts
    attachment_count: int
    modification_count: int            # Number of amendments
    award_count: int
    quote_count: int

    # Password (some RFQs require a password)
    rfq_password: str                  # Stored for automated access

    # Raw data
    raw_data: JSONB                    # Full API response

    # Sync tracking
    source_contract: str               # Which contract number this was synced from
    discovered_at: datetime            # When first seen by sync
    last_synced_at: datetime           # Last sync check

    # Search integration
    indexed_at: datetime
    source_metadata: JSONB             # For search/entity fields

    # AI summary
    summary_status: str                # pending, generating, ready, failed
    summary_generated_at: datetime
```

### EbuyModification (equivalent to SamNotice — version tracking)

Tracks amendments/modifications to an opportunity.

```python
class EbuyModification(Base):
    __tablename__ = "ebuy_modifications"

    id: UUID
    opportunity_id: UUID (FK → ebuy_opportunities)
    organization_id: UUID (FK → organizations)

    version_number: int                # 1, 2, 3...
    modification_note: str             # Amendment description text
    modification_date: datetime        # When the amendment was issued
    amend_identifier: str              # Amendment ID (if any)

    # Search integration
    indexed_at: datetime
    source_metadata: JSONB
```

### EbuyAttachment (equivalent to SamAttachment)

Documents attached to an opportunity (SOWs, amendments, Q&As, etc.).

```python
class EbuyAttachment(Base):
    __tablename__ = "ebuy_attachments"

    id: UUID
    opportunity_id: UUID (FK → ebuy_opportunities)
    organization_id: UUID (FK → organizations)
    asset_id: UUID (FK → assets, nullable)

    # File info
    doc_name: str                      # "Attachment 2_ICDE Minimum Requirements_Final_v1.0.pdf"
    doc_path: str                      # "/ebuy_upload/202603/RFQ1798776/FalndjH2/..."
    doc_seq_num: int                   # eBuy sequence number
    doc_type: int                      # eBuy doc type code
    doc_session_date: int              # Upload timestamp (epoch ms)

    # Download tracking
    download_status: str               # pending, downloading, downloaded, failed, skipped
    downloaded_at: datetime
    download_error: str
```

### EbuyQuote (eBuy-specific — no SAM.gov equivalent)

Tracks vendor quote/bid responses to opportunities.

```python
class EbuyQuote(Base):
    __tablename__ = "ebuy_quotes"

    id: UUID
    opportunity_id: UUID (FK → ebuy_opportunities)
    organization_id: UUID (FK → organizations)

    # Quote info
    quote_id: str                      # "RFQ1798776-47QTCA20D001V"
    quote_oid: int                     # eBuy internal OID
    contract_number: str               # Which contract this quote is under

    # Status
    quote_status: int                  # 0=Draft, 2=Saved, 3=Submitted, etc.
    quote_status_text: str             # "Interested", "Submitted", "Awarded", etc.

    # Tracking
    submitted_at: datetime
    awarded_at: datetime

    # Raw data
    raw_data: JSONB
```

## API Endpoints Used by Sync

### Search & Filtering (Verified)

**Both list endpoints work:**

1. **`GET /seller/activerfqs/{contract}`** — returns ALL active RFQs (~94 on MAS). No filtering.
2. **`POST /seller/searchactiverfqs`** — server-side text search with sort. Works with `application/json`.

**searchactiverfqs request:**
```json
{
  "contractnumber": "47QTCA20D001V",
  "query": "artificial intelligence",
  "matchtype": 1,
  "sortspec": "CloseDate dsc"
}
```

> **Critical**: `matchtype` must be an **integer**, not a string. Using a string causes 500 errors.

**searchactiverfqs response:**
```json
{
  "header": { "status": 0 },
  "response": {
    "suggestedKeyword": "",
    "rfqList": {
      "47QTCA20D001V": [ ...rfq items (same shape as activerfqs)... ]
    }
  }
}
```

**matchtype values:**

| matchtype | Behavior | `IT support` results |
|---|---|---|
| 0 | Match any word | 92 (broadest) |
| 1 | Match any word | 92 (same as 0) |
| 2 | Match exact phrase | 13 (most restrictive) |
| 3 | Match any word | 92 (same as 0) |

**sortspec values (all verified):**

| sortspec | Description |
|---|---|
| `CloseDate dsc` | Most recent closing first |
| `CloseDate asc` | Earliest closing first |
| `IssueDate dsc` | Most recently posted first |
| `Title asc` | Alphabetical by title |

**Search behavior:**
- Searches across title AND description
- Empty query returns null (no results)
- No server-side date filtering — must filter client-side on `issueTime`/`closeTime`
- No pagination — all matching results returned at once
- `suggestedKeyword` field exists but appears to always be empty

**Implication for sync**: Use `activerfqs` for full sync (complete dataset). Use
`searchactiverfqs` for targeted queries (e.g., CWR procedures that search by keyword).

### Date Fields Available for Client-Side Filtering

All dates are epoch milliseconds. Coverage from 94 MAS RFQs:

| Field | Coverage | Range | Description |
|---|---|---|---|
| `issueTime` | 94/94 | 2025-12-15 → 2026-03-24 | When opportunity was posted |
| `closeTime` | 94/94 | 2026-03-20 → 2026-05-08 | Response deadline |
| `cancelTime` | 94/94 | 2025-12-09 → 2026-03-24 | When cancelled (present even on non-cancelled) |
| `lastRfqModDate` | 38/94 | 2026-01-22 → 2026-03-24 | Last amendment date (null if no mods) |
| `rfq.rfqInfo.popStartDate` | 40/94 | 2026-03-29 → 2027-04-17 | Period of performance start |
| `rfq.rfqInfo.popEndDate` | 40/94 | 2026-08-14 → 2033-06-17 | Period of performance end |

### Primary Sync Endpoints

| Priority | Endpoint | Method | Purpose | Data Yielded |
|---|---|---|---|---|
| P0 | `/seller/activerfqs/{contract}` | GET | List all active opportunities (full set, no pagination) | EbuyOpportunity (list) |
| P0 | `/seller/rfq/{rfqId}/{contract}` | GET | Full opportunity detail | EbuyOpportunity (detail), EbuyAttachment, EbuyModification |
| P1 | `/seller/notifications/{contract}` | GET | Lightweight "what's new" alerts | Trigger for detail fetch |
| P1 | `/seller/getquotes/a/{contract}` | GET | Active quotes | EbuyQuote (list) |
| P2 | `/seller/getquotes/h/{contract}` | GET | Historical quotes | EbuyQuote (archive) |
| P2 | `/rfq/{rfqId}/rfqAttachment/` | POST | Download attachment | EbuyAttachment → Asset |
| P1 | `/seller/searchactiverfqs` | POST | Text search with sort (matchtype=int!) | Filtered EbuyOpportunity list |

### Sync Flow

```
1. AUTH: Okta 2FA → OIDC PKCE → Okta access token
   │
2. FOR EACH contract in sync_config.contract_numbers:
   │
   ├─ GET /seller/getuser (with oktatoken + contractnumber) → eBuy JWT
   │
   ├─ GET /seller/activerfqs/{contract} → list of active RFQs
   │  │
   │  ├─ FOR EACH RFQ in list:
   │  │  │
   │  │  ├─ Check if EbuyOpportunity exists (by rfq_id)
   │  │  │  ├─ If new: CREATE with list-level data
   │  │  │  └─ If exists: check lastModTime for updates
   │  │  │
   │  │  ├─ GET /seller/rfq/{rfqId}/{contract} → full detail
   │  │  │  ├─ UPDATE EbuyOpportunity with detail fields
   │  │  │  ├─ CREATE/UPDATE EbuyModification for each amendment
   │  │  │  └─ CREATE EbuyAttachment for each attachment
   │  │  │
   │  │  ├─ INDEX to search (EbuyOpportunityBuilder)
   │  │  │
   │  │  └─ QUEUE attachment downloads (if enabled)
   │  │
   │  └─ GET /seller/getquotes/a/{contract} → active quotes
   │     └─ CREATE/UPDATE EbuyQuote for each
   │
   └─ NEXT contract (requires new JWT via getuser)
   │
3. POST-SYNC: Run automation procedures (e.g., ebuy_daily_digest)
```

## Enums & Mappings

### RFQ Status Mapping

| rfqStatus (int) | rfqStatusDescription | Curatore status |
|---|---|---|
| 1 | Open | active |
| 2 | Closed | closed |
| 3 | Open | active |
| 4 | Cancelled | cancelled |
| (awarded) | (from awardCount > 0) | awarded |

### Request Type Mapping

Derived from rfqId prefix AND `requestType` code:

| Prefix | requestType (int) | Type | Description |
|---|---|---|---|
| RFQ | 1 | Request for Quote | Formal solicitation for pricing |
| RFI | (TBD) | Request for Information | Market research / capability query |
| RFP | 3 | Request for Proposal | Formal proposal solicitation |

### Service Type Enum (`gov.gsa.ebuy.model.ServiceTypeEnum`)

| value | name | Description |
|---|---|---|
| 0 | Schedule | MAS (Multiple Award Schedule) |
| 5 | IDIQ | OASIS+, OASIS+8A, etc. |

### Notification Message Types

| messageType | Description |
|---|---|
| `Quote Requested` | New opportunity posted |
| `modified` | Existing opportunity amended |
| `cancelled` | Opportunity cancelled |

### Quote Status Codes

| Code | Text | Description |
|---|---|---|
| 0 | (none) | No quote action taken |
| 2 | Saved | Quote saved as draft |
| 3 | Submitted | Quote submitted |
| 7 | (varies) | Additional status |
| 9 | Interested | Vendor expressed interest |

## Detailed Response Shapes

### RFQ Detail — rfqLineItems (CLINs)

IDIQ/OASIS+ RFPs include pricing line items (CLINs). MAS RFQs typically have empty `rfqLineItems`.

```json
{
  "manufactureName": "Base Year",
  "manufacturePartNum": "0001",
  "productDescription": "Time and Materials",
  "quantity": 1,
  "unit": "LT",
  "price": 0.0,
  "rfqItemId": "1",
  "awarded": null,
  "selected": true,
  "deleted": false,
  "quoted": false
}
```

`manufactureName` = period label (Base Year, Option Year 1-4, 6 month Option 52.217-8).
`unit` = LT (Lot), CO (Cost).

### RFQ Detail — rfqAddresses (Place of Performance)

```json
{
  "addressType": "D",
  "addressName": "HQ USSOCOM",
  "agencyName": "SOCS-SOOR",
  "addressLine1": "7701 Tampa Point Blvd",
  "city": "Tampa",
  "state": "FL",
  "zip": "33621",
  "dodAAC": null,
  "irsData": {
    "name": "Sherri Ashby",
    "email": "sherri.ashby@socom.mil",
    "phone": "813-597-9971"
  }
}
```

### RFQ Detail — rfqCategories (with Competitor List)

The `rfqVendors` array within each category contains **all contract holders invited to the RFQ** — a complete competitor list with company names and emails.

```json
{
  "schedule": "OASIS+8A",
  "sin": "20108",
  "categoryId": "OASIS+8A:20108",
  "vendorCount": 258,
  "rfqVendors": [
    {
      "contractNum": "47QRCA25DA081",
      "companyName": "AMIVERO LLC",
      "email": "jwhitlow@amivero.com",
      "vendorCategoryKey": "47QRCA25DA081#20108#"
    }
  ]
}
```

> **Competitive Intelligence**: This data shows every vendor invited to bid on an opportunity — valuable for BD pipeline analysis.

### Notifications

```json
{
  "id": "RFI1802458",
  "issueTime": 1774388434360,
  "scheduleNumber": "OASIS+8A",
  "messageType": "Quote Requested",
  "calendar": 1774388434360
}
```

Response is keyed by contract number: `{ "47QRCA25DA081": [ ...notifications ] }`

### Top-Level Response Flags

The RFQ detail response includes boolean flags at the top level:

| Flag | Description |
|---|---|
| `mas` | true if MAS/Schedule opportunity |
| `idiq` | true if IDIQ (OASIS+) opportunity |
| `bpa` | true if BPA (Blanket Purchase Agreement) |
| `gwac` | true if GWAC |
| `nst` | true if Non-Standard |

## Search Integration

### Content Type Registration

```yaml
# app/metadata/registry/fields/ebuy.yaml
ebuy_opportunity:
  namespace: ebuy
  fields:
    rfq_id:
      data_type: string
      indexed: true
      facetable: false
    request_type:
      data_type: string
      indexed: true
      facetable: true           # RFQ, RFI, RFP
    schedule:
      data_type: string
      indexed: true
      facetable: true           # MAS, OASIS+8A, etc.
    sin:
      data_type: string
      indexed: true
      facetable: true           # Special Item Number
    agency_name:
      data_type: string
      indexed: true
      facetable: true
    bureau_name:
      data_type: string
      indexed: true
      facetable: true
    status:
      data_type: string
      indexed: true
      facetable: true           # active, closed, cancelled, awarded
    contract_type:
      data_type: string
      indexed: true
      facetable: true           # firm-fixed-price, T&M, etc.
    award_method:
      data_type: string
      indexed: true
      facetable: true           # best-value, lowest-price
    issue_date:
      data_type: date
      indexed: true
      facetable: false
    close_date:
      data_type: date
      indexed: true
      facetable: false
    source_contract:
      data_type: string
      indexed: true
      facetable: true           # Which Amivero contract saw this
    modification_count:
      data_type: number
      indexed: true
    attachment_count:
      data_type: number
      indexed: true
    source_url:
      data_type: string
      indexed: true
```

### Metadata Builder

```python
class EbuyOpportunityBuilder:
    source_type = "ebuy_opportunity"
    namespace = "ebuy"

    def build_content(self, opportunity):
        # Searchable text content
        return f"{opportunity.agency_name}\n\n{opportunity.title}\n\n{opportunity.description}"

    def build_metadata(self, opportunity):
        return {
            "ebuy": {
                "rfq_id": opportunity.rfq_id,
                "request_type": opportunity.request_type,
                "schedule": opportunity.schedule,
                "sin": opportunity.sin,
                "agency_name": opportunity.agency_name,
                "bureau_name": opportunity.bureau_name,
                "status": opportunity.status,
                "contract_type": opportunity.contract_type,
                "award_method": opportunity.award_method,
                "issue_date": opportunity.issue_date,
                "close_date": opportunity.close_date,
                "source_contract": opportunity.source_contract,
                "modification_count": opportunity.modification_count,
                "attachment_count": opportunity.attachment_count,
                "source_url": f"https://www.ebuy.gsa.gov/ebuy/seller/prepare-quote/{opportunity.rfq_id}",
            },
            "ontology": {
                "agency": opportunity.agency_name,
                "office": opportunity.bureau_name,
            },
        }
```

### Ontology Mapping

| eBuy Field | Ontology Field |
|---|---|
| agency_name | ontology.agency |
| bureau_name | ontology.office |
| sin | ontology.psc_codes (approximate mapping TBD) |
| schedule | (new field or custom) |

## Contract Configuration (Required for Sync Setup)

The eBuy sync MUST define which GSA contracts to sync. Each contract has its own
opportunity pool, SIN list, and JWT scope. This is configured at the sync config level.

### Available Contracts (Amivero)

```python
CONTRACTS = [
    "47QTCA20D001V",  # MAS - AMIVERO LLC
    "47QTCA24D000Z",  # MAS - STELLA JV, LLC
    "47QRCA25DA081",  # OASIS+8A - AMIVERO LLC
    "47QRCA25DS654",  # OASIS+SB - AMIVERO LLC
    "47QRCA25DU019",  # OASIS+UR - AMIVERO LLC
    "47QRCA25DW124",  # OASIS+WO - AMIVERO LLC
]
```

### EbuySyncConfig.contract_numbers

Each sync config stores its contract list as a top-level array column (not JSONB):

```python
class EbuySyncConfig(Base):
    contract_numbers: list[str]  # ["47QTCA20D001V", "47QRCA25DA081", ...]
```

A sync config might target all 6 contracts (full sweep) or a subset (e.g., just MAS,
or just OASIS+). This enables different sync frequencies or filter configs per vehicle.

### Cross-Contract Behavior

| Behavior | Verified |
|---|---|
| Single Okta auth covers all contracts | Yes |
| Each contract needs its own eBuy JWT | Yes |
| RFQs do NOT overlap across contracts | Yes (0 shared rfqIds MAS↔OASIS+8A) |
| SINs are vehicle-specific | Yes (MAS: 518210C, OASIS: 20108) |
| OASIS+ contracts return 401 with MAS JWT | Yes |

---

## Ontology, Taxonomy & Metadata Catalog for eBuy

### Solicitation Source (New Entity Field)

Currently there is no entity field to distinguish WHERE a solicitation/opportunity came from.
We need a `solicitation_source` field to identify SAM.gov vs eBuy vs other future sources.

**Add to `entity_field_catalog.yaml`:**

```yaml
solicitation_source:
  data_type: string
  description: "Source system where this opportunity was published (e.g., SAM.gov, eBuy, FBO)"
  indexed: true
  facetable: true
  llm_extracted: false  # Set deterministically from source_ontology_mappings
  storage_namespace: ontology
  applicable_content_types:
    - sam_notice
    - sam_solicitation
    - ebuy_opportunity
    - asset  # For extracted attachments that came from a source
```

**Values:** `"SAM.gov"`, `"eBuy"`, `"FBO"` (legacy), future: `"FPDS"`, `"USASpending"`

### FAR Authority (New Entity Field)

The FAR clause/authority under which the procurement is conducted. Already partially
captured via SAM notice types but not explicitly as a standalone field.

**Add to `entity_field_catalog.yaml`:**

```yaml
far_authority:
  data_type: string
  description: "FAR part/subpart authorizing this procurement action (e.g., FAR 8.4, FAR 12.6, FAR 16.5)"
  indexed: true
  facetable: true
  llm_extracted: true  # Can be extracted from SOWs and solicitations
  storage_namespace: ontology
  applicable_content_types:
    - sam_notice
    - sam_solicitation
    - ebuy_opportunity
    - asset
  extraction_hints:
    - "FAR part"
    - "FAR subpart"
    - "authority"
    - "under FAR"
    - "pursuant to"
```

**Common values for eBuy:**
- `"FAR 8.4"` — Federal Supply Schedules (MAS procurements)
- `"FAR 16.5"` — Indefinite-Delivery Contracts (OASIS+ task orders)
- `"FAR 12.6"` — Streamlined procedures for commercial items
- `"FAR 15"` — Contracting by Negotiation (competitive RFPs)

### Contract Vehicle (Existing Field — Ensure eBuy Maps To It)

The `vehicle` field already exists in `entity_field_catalog.yaml`:

```yaml
vehicle:
  data_type: string
  description: "Contract vehicle (IDIQ, GWAC, BPA, GSA Schedule)"
```

**eBuy mapping:** `schedule` field → `ontology.vehicle`
- MAS → "GSA MAS" or "Multiple Award Schedule"
- OASIS+8A → "OASIS+ 8(a)"
- OASIS+SB → "OASIS+ Small Business"
- OASIS+UR → "OASIS+ Unrestricted"
- OASIS+WO → "OASIS+ Woman-Owned"

### eBuy Namespace Fields (`fields/ebuy.yaml`)

**Create `backend/app/metadata/registry/fields/ebuy.yaml`:**

```yaml
# GSA eBuy opportunity metadata fields
# Applicable content types: ebuy_opportunity

ebuy_opportunity:
  namespace: ebuy
  fields:
    # === Identification ===
    rfq_id:
      data_type: string
      description: "eBuy opportunity ID (e.g., RFQ1798776, RFI1802457)"
      indexed: true
      facetable: false

    request_type:
      data_type: string
      description: "Opportunity type derived from rfqId prefix"
      indexed: true
      facetable: true
      values: ["RFQ", "RFI", "RFP"]

    reference_num:
      data_type: string
      description: "External reference number (buyer's solicitation number)"
      indexed: true
      facetable: false

    # === Classification ===
    schedule:
      data_type: string
      description: "GSA contract vehicle/schedule"
      indexed: true
      facetable: true
      values: ["MAS", "OASIS+8A", "OASIS+SB", "OASIS+UR", "OASIS+WO"]

    sin:
      data_type: string
      description: "Special Item Number"
      indexed: true
      facetable: true

    service_type:
      data_type: string
      description: "Schedule vs IDIQ from ServiceTypeEnum"
      indexed: true
      facetable: true
      values: ["Schedule", "IDIQ"]

    # === Agency ===
    agency_code:
      data_type: string
      description: "Federal agency numeric code"
      indexed: true
      facetable: false

    agency_name:
      data_type: string
      description: "Federal agency name"
      indexed: true
      facetable: true
      ontology_field: agency

    bureau_name:
      data_type: string
      description: "Bureau/sub-agency name"
      indexed: true
      facetable: true
      ontology_field: bureau

    # === Contracting ===
    contract_type:
      data_type: string
      description: "Contract pricing type"
      indexed: true
      facetable: true
      values: ["firm-fixed-price", "time-materials", "cost-plus", "labor-hour"]
      ontology_field: contract_type

    award_method:
      data_type: string
      description: "Evaluation methodology"
      indexed: true
      facetable: true
      values: ["best-value", "lowest-price"]

    commercial_type:
      data_type: string
      description: "C = commercial, N = non-commercial"
      indexed: true
      facetable: true

    # === Status & Lifecycle ===
    status:
      data_type: string
      description: "Curatore-normalized status"
      indexed: true
      facetable: true
      values: ["active", "closed", "cancelled", "awarded"]

    is_amended:
      data_type: boolean
      description: "Has been amended/modified since initial posting"
      indexed: true
      facetable: true

    amendment_count:
      data_type: number
      description: "Number of amendments"
      indexed: true

    # === Dates ===
    issue_date:
      data_type: date
      description: "When opportunity was posted"
      indexed: true
      ontology_field: response_deadline  # No — this is issue, not deadline

    close_date:
      data_type: date
      description: "Response deadline"
      indexed: true
      ontology_field: response_deadline

    pop_start_date:
      data_type: date
      description: "Period of performance start"
      indexed: true
      ontology_field: pop_start_date

    pop_end_date:
      data_type: date
      description: "Period of performance end"
      indexed: true
      ontology_field: pop_end_date

    # === Counts ===
    attachment_count:
      data_type: number
      indexed: true

    vendor_count:
      data_type: number
      description: "Number of vendors invited to this opportunity"
      indexed: true

    # === Source Tracking ===
    source_contract:
      data_type: string
      description: "Amivero contract number this was synced from"
      indexed: true
      facetable: true

    source_url:
      data_type: string
      description: "URL to opportunity on eBuy"
      indexed: true
      ontology_field: source_url

    # === Ingest Lifecycle ===
    ingest_status:
      data_type: string
      indexed: true
      facetable: true
    ingested_at:
      data_type: string
      indexed: true

    # === Classification Lifecycle (Deterministic) ===
    classification_status:
      data_type: string
      indexed: true
      facetable: true
    classified_at:
      data_type: string
      indexed: true
    classification_method:
      data_type: string
      indexed: true

    # === Indexing Lifecycle ===
    indexed_status:
      data_type: string
      indexed: true
      facetable: true
    indexed_at:
      data_type: string
      indexed: true
```

### Source-Ontology Mappings (`source_ontology_mappings.yaml`)

**Add to `source_ontology_mappings.yaml`:**

```yaml
ebuy_opportunity:
  # Classification varies by request type (RFQ vs RFI vs RFP)
  request_type_to_class:
    RFQ: "Solicitation"
    RFI: "Request for Information (RFI)"
    RFP: "Solicitation"

  request_type_to_lifecycle_phase:
    RFQ: "Solicitation"
    RFI: "Pre-Solicitation"
    RFP: "Solicitation"

  classification:
    domain: "Federal Acquisition"
    category: "Solicitation Documents"
    # class: derived from request_type_to_class
    # lifecycle_phase: derived from request_type_to_lifecycle_phase

  fields:
    rfq_id:
      raw_key: "rfqId"
      ontology_field: "solicitation_number"
    agency_name:
      raw_key: "userAgency"
      ontology_field: "agency"
    bureau_name:
      raw_key: "rfqProps.userBureau"
      ontology_field: "bureau"
    office:
      raw_key: "rfqAdditionalInfo.ocoAgency"
      ontology_field: "office"
    schedule:
      raw_key: "schedule"
      ontology_field: "vehicle"
      transform: "ebuy_schedule_to_vehicle"
    contract_type:
      raw_key: "rfqAdditionalInfo.contractType"
      ontology_field: "contract_type"
    close_date:
      raw_key: "closeTime"
      transform: "epoch_ms_to_date"
      ontology_field: "response_deadline"
    pop_start_date:
      raw_key: "rfqInfo.popStartDate"
      transform: "epoch_ms_to_date"
      ontology_field: "pop_start_date"
    pop_end_date:
      raw_key: "rfqInfo.popEndDate"
      transform: "epoch_ms_to_date"
      ontology_field: "pop_end_date"
    place_of_performance:
      raw_key: "rfqAddresses[0]"
      transform: "ebuy_address_to_string"
      ontology_field: "place_of_performance"
    source_url:
      ontology_field: "source_url"
    solicitation_source:
      static_value: "eBuy"
      ontology_field: "solicitation_source"

  # New transforms needed:
  # ebuy_schedule_to_vehicle: MAS → "GSA MAS", OASIS+8A → "OASIS+ 8(a)", etc.
  # epoch_ms_to_date: int → "YYYY-MM-DD" string
  # ebuy_address_to_string: address object → "City, ST ZIP"

  query_model_suppress:
    - agency_name
    - bureau_name
```

### Retroactive: Update SAM Source Mappings

Add `solicitation_source` to existing SAM mappings:

```yaml
# In sam_solicitation and sam_notice sections of source_ontology_mappings.yaml:
solicitation_source:
  static_value: "SAM.gov"
  ontology_field: "solicitation_source"
```

### Data Sources Registry (`data_sources.yaml`)

**Add eBuy entry:**

```yaml
gsa_ebuy:
  display_name: "GSA eBuy"
  description: "GSA eBuy is the online portal where federal buyers post RFQs, RFIs, and RFPs for GSA contract holders. Supports MAS (Multiple Award Schedule) and OASIS+ contract vehicles."
  data_contains:
    - "Requests for Quotation (RFQ) on GSA schedules"
    - "Requests for Information (RFI) for market research"
    - "Requests for Proposal (RFP) for OASIS+ task orders"
    - "Solicitation attachments (SOWs, ITOs, CDRLs, pricing templates)"
    - "Amendment/modification history"
    - "Competitor intelligence (invited vendor lists)"
  capabilities:
    - "Search opportunities by keyword, schedule, SIN, agency"
    - "Track amendment history and status changes"
    - "Download and extract solicitation attachments"
    - "Identify competitors invited to bid"
    - "Monitor quote/bid status"
  example_questions:
    - "What new OASIS+ RFPs were posted this week?"
    - "Show me DoD opportunities on MAS schedule 518210C"
    - "Which competitors are bidding on the S-TRIG opportunity?"
    - "Are there any open RFQs closing in the next 7 days?"
  search_tools:
    - tool: search_assets
      use_for: "Search eBuy opportunities and their attachments"
      filter: "solicitation_source='eBuy'"
  note: "eBuy requires Okta 2FA authentication. Each JWT is scoped to a single GSA contract. Opportunities do not overlap across contract vehicles."
```

### Taxonomy Additions (`document_taxonomy.yaml`)

eBuy RFIs map to existing "Request for Information (RFI)" class. RFQs and RFPs map to
existing "Solicitation" class. No new taxonomy classes needed — eBuy fits cleanly into
the existing Federal Acquisition domain.

However, consider adding a `subclass` for eBuy-specific distinction:

```yaml
# Under federal_acquisition > solicitation_documents > solicitation:
solicitation:
  subclasses:
    gsa_schedule_rfq:
      display_name: "GSA Schedule RFQ"
      description: "Request for Quotation on GSA Multiple Award Schedule"
    oasis_task_order_rfp:
      display_name: "OASIS+ Task Order RFP"
      description: "Request for Proposal for OASIS+ task order"
```

## Config.yml Entry

```yaml
ebuy:
  enabled: true
  okta_domain: mfalogin.fas.gsa.gov
  base_url: https://www.ebuy.gsa.gov
  timeout: 30
  max_retries: 3
  rate_limit_delay: 1.0              # Conservative — unknown rate limits
  otp_method: microsoft_graph        # or 'manual'
  token_refresh_minutes: 25          # Refresh before 30-min JWT expiry
  contracts:                         # All available contracts
    - number: "47QTCA20D001V"
      vehicle: "MAS"
      company: "AMIVERO LLC"
    - number: "47QTCA24D000Z"
      vehicle: "MAS"
      company: "STELLA JV, LLC"
    - number: "47QRCA25DA081"
      vehicle: "OASIS+8A"
      company: "AMIVERO LLC"
    - number: "47QRCA25DS654"
      vehicle: "OASIS+SB"
      company: "AMIVERO LLC"
    - number: "47QRCA25DU019"
      vehicle: "OASIS+UR"
      company: "AMIVERO LLC"
    - number: "47QRCA25DW124"
      vehicle: "OASIS+WO"
      company: "AMIVERO LLC"
```

## Missing Models (Identified via SAM.gov Gap Analysis)

The following models are present in SAM.gov but not yet in our eBuy design:

### EbuySolicitationSummary (equivalent to SamSolicitationSummary)

LLM-generated analysis of opportunities.

```python
class EbuySolicitationSummary(Base):
    __tablename__ = "ebuy_solicitation_summaries"

    id: UUID
    opportunity_id: UUID (FK → ebuy_opportunities)
    summary_type: str                  # full, executive, technical, compliance
    is_canonical: bool                 # Active/promoted summary
    summary_text: str
    model_used: str                    # LLM model
    prompt_template_hash: str
    key_requirements: JSONB            # Structured extraction
    compliance_checklist: JSONB
```

### EbuyApiUsage (equivalent to SamApiUsage)

Rate limit tracking (eBuy rate limits are unknown — track conservatively).

```python
class EbuyApiUsage(Base):
    __tablename__ = "ebuy_api_usage"

    id: UUID
    organization_id: UUID
    usage_date: date
    call_count: int
    daily_limit: int                   # TBD — start with conservative limit
```

### EbuyAgency (equivalent to SamAgency)

Agency reference data (eBuy uses numeric `agencyCode` + `agencyName`).

```python
class EbuyAgency(Base):
    __tablename__ = "ebuy_agencies"

    id: UUID
    agency_code: str (unique)          # "15" (DOJ), "70" (DHS), "97" (DoD)
    agency_name: str                   # "Department of Justice"
    is_active: bool
```

## Run Integration Pattern

Following SAM.gov's pattern, each eBuy sync creates a Run record:

```python
run = Run(
    name=f"eBuy Sync: {sync_config.name} ({len(contracts)} contracts)",
    job_type="ebuy_sync",
    status="running",
    organization_id=org_id,
)
```

- **One Run per sync invocation** (covers all contracts in the sync config)
- Per-contract progress tracked via Run logs:
  ```python
  await _log_event(session, run.id, "INFO", "contract_start",
      f"Starting sync for {contract_number} ({vehicle})")
  ```
- Attachment downloads use `group_id=run.id` for batch tracking
- Final result: `{contracts_synced: {contract: {opportunities: N, new: N, updated: N, attachments: N}}}`

## Token Lifecycle Management (eBuy-specific)

Unlike SAM.gov (static API key), eBuy requires active token management.

### Key Finding: Single Okta Auth → Multiple Contract JWTs (No Re-Auth)

Verified: the eBuy frontend does NOT re-authenticate when switching between contracts.
The flow is:

```
1. Okta 2FA (once) → Okta access token (1 hour)
2. POST /seller/oktalogin/ → contract list (no JWT yet)
3. POST /seller/getuser {contract: A} → eBuy JWT for A (30 min)
4. POST /seller/getuser {contract: B} → eBuy JWT for B (30 min)  ← same Okta token, no re-auth
5. POST /seller/getuser {contract: C} → eBuy JWT for C (30 min)  ← same Okta token
   ...
```

**This means the sync can iterate all 6 contracts with a single Okta authentication cycle.**
The 1-hour Okta token window is more than enough for 6 contracts × ~5 min each = ~30 min.

### Token Hierarchy

```
Okta access token (1 hour, obtained once per sync)
├── eBuy JWT for 47QTCA20D001V / MAS (30 min)
├── eBuy JWT for 47QTCA24D000Z / MAS (30 min)
├── eBuy JWT for 47QRCA25DA081 / OASIS+8A (30 min)
├── eBuy JWT for 47QRCA25DS654 / OASIS+SB (30 min)
├── eBuy JWT for 47QRCA25DU019 / OASIS+UR (30 min)
└── eBuy JWT for 47QRCA25DW124 / OASIS+WO (30 min)
```

### Refresh Strategy

- **Okta access token**: Re-authenticate (full 2FA) if > 50 min old
- **eBuy JWT per contract**: Call `getuser` again with same Okta token (instant, no re-auth)
- **Track state** in `EbuySyncConfig.token_config` JSONB:
  ```json
  {
    "okta_token_expires_at": "2026-03-25T12:00:00Z",
    "last_auth_at": "2026-03-25T11:00:00Z"
  }
  ```

## Beat Schedule / Periodic Tasks

Register in `app/core/ops/scheduled_task_registry.py`:

```python
@register(
    task_type="connector.ebuy_sync",
    name="ebuy_sync",
    display_name="eBuy Sync",
    description="Trigger eBuy syncs based on frequency and last_synced_at.",
    schedule_expression="0 */2 * * *",  # Every 2 hours (conservative)
)
async def handle_ebuy_scheduled_sync(session, run, config):
    # Query active EbuySyncConfig with sync_frequency != "manual"
    # For each: check _is_sync_due() (same logic as SAM)
    # Execute ebuy_sync_task() if due
```

**Schedule: every 2 hours** (conservative — SAM is hourly, but eBuy has unknown rate limits
and requires Okta 2FA which adds latency).

## CWR Procedures Needed

| Procedure | SAM.gov Equivalent | Description |
|---|---|---|
| `ebuy_daily_digest.json` | `sam_daily_digest.json` | Daily opportunity analysis with LLM disposition (ACTIONABLE/MONITOR/IGNORE) |
| `ebuy_opportunity_watch.json` | (none) | Monitor specific RFQs for status changes, deadline alerts |
| `ebuy_quote_tracker.json` | (none) | Track our quotes vs competitors |

### CWR Functions Needed

| Function | Purpose |
|---|---|
| `ebuy.search_opportunities` | Query EbuyOpportunity records with filters |
| `ebuy.get_opportunity_detail` | Fetch full opportunity with mods, attachments, competitors |
| `ebuy.get_competitor_list` | Extract `rfqVendors` from `rfqCategories` |
| `ebuy.get_quote_status` | Track our quotes (eBuy-specific) |

## Asset Creation from Attachments

Follow SAM.gov's pattern in `ebuy_pull_service.download_attachment()`:

```python
asset = await asset_service.create_asset(
    session=session,
    organization_id=organization_id,
    source_type="ebuy",
    source_metadata={
        "attachment_id": str(attachment.id),
        "opportunity_id": str(attachment.opportunity_id),
        "rfq_id": opportunity.rfq_id,
        "doc_name": attachment.doc_name,
        "doc_path": attachment.doc_path,
        "doc_seq_num": attachment.doc_seq_num,
        "agency_name": opportunity.agency_name,
        "bureau_name": opportunity.bureau_name,
        "schedule": opportunity.schedule,
        "source_contract": opportunity.source_contract,
        "downloaded_at": datetime.utcnow().isoformat(),
    },
    original_filename=attachment.doc_name,
    content_type=content_type,
    file_size=len(file_content),
    raw_bucket=bucket,
    raw_object_key=f"{org_id}/ebuy/{opportunity.rfq_id}/{attachment.doc_name}",
    group_id=run_id,
    source_url=f"https://www.ebuy.gsa.gov/ebuy/seller/prepare-quote/{opportunity.rfq_id}",
)
```

## Connector Directory Structure

```
backend/app/connectors/gsa_ebuy/
├── __init__.py
├── ebuy_service.py              # CRUD for EbuyOpportunity, EbuyModification, EbuyAttachment, EbuyQuote
├── ebuy_pull_service.py         # API client: data fetch + attachment download
├── ebuy_auth_service.py         # Okta 2FA + OIDC PKCE + Graph OTP + token lifecycle
├── ebuy_summarization_service.py # LLM analysis of opportunities
├── ebuy_api_usage_service.py    # Rate limit tracking (conservative)
└── agency_map.yaml              # Agency code → canonical name mapping
```

## API Router Structure (Needed)

```
backend/app/api/v1/connectors/routers/ebuy/
├── sync_configs.py              # CRUD on sync configurations
├── opportunities.py             # List/detail opportunities (client-side filters)
├── attachments.py               # Attachment status & download tracking
├── quotes.py                    # Vendor quote tracking (eBuy-specific)
├── dashboard.py                 # Aggregated stats
└── _helpers.py                  # Shared utilities (org scoping, auth)
```

## Date Handling

eBuy uses **epoch milliseconds** (not seconds). Conversion:

```python
from datetime import datetime, timezone

def epoch_ms_to_datetime(epoch_ms: int) -> datetime:
    """Convert eBuy epoch milliseconds to UTC datetime."""
    if epoch_ms is None:
        return None
    return datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
```

## Multi-Contract Sync Strategy

Since each JWT is scoped to a single contract, the sync must:

1. Authenticate once (Okta 2FA → Okta access token — valid 1 hour)
2. For each contract: call `getuser` with the Okta access token → fresh eBuy JWT
3. Sync that contract's RFQs with its JWT
4. Move to next contract (no re-authentication needed within the 1-hour Okta window)

**Deduplication**: The same RFQ may appear under multiple contracts (e.g., a MAS RFQ visible
to both `47QTCA20D001V` and `47QTCA24D000Z`). Deduplicate by `rfq_id` (globally unique).
Store `source_contract` as the first contract that discovered it.

## Attachment Download (Verified)

Attachments use a **POST** request with **multipart/form-data** (not GET). The FormData
contains a single field `data` whose value is a JSON-stringified object.

**Endpoint:**
```
POST /ebuy/api/services/ebuyservices/rfq/{rfqId}/rfqAttachment/
Authorization: Bearer <eBuy JWT>
Content-Type: multipart/form-data
```

**FormData:**
```
data = JSON.stringify({
  "fileName": "<docName from rfqAttachments>",
  "docPath": "<docPath from rfqAttachments>",
  "action": "download"
})
```

**Python (requests):**
```python
data_payload = json.dumps({
    "fileName": attachment["docName"],
    "docPath": attachment["docPath"],
    "action": "download",
})
resp = requests.post(
    f"{EBUY_API}/rfq/{rfq_id}/rfqAttachment/",
    files={"data": (None, data_payload)},
    headers={"authorization": f"Bearer {token}", "accept": "text/plain"},
    timeout=60,
)
# resp.content = binary file bytes
# resp.headers["Content-Type"] = "application/pdf" | "application/vnd.openxmlformats-..."
# resp.headers["Content-Disposition"] = 'attachment; filename="<docPath filename>"'
```

**Verified file types:**

| File | Content-Type | Size | Magic |
|---|---|---|---|
| PDF | `application/pdf` | 349,768 bytes | `%PDF` |
| PDF (large) | `application/pdf` | 792,849 bytes | `%PDF` |
| XLSX | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` | 23,600 bytes | `PK\x03\x04` |

**Key notes:**
- The `docPath` field from `rfqAttachments` is used as-is (it's a server-side path)
- External attachments (where `docPath` starts with `http`) use a direct GET instead
- The response `Content-Disposition` filename uses the `docPath` filename (with timestamp), not `docName`
- Bulk download via `POST /rfq/{rfqId}/attachments/downloadAll` returns a ZIP (from JS analysis)

**docPath structure:**
```
/ebuy_upload/{YYYYMM}/{rfqId}/{randomHash}/{docName}.{epochMs}.{ext}
```
Example: `/ebuy_upload/202603/RFQ1798776/FalndjH2/Attachment 2_ICDE Minimum Requirements_Final_v1.0.1772636974698.pdf`

## Notification-Driven Amendment Tracking

Notifications provide a lightweight event stream for each contract. They tell us WHAT changed
without fetching the full RFQ detail:

```json
{"id": "RFP1802125", "issueTime": 1774292600710, "scheduleNumber": "OASIS+8A", "messageType": "modified", "calendar": 1774373764706}
```

### Event Types and Actions

| messageType | Meaning | Sync Action |
|---|---|---|
| `Quote Requested` | New opportunity posted | Create EbuyOpportunity + fetch full detail |
| `modified` | Existing opportunity amended | Fetch detail, create EbuyModification, update EbuyOpportunity |
| `cancelled` | Opportunity cancelled | Update EbuyOpportunity.status = "cancelled" |

### EbuyOpportunity History Tracking

Store amendment/event history in a `history` JSONB column on EbuyOpportunity:

```python
class EbuyOpportunity(Base):
    # ... existing fields ...

    history: JSONB  # Append-only log of lifecycle events
    # [
    #   {"event": "created", "at": "2026-03-21T12:00:00Z", "source": "activerfqs"},
    #   {"event": "modified", "at": "2026-03-24T17:36:00Z", "version": 1,
    #    "note": "Amendment to correct Contracting POCs and Q&A submission date"},
    #   {"event": "cancelled", "at": "2026-03-24T14:51:00Z"}
    # ]
```

### Amendment-Aware Attachment Classification

When an opportunity is amended, new attachments often appear. These should be tagged in their
`source_metadata` to indicate they're amendment-related:

```python
source_metadata = {
    "ebuy": {
        "rfq_id": "RFP1802125",
        "is_amendment": True,           # True if added after initial posting
        "amendment_version": 1,         # Which amendment introduced this attachment
        "original_doc_name": "01 S-TRIG ITO r1 20260324.docx",  # "r1" = revision 1
    }
}
```

**Heuristics for detecting amendment attachments:**
- `docSessionDate` is later than `issueTime` → attachment was added post-posting
- Filename contains revision indicators: `r1`, `r2`, `Rev`, `Amendment`, `A000XX`
- Attachment appears in `rfqModifications[].modificationTime` window

### Ontology/Taxonomy Metadata for Amendments

Add to the metadata registry (`ebuy.yaml`):

```yaml
ebuy_opportunity:
  fields:
    is_amended:
      data_type: boolean
      indexed: true
      facetable: true            # Filter for amended vs original
    amendment_count:
      data_type: number
      indexed: true
    latest_amendment_date:
      data_type: date
      indexed: true

# For attachments (Assets with source_type=ebuy)
ebuy_attachment:
  fields:
    is_amendment_attachment:
      data_type: boolean
      indexed: true
      facetable: true            # Filter for amendment docs vs original docs
    amendment_version:
      data_type: number
      indexed: true
```

### Sync Flow with Notifications

Optimized sync uses notifications as a pre-flight check:

```
1. GET /seller/notifications/{contract}
   │
   ├─ For "Quote Requested" → new rfq_id
   │  └─ GET /seller/rfq/{rfqId}/{contract} → full detail → CREATE
   │
   ├─ For "modified" → existing rfq_id amended
   │  └─ GET /seller/rfq/{rfqId}/{contract} → full detail → UPDATE + new EbuyModification
   │     └─ Diff attachments: new ones are amendment attachments
   │
   ├─ For "cancelled" → existing rfq_id
   │  └─ UPDATE status=cancelled (no detail fetch needed)
   │
   └─ THEN: full activerfqs fetch for completeness (catch anything notifications missed)
```

## Implementation Status vs SAM.gov

| Area | SAM.gov | eBuy | Status |
|---|---|---|---|
| Database models | 9 models | 5 designed + 3 identified gaps | Design complete |
| Alembic migrations | 4 migrations | 0 | Not started |
| API routers | 6 modules | 0 | Not started |
| Metadata registry | `sam.yaml` | 0 | Not started |
| Metadata builders | 2 builders | Designed, not implemented | Design only |
| Celery tasks | `sam_pull_task` | 0 | Not started |
| Beat schedule | Hourly | Designed (every 2hr) | Not started |
| CWR procedures | 2 (daily/weekly digest) | 0 | Not started |
| Frontend pages | 4 pages + components | 0 | Not started |
| Auth chain | Static API key | Full Okta 2FA + OIDC PKCE (spike scripts working) | **Spike complete** |
| API exploration | N/A (public docs) | ~85 endpoints discovered, key ones verified | **Spike complete** |
| Attachment download | GET from SAM API | POST with multipart FormData (verified) | **Spike complete** |
| Search/filtering | Server-side pagination | Client-side only (searchactiverfqs broken) | **Spike complete** |

## Open Questions

1. **SIN → PSC mapping**: Can we map eBuy SIN codes to SAM.gov PSC codes for unified faceting?
2. **Quote tracking scope**: Do we want to track our own quotes (bid management) or just the opportunities?
3. **Cross-contract dedup**: How to handle the same RFQ appearing under multiple contracts? (First-seen wins for `source_contract`, but should we track all contracts that see it?)
4. **Attachment password**: Some RFQs have passwords (`rfqPassword`) — store in DB for auto-download, or skip?
5. **Historical depth**: How far back should the initial backfill go? (274 historical quotes on MAS alone)
6. **Rate limits**: Unknown — start with 2-hour sync intervals and 1s delay between API calls
7. ~~**searchactiverfqs**~~: **RESOLVED** — works with `matchtype` as integer (not string). See Search section above.

## Answered Questions

| Question | Answer |
|---|---|
| Server-side search? | YES — `POST /seller/searchactiverfqs` with `{contractnumber, query, matchtype: 1, sortspec}`. matchtype must be INT (0/1=any, 2=exact phrase). Previous 500 errors were from using string matchtype. |
| Date filtering? | Client-side only. No date params in search API. Filter on `issueTime`, `closeTime`, `lastRfqModDate` (epoch ms) |
| Pagination? | None server-side. All matching results returned at once |
| Sort options? | YES — via `sortspec`: `CloseDate dsc/asc`, `IssueDate dsc/asc`, `Title asc` |
| Notification structure? | Keyed by contract → array of `{id, issueTime, scheduleNumber, messageType, calendar}` |
| Amendment tracking? | Via `rfqModifications[]` array + notifications with `messageType: "modified"` |
