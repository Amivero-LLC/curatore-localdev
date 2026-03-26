# GSA eBuy Integration — Technical Requirements

## Overview

GSA eBuy (<https://www.ebuy.gsa.gov>) is a government procurement platform where federal buyers post RFQs/RFIs/RFPs and GSA contract holders submit quotes. Unlike SAM.gov (which provides a public API key), eBuy requires automated 2-factor email authentication through GSA's Okta instance. Once authenticated, a JWT bearer token is obtained that is scoped to a single GSA contract and valid for approximately **30 minutes**.

The long-term goal is to integrate eBuy data into the Curatore platform as a data connection, similar to the existing SAM.gov integration. See `ebuy_data_model.md` for the full data model and sync architecture.

## Architecture

### Authentication Chain

```
┌──────────┐     ┌──────────────────────┐     ┌──────────┐     ┌───────────┐     ┌──────────┐
│  Curatore │────▶│  GSA Okta            │────▶│  Email   │────▶│  Okta     │────▶│  eBuy    │
│  Backend  │     │  mfalogin.fas.gsa.gov│     │  OTP     │     │  OIDC     │     │  API     │
│           │     │  (username+password) │     │  (Graph) │     │  (PKCE)   │     │  (JWT)   │
└──────────┘     └──────────────────────┘     └──────────┘     └───────────┘     └──────────┘
```

**Full flow:** Okta authn → Email MFA → OIDC PKCE → Okta access token → eBuy oktalogin → eBuy getuser → **eBuy JWT**

### Key Differences from SAM.gov

| Aspect | SAM.gov | GSA eBuy |
|--------|---------|----------|
| Auth method | Static API key | Okta 2FA → OIDC PKCE → contract-scoped JWT |
| Token lifetime | Indefinite (key-based) | eBuy JWT: ~30 min, Okta token: 1 hour |
| Token scope | Global | Per-contract (need separate JWT per contract) |
| Token refresh | N/A | Call `getuser` again with same Okta token |
| API style | Public REST API with pagination | Authenticated SPA backend, full result sets |
| Pagination | Server-side (pageNumber/pageSize) | Client-side (all results returned at once) |
| Rate limiting | 1,000 calls/day | Unknown — treat conservatively |
| Email MFA | No | Yes — requires email inbox access (Graph API) |
| Service account | Not needed | Planned: `ebuy@amivero.com` |
| Classification | NAICS + PSC + set-aside | Schedule + SIN (Special Item Number) |
| Opportunity ID | notice_id (UUID) | rfqId (e.g., `RFQ1798776`, `RFI1802457`) |

## GSA Okta Configuration

- **Okta Domain**: `mfalogin.fas.gsa.gov`
- **Okta Auth Server ID**: `${EBUY_OKTA_AUTH_SERVER_ID}` (in `.env`)
- **OIDC Client ID**: `${EBUY_OKTA_CLIENT_ID}` (in `.env`, public client, PKCE)
- **OIDC Redirect URI**: `https://www.ebuy.gsa.gov/ebuy/pkce/callback`
- **OIDC Scopes**: `openid profile email`
- **Auth endpoint**: `POST https://mfalogin.fas.gsa.gov/api/v1/authn`
- **Token endpoint**: `POST https://mfalogin.fas.gsa.gov/oauth2/${EBUY_OKTA_AUTH_SERVER_ID}/v1/token`
- **OIDC Discovery**: `GET https://mfalogin.fas.gsa.gov/.well-known/openid-configuration`
- **MFA type**: Email OTP (6-digit code)
- **Email factor ID**: Auto-discovered from authn response (user-specific)

> **Note**: Factor IDs and user IDs are user-specific and will change when we switch to the `ebuy@amivero.com` service account.

## Authentication Flow (Detailed)

### Step 1: Primary Authentication

```
POST https://mfalogin.fas.gsa.gov/api/v1/authn
Content-Type: application/json
```

**Body:**
```json
{
  "password": "<password>",
  "username": "<username>",
  "options": {
    "warnBeforePasswordExpired": true,
    "multiOptionalFactorEnroll": true
  }
}
```

**Response:** `status: "MFA_REQUIRED"` with `stateToken`, user profile, and available MFA factors.

### Step 2: Trigger Email MFA

```
POST https://mfalogin.fas.gsa.gov/api/v1/authn/factors/{factorId}/verify?rememberDevice=true
Content-Type: application/json
Body: { "stateToken": "<stateToken>" }
```

**Response:** `status: "MFA_CHALLENGE"` — sends a 6-digit code to the user's email. The verify URL for submitting the code is in `_links.next.href`.

### Step 3: Verify Email Code

```
POST <_links.next.href from Step 2>?rememberDevice=true
Content-Type: application/json
Body: { "stateToken": "<stateToken>", "passCode": "<6-digit code>" }
```

**Response:** `status: "SUCCESS"` with `sessionToken`.

### Step 4: OIDC Authorization (PKCE)

Uses the Okta `sessionToken` to perform an OIDC Authorization Code + PKCE flow **without a browser**.

```
GET https://mfalogin.fas.gsa.gov/oauth2/${EBUY_OKTA_AUTH_SERVER_ID}/v1/authorize
    ?client_id=${EBUY_OKTA_CLIENT_ID}
    &response_type=code
    &scope=openid+profile+email
    &redirect_uri=https://www.ebuy.gsa.gov/ebuy/pkce/callback
    &state=<random>&nonce=<random>
    &code_challenge=<S256 hash of code_verifier>
    &code_challenge_method=S256
    &sessionToken=<sessionToken from Step 3>
```

**Response:** `302` redirect to callback URL with `code` parameter. Extract `code` from the Location header (do NOT follow the redirect).

### Step 5: Exchange Code for Okta Access Token

```
POST https://mfalogin.fas.gsa.gov/oauth2/${EBUY_OKTA_AUTH_SERVER_ID}/v1/token
Content-Type: application/x-www-form-urlencoded
Body: grant_type=authorization_code&code=<code>&client_id=${EBUY_OKTA_CLIENT_ID}&redirect_uri=<redirect_uri>&code_verifier=<code_verifier>
```

**Response:** `access_token` (Okta JWT, 1 hour expiry), `id_token`, `scope: "email openid profile"`.

### Step 6a: eBuy OktaLogin (Get Contracts)

```
POST https://www.ebuy.gsa.gov/ebuy/api/services/ebuyservices/seller/oktalogin/
Content-Type: text/plain
Body: { "oktatoken": "<Okta access_token>", "token": "" }
```

**Response:** `rc: 2` with `sellerContractInfoList` — array of available contracts.

### Step 6b: eBuy GetUser (Select Contract → JWT)

```
POST https://www.ebuy.gsa.gov/ebuy/api/services/ebuyservices/seller/getuser
Content-Type: application/json
Body: { "contractnumber": "47QTCA20D001V", "password": null, "oktatoken": "<Okta access_token>" }
```

**Response:** `rc: 4, message: "OTP successfully verified"` with `token: "<eBuy JWT>"`.

> **Important**: The eBuy JWT is scoped to a **single contract number**. To sync all 6 contracts, call `getuser` once per contract using the same Okta access token (valid 1 hour). No re-authentication needed.

## eBuy API

### Base URLs

| Prefix | URL | Usage |
|--------|-----|-------|
| Main API | `https://www.ebuy.gsa.gov/ebuy/api/services/ebuyservices/` | Most endpoints |
| Proj API | `https://www.ebuy.gsa.gov/ebuy/api/services/ebuyservices_proj/` | Attachment uploads |
| eLibrary | `https://www.ebuy.gsa.gov/ebuy/api/` | Search/category lookup |

### Authentication

All API calls require:
```
Authorization: Bearer <eBuy JWT from Step 6b>
```

### Response Envelope

All responses follow this pattern:
```json
{
  "header": { "status": 0 },
  "response": { ... }
}
```
- `header.status == 0` = success
- `header.status != 0` = error

### JWT Token Structure

```json
{
  "jti": "4ed8c37bf28d4b8ea786c976174f5c80",
  "iat": 1774404214.9928305,
  "exp": 1774406014.9928305,
  "data": {
    "user": "47QTCA20D001V",
    "user_id": 2549581,
    "store_id": "0",
    "user_type": "EBUYVENDOR",
    "sas_code": "00",
    "authorization_code": 0,
    "email": "<EBUY_USERNAME>",
    "client_logged_in_i_p_address": "<client_ip>"
  },
  "rcnt": 0
}
```

**Token lifetime**: ~30 minutes. Refresh by calling `getuser` again with the same Okta access token.

### Contract Numbers & Vehicles

| Contract Number | Vehicle | Company |
|----------------|---------|---------|
| 47QTCA20D001V | MAS | AMIVERO LLC |
| 47QTCA24D000Z | MAS | STELLA JV, LLC |
| 47QRCA25DA081 | OASIS+8A | AMIVERO LLC |
| 47QRCA25DS654 | OASIS+SB | AMIVERO LLC |
| 47QRCA25DU019 | OASIS+UR | AMIVERO LLC |
| 47QRCA25DW124 | OASIS+WO | AMIVERO LLC |

Each contract receives different RFQ/RFI opportunities. The sync iterates across all contracts.

### API Endpoints — Seller (Vendor)

#### Opportunities

| Method | Endpoint | Description | Verified |
|--------|----------|-------------|----------|
| GET | `/seller/activerfqs/{contractNumber}` | List all active RFQs for a contract | Yes — 94 RFQs on MAS |
| GET | `/seller/rfq/{rfqId}/{contractNumber}` | Full RFQ detail (info, attachments, mods, categories, CLINs, vendors) | Yes — MAS + OASIS+8A |
| GET | `/seller/findrfq/{rfqNumber}` | Find RFQ by number | Yes (from JS) |
| POST | `/seller/searchactiverfqs` | Text search with sort. Body: `{contractnumber, query, matchtype: 1, sortspec: "CloseDate dsc"}`. matchtype must be INT (0/1=any word, 2=exact phrase). | Yes — verified |
| GET | `/seller/notifications/{contractNumber}` | Notification alerts for a contract | Yes — 37 on MAS |
| GET | `/seller/rfqawardinfo/{rfqId}/{contractNumber}` | Award info for an RFQ | Yes |
| POST | `/seller/watchrfq/{rfqId}/{contractNumber}` | Watch/track an RFQ | From JS |
| GET | `/seller/watchrfqstatus/{rfqId}/{contractNumber}` | Check if RFQ is watched | From JS |
| POST | `/seller/hiderfqs` | Hide RFQs from active list | From JS |

#### Quotes (Vendor Responses)

| Method | Endpoint | Description | Verified |
|--------|----------|-------------|----------|
| GET | `/seller/getquotes/a/{contractNumber}` | Active quotes | Yes |
| GET | `/seller/getquotes/h/{contractNumber}` | Historical quotes | Yes — 274 on MAS |
| GET | `/seller/getquote/{rfqId}/{contractNumber}` | Quote for specific RFQ | From JS |
| GET | `/seller/getquoteById/{quoteId}/{contractNumber}` | Quote by ID | From JS |
| POST | `/seller/savequote` | Save quote draft | From JS |
| POST | `/seller/submitquote` | Submit quote | From JS |
| POST | `/seller/interestedquote` | Mark as interested | From JS |
| POST | `/seller/submitnoquote` | Submit no-quote response | From JS |

#### Attachments

| Method | Endpoint | Description | Verified |
|--------|----------|-------------|----------|
| POST | `/rfq/{rfqId}/rfqAttachment/` | Download attachment (multipart FormData with JSON `data` field) | Yes — PDF, XLSX verified |
| POST | `/rfq/{rfqId}/attachments/downloadAll` | Download all RFQ attachments as zip | From JS |

#### Profile & Contracts

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/seller/oktalogin/` | Okta login → contract list |
| POST | `/seller/getuser` | Select contract → eBuy JWT |
| GET | `/seller/profile/contract/{contractNumber}` | Associated contracts |
| GET | `/seller/profile/vendorcategory/{contractNumber}` | Vendor categories/SINs |

### API Endpoints — Authentication

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | `/login` | Session login (eBuy Connect) |
| POST | `/logout` | Session logout |
| POST | `/validate` | Validate session token |
| POST | `/renew` | Renew session |

### Required Headers

| Header | Value |
|--------|-------|
| `Accept` | `application/json, text/plain, */*` |
| `Authorization` | `Bearer <eBuy JWT>` |
| `Referer` | `https://www.ebuy.gsa.gov/ebuy/seller/` |
| `User-Agent` | Standard browser UA string |

### Key Data Shapes

#### Active RFQ List Item

Response from `GET /seller/activerfqs/{contract}` — keyed by contract number:

```json
{
  "rfqId": "RFQ1798776",
  "title": "Investigative Case and Data Ecosystem (ICDE)",
  "rfqStatus": 4,
  "rfqStatusText": "Closed",
  "agencyCode": "15",
  "userName": "ROBERT JONES",
  "userAgency": "Department of Justice",
  "userEmail": "robert.a.jonesjr@dea.gov",
  "issueTime": 1772638645436,
  "closeTime": 1778270400000,
  "cancelTime": 1772600400000,
  "schedule": "MAS",
  "sin": "518210C",
  "quoteStatus": 0,
  "awardCount": 0,
  "lastRfqModVersion": 3,
  "rfq": {
    "rfqInfo": { ... },
    "rfqAdditionalInfo": { ... },
    "rfqModifications": [ ... ],
    "rfqAttachments": [ ... ]
  }
}
```

#### RFQ Detail (rfqAdditionalInfo)

Rich buyer/contracting officer info:

```json
{
  "followOnRequirement": "N",
  "commercialType": "C",
  "contractType": "firm-fixed-price",
  "awardMethod": "best-value",
  "ocoName": "Marie T. Devine",
  "ocoTitle": "Contracting Officer",
  "ocoAgency": "Drug Enforcement Administration",
  "ocoPhone": "571-776-0624",
  "ocsName": "Robert A. Jones",
  "ocsTitle": "Contract Specialist",
  "ocsAgency": "Drug Enforcement Administration",
  "ocsPhone": "571-776-1215"
}
```

#### Attachment

```json
{
  "docName": "Attachment 2_ICDE Minimum Requirements_Final_v1.0.pdf",
  "docPath": "/ebuy_upload/202603/RFQ1798776/FalndjH2/Attachment 2_ICDE Minimum Requirements_Final_v1.0.1772636974698.pdf",
  "docSeqNum": 3594487,
  "docType": 0,
  "docSessionDate": 1772636974698
}
```

Download via **POST** with **multipart/form-data**. The `data` field contains a JSON-stringified object:
```python
requests.post(url, files={"data": (None, json.dumps({"fileName": docName, "docPath": docPath, "action": "download"}))})
```
Returns binary file with correct `Content-Type` and `Content-Disposition` headers.
Verified: PDF (up to 792KB), XLSX (23KB). DOCX expected to work similarly (PK/ZIP format).

#### Notification

Lightweight alert (not full opportunity data):

```json
{
  "id": "RFI1802479",
  "issueTime": 1774391278516,
  "scheduleNumber": "MAS",
  "messageType": "Quote Requested",
  "calendar": 1774391278516
}
```

### RFQ Status Codes

| Code | Description | Curatore Status |
|------|-------------|-----------------|
| 1 | Open | active |
| 2 | Closed | closed |
| 3 | Open | active |
| 4 | Cancelled | cancelled |

### Request Type (from rfqId prefix)

| Prefix | Type |
|--------|------|
| RFQ | Request for Quote |
| RFI | Request for Information |
| RFP | Request for Proposal |

### Date Format

All dates are **epoch milliseconds** (not seconds):
```python
datetime.fromtimestamp(epoch_ms / 1000, tz=timezone.utc)
```

## Credentials

### Credentials

| Variable | Purpose |
|----------|---------|
| `EBUY_USERNAME` | eBuy/Okta login email AND OTP inbox (read via Graph API) |
| `EBUY_PASSWORD` | Okta password |
| `EBUY_OKTA_AUTH_SERVER_ID` | GSA Okta auth server ID |
| `EBUY_OKTA_CLIENT_ID` | GSA Okta OIDC client ID |

All values set in root `.env` (never committed).

### Architecture

```
${EBUY_USERNAME} (single account for everything)
     │
     ├─ Authenticates to GSA Okta (Steps 1-3)
     ├─ Receives OTP email from Okta
     ├─ Graph API reads OTP from this mailbox (Mail.Read permission)
     └─ OIDC PKCE → eBuy JWT (Steps 4-6)
```

The `ebuy@amivero.com` account is a **shared mailbox** in Microsoft 365 that is also
registered as an eBuy/Okta user. Graph API has `Mail.Read` permission scoped to this mailbox.

### Production Deployment

- Stephen to configure environment variables in ArgoCD for `curator.dev.amivero-solutions`

## Automation Strategy for Email OTP

### Approach A: Microsoft Graph API (Preferred — implemented)

Script: `scripts/ebuy/ebuy_graph_otp.py`

1. Authenticate to Okta with `ebuy@amivero.com` credentials
2. Trigger email MFA → OTP email arrives in inbox
3. Poll inbox via Graph API (`/users/{email}/messages` with OData filter for Okta emails)
4. Parse 6-digit OTP code from email body
5. Submit OTP to complete authentication

**Requirements:**
- `ebuy@amivero.com` must be a real mailbox (shared inbox), not a distribution list
- Graph API app registration must have **`Mail.Read`** application permission
- Admin consent must be granted for the tenant
- Polling: 3-second intervals, max 15 attempts (~45 seconds)

**Status:** Script implemented, but `Mail.Read` permission not yet granted (returns 403).

### Approach B: Manual Entry (Current Workaround)

Two-step CLI workflow:
```bash
python3 scripts/ebuy/ebuy_auth.py --trigger    # Sends OTP email
python3 scripts/ebuy/ebuy_auth.py --otp <CODE> # Completes auth
```

### Approach C: Fully Automated (Future — requires Approach A)

Single command:
```bash
python3 scripts/ebuy/ebuy_auth.py --auto
```

## Multi-Contract Sync Strategy

### Key Finding: Single Auth → All Contracts (Verified)

The eBuy frontend does NOT re-authenticate when switching contracts. A single Okta
access token (1 hour) can obtain eBuy JWTs for all 6 contracts sequentially by calling
`getuser` with each contract number. No re-authentication or additional OTP needed.

### Sync Flow

1. **Authenticate once**: Okta 2FA → Okta access token (valid 1 hour)
2. **For each contract**: call `getuser` with Okta access token → fresh eBuy JWT (~30 min)
3. **Sync that contract's RFQs** with its JWT
4. **Move to next contract** — call `getuser` again with same Okta token (instant)
5. Total: ~30 min for 6 contracts within a 1-hour Okta window

### Contract Configuration

Each sync config MUST define which contracts to sync:

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

### Cross-Contract Behavior (Verified)

| Behavior | Verified |
|---|---|
| Single Okta auth covers all contracts | Yes |
| No re-authentication when switching contracts | Yes (confirmed from eBuy frontend behavior) |
| Each contract needs its own eBuy JWT via `getuser` | Yes |
| RFQs do NOT overlap across vehicles | Yes (0 shared rfqIds between MAS ↔ OASIS+8A) |
| SINs are vehicle-specific | Yes |
| Cross-contract JWT returns 401 | Yes |

**Deduplication**: Since RFQs don't overlap across contract vehicles, dedup is only
needed for MAS contracts that share the same schedule (e.g., `47QTCA20D001V` and
`47QTCA24D000Z` are both MAS and MAY see the same RFQs).

## Answered Questions

| Question | Answer |
|----------|--------|
| Server-side search? | YES — `POST /seller/searchactiverfqs` works. `matchtype` must be an integer (not string). 0/1=any word, 2=exact phrase. Sorts: CloseDate/IssueDate/Title asc/dsc |
| Multi-contract sync? | Yes — need separate JWT per contract, but same Okta token works |
| JWT refresh? | Yes — call `getuser` again with same Okta access token (1hr window) |
| RFQ listing endpoint? | `GET /seller/activerfqs/{contract}` — returns all active RFQs |
| Notification endpoint? | `GET /seller/notifications/{contract}` — lightweight alerts |
| Attachment download? | `POST /rfq/{rfqId}/rfqAttachment/` with multipart FormData `data` field (JSON-stringified). Verified: PDF, XLSX work. Returns binary with Content-Type + Content-Disposition |
| API discovery? | ~85 endpoints found via JS bundle analysis (see ebuy_data_model.md) |

## Open Questions

1. **Rate limits**: Are there rate limits on the eBuy API? (treat conservatively until known)
2. **SIN → PSC mapping**: Can we map eBuy SIN codes to SAM.gov PSC codes for unified faceting?
3. **Quote tracking scope**: Do we want to track our own quotes (bid management) or just opportunities?
4. **Historical depth**: How far back should the initial backfill go? (274 historical quotes available on MAS alone)
5. **Service account timeline**: When will `ebuy@amivero.com` be created with Graph API Mail.Read permission?
6. **Password-protected RFQs**: Some RFQs have `rfqPassword` — do we need to handle these for attachment access?

## File Structure

```
scripts/ebuy/
├── ebuy_auth.py              # Full auth chain: Okta 2FA → OIDC PKCE → eBuy JWT
├── ebuy_graph_otp.py          # Microsoft Graph OTP reader for automated MFA
├── ebuy_api_explore.py        # API endpoint explorer / response capture tool
├── ebuy_requirements.md       # This document — auth flow, API reference, credentials
├── ebuy_data_model.md         # Data model, sync architecture, search integration
├── api_responses/             # Captured API responses (gitignored)
├── .ebuy_token.json           # Saved JWT for reuse (gitignored)
└── .ebuy_auth_state.json      # MFA state for trigger/verify workflow (gitignored)
```

## Environment Variables

Root `.env`:
```env
# GSA eBuy Integration (Okta 2FA email auth)
EBUY_USERNAME=<ebuy_account_email>
EBUY_PASSWORD=<password>
EBUY_OKTA_AUTH_SERVER_ID=<from GSA Okta — do not commit>
EBUY_OKTA_CLIENT_ID=<from GSA Okta — do not commit>
```

Future backend `config.yml`:
```yaml
ebuy:
  enabled: true
  okta_domain: mfalogin.fas.gsa.gov
  base_url: https://www.ebuy.gsa.gov
  timeout: 30
  max_retries: 3
  rate_limit_delay: 1.0
  otp_method: microsoft_graph  # or 'manual'
  token_refresh_minutes: 25    # refresh before 30-min JWT expiry
  contracts:
    - number: "47QTCA20D001V"
      vehicle: "MAS"
      company: "AMIVERO LLC"
    # ... (see ebuy_data_model.md for full list)
```
