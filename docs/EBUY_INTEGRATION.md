# GSA eBuy Integration

## Overview

GSA eBuy is a procurement platform where federal buyers post RFQs/RFPs/RFIs to GSA contract holders. Unlike SAM.gov (public API with API key), eBuy requires authenticated access via Okta 2FA with per-contract JWT tokens.

## Authentication Chain

```
Curatore → GSA Okta (username + password)
         → Email MFA (OTP via Microsoft Graph)
         → OIDC PKCE (authorization code)
         → Okta Access Token (~1 hour)
         → eBuy oktalogin (contract list)
         → eBuy getuser (per-contract JWT ~30 min)
```

Tokens are cached in Redis (DB 2):
- Okta access token: 50 min TTL
- Per-contract eBuy JWTs: 25 min TTL

## Contract-Scoped Sessions

**IMPORTANT:** eBuy sessions are scoped to a single GSA contract. This affects:

### API Access
Each API call requires a JWT obtained for a specific contract number. The sync iterates over configured contracts, getting a new JWT for each one.

### Deep Links
eBuy deep links include a `contractNumber` parameter:
```
https://www.ebuy.gsa.gov/ebuy/seller/prepare-quote/{rfqId}?from=%2Fseller%2Factive-rfqs&contractNumber={contractNumber}
```

**The user must be logged into eBuy with the matching contract for the link to work.** If the user's eBuy session is on a different contract, they will get an error. The Curatore UI displays a confirmation dialog before navigating, informing the user which contract to select.

### Implications for Users
- Users who work on MAS cannot click OASIS+ solicitation links without switching contracts in eBuy
- The `source_contract` field on each solicitation/notice indicates which contract is required
- CWR/MCP responses include the contract number alongside source URLs

## Data Model

| eBuy Concept | Curatore Model | SAM Equivalent |
|---|---|---|
| RFQ/RFP | `EbuySolicitation` | `SamSolicitation` |
| RFI (standalone) | `EbuyNotice` (solicitation_id=NULL) | `SamNotice` (standalone) |
| Amendment | `EbuyNotice` (solicitation_id set) | `SamNotice` (linked) |
| Attachment (SOW, etc.) | `EbuyAttachment` | `SamAttachment` |
| Sync config | `EbuySyncConfig` | `SamSyncConfig` |

## Classification Mapping

| eBuy Field | SAM Equivalent | Ontology Field |
|---|---|---|
| Schedule (MAS, OASIS+) | N/A | `vehicle` |
| SIN (Special Item Number) | NAICS code | N/A (eBuy-specific) |
| Request type (RFQ/RFP/RFI) | Notice type | `solicitation_type` |
| Derived from schedule | Set-aside code | `set_aside_type` |

### Set-Aside Derivation

eBuy doesn't expose set-aside as a field. It's derived from the contract vehicle:

| Schedule | Set-Aside Type |
|----------|---------------|
| OASIS+8A | 8(a) |
| OASIS+SB | Small Business |
| OASIS+UR | Unrestricted |
| OASIS+WO | WOSB |
| MAS | (varies per task order) |

## Sync Schedule

- **Manual**: On-demand via UI or API
- **Hourly**: Beat checks every hour, syncs if due
- **Daily**: Preferred time 1:30 AM EST (6:30 UTC)

## API Endpoints

All endpoints under `/api/v1/connectors/ebuy/`:

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/sync-configs` | GET/POST | List/create sync configs |
| `/sync-configs/{id}` | GET/PATCH/DELETE | Detail/update/delete (cascade) |
| `/sync-configs/{id}/sync` | POST | Trigger sync |
| `/sync-configs/{id}/runs` | GET | Sync run history |
| `/solicitations` | GET | List solicitations |
| `/solicitations/{id}` | GET | Solicitation detail |
| `/notices` | GET | List notices |
| `/notices/{id}` | GET | Notice detail |
| `/attachments` | GET | List attachments |
| `/attachments/{id}/download` | POST | Trigger attachment download |
| `/dashboard` | GET | Dashboard stats |

## Configuration

### config.yml
```yaml
ebuy:
  enabled: true
  username: "${EBUY_USERNAME}"
  password: "${EBUY_PASSWORD}"
  okta_auth_server_id: "${EBUY_OKTA_AUTH_SERVER_ID}"
  okta_client_id: "${EBUY_OKTA_CLIENT_ID}"
  timeout: 60
  max_retries: 3
```

### .env
```
EBUY_USERNAME=ebuy@amivero.com
EBUY_PASSWORD=<password>
EBUY_OKTA_AUTH_SERVER_ID=<okta-auth-server-id>
EBUY_OKTA_CLIENT_ID=<okta-client-id>
```

Microsoft Graph credentials (shared with SharePoint) are required for OTP reading:
```
MS_TENANT_ID=<tenant-id>
MS_CLIENT_ID=<client-id>
MS_CLIENT_SECRET=<client-secret>
```
