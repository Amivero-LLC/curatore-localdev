# OAuth SSO — Microsoft Entra ID Integration

Curatore supports Single Sign-On (SSO) via Microsoft Entra ID (formerly Azure AD) using the OpenID Connect (OIDC) Authorization Code flow. The backend acts as a confidential OIDC client — it exchanges the authorization code for tokens, validates the ID token, and issues its own Curatore JWT. This means the existing JWT auth chain (API keys, delegated auth, token refresh) is completely unchanged.

## Quick Start

### 1. Register an App in Azure Portal

1. Go to **Azure Portal → Entra ID → App registrations → New registration**
2. Name: `Curatore` (or your preferred name)
3. Supported account types: **Single tenant** (your org only)
4. Redirect URI: **Web** platform
   - Local dev: `http://localhost:8000/api/v1/auth/oauth/callback`
   - Production: `https://<your-domain>/api/v1/auth/oauth/callback`
5. Click **Register**

### 2. Create a Client Secret

1. Go to **Certificates & secrets → New client secret**
2. Description: `Curatore SSO`
3. Expiry: Choose based on your rotation policy
4. **Copy the Value immediately** (shown only once)

### 3. Note Your IDs

From the app registration **Overview** page, copy:
- **Application (client) ID** → `OAUTH_MS_CLIENT_ID`
- **Directory (tenant) ID** → `OAUTH_MS_TENANT_ID`
- **Client secret value** (from step 2) → `OAUTH_MS_CLIENT_SECRET`

### 4. Configure Curatore

Add to your root `.env`:

```bash
AUTH_MODE=both                    # or "oauth" for SSO-only
OAUTH_MS_TENANT_ID=your-tenant-id
OAUTH_MS_CLIENT_ID=your-client-id
OAUTH_MS_CLIENT_SECRET=your-client-secret
```

Then regenerate and restart:

```bash
./scripts/generate-env.sh
./scripts/dev-down.sh && ./scripts/dev-up.sh --with-postgres
```

That's it for basic SSO. Users will see a "Sign in with Microsoft" button on the login page.

---

## Authentication Modes

The `AUTH_MODE` setting controls how users authenticate:

| Mode | Password Login | Microsoft SSO | Use Case |
|------|---------------|---------------|----------|
| `basic` | Yes | No | Default, no SSO |
| `both` | Yes | Yes | Transition period — test SSO while keeping passwords |
| `oauth` | No | Yes | Full SSO — password endpoints return 403 |

**Recommended migration path:**
1. Start with `AUTH_MODE=both` to test SSO alongside existing password auth
2. Have users sign in with Microsoft to link their accounts
3. Switch to `AUTH_MODE=oauth` once all users have linked

---

## How the Flow Works

```
Browser                    Curatore Backend              Microsoft Entra ID
  │                              │                              │
  │  Click "Sign in with         │                              │
  │  Microsoft"                  │                              │
  │─────────────────────────────>│                              │
  │                              │                              │
  │  302 Redirect ───────────────│──────────────────────────────>
  │                              │    /authorize (OIDC)         │
  │                              │                              │
  │<─────────────────────────────│──────────────────────────────│
  │  Microsoft login page        │                              │
  │                              │                              │
  │  User authenticates ─────────│──────────────────────────────>
  │                              │                              │
  │  302 Redirect with code ─────│<─────────────────────────────│
  │                              │                              │
  │                              │  Exchange code for tokens    │
  │                              │─────────────────────────────>│
  │                              │                              │
  │                              │  ID token + access token     │
  │                              │<─────────────────────────────│
  │                              │                              │
  │                              │  Validate ID token (JWKS)    │
  │                              │  Provision/link user         │
  │                              │  Sync role from claims       │
  │                              │  Sync org memberships        │
  │                              │  Issue Curatore JWT          │
  │                              │                              │
  │  302 Redirect to frontend    │                              │
  │  with Curatore JWT           │                              │
  │<─────────────────────────────│                              │
  │                              │                              │
  │  Store JWT, load user        │                              │
  │  Normal app usage            │                              │
```

Key points:
- The backend is the **confidential client** (has the client secret)
- State parameter stored in Redis (CSRF protection, 10-minute TTL)
- Nonce validated to prevent replay attacks
- JWKS keys cached and auto-rotated
- The backend issues its own Curatore JWT — **the Entra token is never sent to the frontend**

---

## User Provisioning

### Auto-Provisioning (default)

When `OAUTH_AUTO_PROVISION=true` (default), users are automatically created on their first Microsoft login:

1. Backend validates the ID token
2. Looks up user by `external_id` (Entra Object ID) — if found, existing user
3. Looks up user by email — if found, **links** the existing account to Microsoft
4. If not found, **creates** a new user with:
   - `auth_provider=microsoft`
   - `password_hash=NULL` (SSO-only, no password)
   - `is_verified=true` (Microsoft already verified their email)
   - `username` derived from email prefix
   - Role determined by claim mapping (see below)
   - Membership in the default organization

### Account Linking

When `OAUTH_MERGE_ACCOUNTS_BY_EMAIL=true` (default), existing password-based users are automatically linked to their Microsoft account on first SSO login. The match is by email address (case-insensitive). After linking:
- `auth_provider` changes from `local` to `microsoft`
- `external_id` is set to the Entra Object ID
- User can still password-login when `AUTH_MODE=both`

### Disabling Auto-Provisioning

Set `OAUTH_AUTO_PROVISION=false` to require accounts to be pre-created by an admin. Users without an existing account will see an error on SSO login.

---

## Role Management

### Using App Roles (Recommended)

App Roles are defined in the Azure app registration and appear in the `roles` claim of the ID token. This is the cleanest approach — no overage issues, portable across tenants.

**Azure Portal Setup:**

1. Go to **App Registration → App roles → Create app role**
2. Create two roles:

| Display Name | Value | Allowed Member Types |
|---|---|---|
| Admin | `admin` | Users/Groups |
| Member | `member` | Users/Groups |

3. Go to **Enterprise Applications → Your App → Users and Groups**
4. Assign users or security groups to the appropriate role

**Curatore Configuration:**

```bash
ENABLE_OAUTH_ROLE_MANAGEMENT=true   # Sync roles on every login
OAUTH_ROLES_CLAIM=roles             # Read from the "roles" claim
OAUTH_ADMIN_ROLES=admin             # "admin" claim value → Curatore admin
OAUTH_DEFAULT_ROLE=member           # Everyone else gets "member"
```

The ID token will contain:
```json
{
  "roles": ["admin"],
  "email": "user@company.com",
  "oid": "user-object-id"
}
```

### Using Groups for Roles (Alternative)

If you prefer to use Azure AD security groups instead of App Roles:

```bash
OAUTH_ROLES_CLAIM=groups
OAUTH_ADMIN_ROLES=<admin-group-object-id>
```

Note: The `groups` claim contains Object IDs (GUIDs), not display names. This approach has an overage limit of 200 groups per token.

### Access Restriction

To restrict which users can access Curatore at all:

```bash
OAUTH_ALLOWED_ROLES=admin,member
```

When set, only users whose role claim contains one of these values can log in. Users without a matching role see "You are not authorized to access this application." Leave empty to allow all authenticated users.

### Role Sync Behavior

When `ENABLE_OAUTH_ROLE_MANAGEMENT=true`, the user's Curatore role is updated **on every login** based on their current token claims. This means:
- Promoting a user in Azure → they get admin on next login
- Removing a user's App Role in Azure → they're demoted to member on next login
- No manual role management needed in Curatore

Set `ENABLE_OAUTH_ROLE_MANAGEMENT=false` to manage roles manually in Curatore (Azure roles are ignored).

---

## Organization Mapping (Group → Org)

Entra security groups can be mapped to Curatore organizations, automatically granting users org memberships based on their group assignments.

### Azure Portal Setup

1. **Create security groups** for each Curatore org (e.g., "Curatore - Default Org", "Curatore - Growth")
2. **App Registration → Token Configuration** → Add `groups` optional claim to ID token
3. **App Registration → Manifest** → Set `"groupMembershipClaims": "ApplicationGroup"` (recommended — only includes groups assigned to the app, avoids the 200-group overage problem)
4. **Enterprise Applications → Users and Groups** → Assign each security group to the app
5. Copy each group's **Object ID** from Azure AD → Groups

### Curatore Configuration

**Option A: Environment variable (seeded on startup)**

```bash
ENABLE_OAUTH_GROUP_MANAGEMENT=true
OAUTH_GROUP_CLAIM=groups
OAUTH_GROUP_ORG_MAP=<group-oid-1>:default,<group-oid-2>:growth
```

Format: `entra_group_oid:curatore_org_slug` pairs, comma-separated.

On startup, `prestart.py` writes each mapping to `Organization.settings.entra_group_id`. This is idempotent — safe to re-run.

**Option B: Admin UI**

Set the Entra Group ID directly in the organization settings (System → Organizations → Edit → Entra Group ID). This takes precedence over the env var on subsequent startups.

**Option C: Both (recommended)**

Use the env var for initial seeding, then manage via the admin UI. The env var re-seeds on every startup, but only if the org doesn't already have an `entra_group_id` set.

### Sync Behavior

On each OAuth login:
1. Read the `groups` claim from the ID token (array of group Object IDs)
2. Match group OIDs against `Organization.settings.entra_group_id`
3. **Add** memberships for any matching orgs the user isn't already in
4. Existing memberships are **never removed** (additive only, to prevent lockouts)

The ID token with groups looks like:
```json
{
  "roles": ["member"],
  "groups": ["abc123-group-oid", "def456-group-oid"],
  "email": "user@company.com"
}
```

---

## Configuration Reference

### Required (when AUTH_MODE=oauth or both)

| Variable | Description | Example |
|---|---|---|
| `AUTH_MODE` | Authentication mode | `oauth`, `both`, or `basic` |
| `OAUTH_MS_TENANT_ID` | Azure AD tenant ID (GUID) | `f8bacced-a974-4616-b484-d95fbfc92ac7` |
| `OAUTH_MS_CLIENT_ID` | App registration client ID | `7cc68f1a-ee7c-4e78-abfa-702fb5a732e4` |
| `OAUTH_MS_CLIENT_SECRET` | App registration client secret | `CHZ8Q~...` |

### Optional

| Variable | Default | Description |
|---|---|---|
| `OAUTH_SCOPES` | `openid email profile` | OIDC scopes to request |
| `OAUTH_AUTO_PROVISION` | `true` | Auto-create users on first SSO login |
| `OAUTH_MERGE_ACCOUNTS_BY_EMAIL` | `true` | Link existing accounts by email match |
| `ENABLE_OAUTH_ROLE_MANAGEMENT` | `true` | Sync roles from token claims on every login |
| `OAUTH_ROLES_CLAIM` | `roles` | Token claim containing roles |
| `OAUTH_ADMIN_ROLES` | `admin` | Comma-separated claim values that grant admin |
| `OAUTH_ALLOWED_ROLES` | *(empty)* | Restrict login to these roles (empty = allow all) |
| `OAUTH_DEFAULT_ROLE` | `member` | Default role when no claim matches |
| `ENABLE_OAUTH_GROUP_MANAGEMENT` | `false` | Sync org memberships from group claims |
| `OAUTH_GROUP_CLAIM` | `groups` | Token claim containing group OIDs |
| `OAUTH_GROUP_ORG_MAP` | *(empty)* | Group OID → org slug mapping (e.g., `oid:slug,oid:slug`) |

---

## Bootstrap / Fresh Install

### With AUTH_MODE=basic (default)

Standard flow — setup wizard creates admin with password.

### With AUTH_MODE=both

1. Run `./scripts/bootstrap.sh` as normal
2. Admin user created from `ADMIN_EMAIL` / `ADMIN_PASSWORD` env vars
3. Admin logs in with password, configures platform
4. Admin clicks "Sign in with Microsoft" to link their account
5. Other users use Microsoft SSO (auto-provisioned or pre-created)

### With AUTH_MODE=oauth

1. `prestart.py` creates a password-less admin from `ADMIN_EMAIL` with `auth_provider=microsoft`
2. Setup page shows "Sign in with Microsoft" instead of password form
3. Admin completes first login via Microsoft — account linked by email
4. Platform ready for use

---

## Security Considerations

- **Client secret** is never exposed to the frontend — the backend is the confidential client
- **State parameter** prevents CSRF (stored in Redis, 10-minute TTL, single-use)
- **Nonce** prevents token replay attacks
- **JWKS** keys are cached and auto-rotated (24-hour cache)
- **ID tokens** are validated for signature (RS256), issuer, audience, and expiration
- **Tokens in URL** are briefly exposed during the callback redirect — the frontend clears them immediately via `window.history.replaceState`
- **Audit logging** — all OAuth events (authorize, callback success/failure, access denied, account linking, auto-provisioning) are recorded in the `audit_logs` table with IP address, user agent, and timestamp
- **Passwords are never logged** — the audit service never stores passwords, tokens, or secrets

### When AUTH_MODE=oauth

These endpoints return 403:
- `POST /auth/login` — password login disabled
- `POST /auth/register` — self-registration disabled
- `POST /auth/forgot-password` — password reset disabled
- `POST /auth/reset-password` — password reset disabled
- `POST /auth/verify-email` — email verification disabled
- `POST /auth/resend-verification` — verification email disabled

These continue working unchanged:
- API keys (`X-API-Key` header)
- Delegated auth (`X-API-Key` + `X-On-Behalf-Of`)
- JWT token refresh (`POST /auth/refresh`)
- User profile (`GET /auth/me`)

---

## Troubleshooting

| Issue | Fix |
|---|---|
| `AADSTS50011: redirect URI mismatch` | Add `http://localhost:8000/api/v1/auth/oauth/callback` to App Registration → Authentication → Redirect URIs (Web platform) |
| `AUTH_MODE=oauth requires: OAUTH_MS_TENANT_ID` | Set all three OAuth credentials in root `.env` and run `./scripts/generate-env.sh` |
| User gets "member" role despite having admin App Role | Verify App Role value is exactly `admin` (case-sensitive). Check `OAUTH_ADMIN_ROLES` matches. |
| User not in any org after SSO login | Set up group management: `ENABLE_OAUTH_GROUP_MANAGEMENT=true` + `OAUTH_GROUP_ORG_MAP` |
| Groups overage (>200 groups) | Set `"groupMembershipClaims": "ApplicationGroup"` in app manifest to only include app-assigned groups |
| Login works but user redirected back to login | Clear browser localStorage (`curatore_access_token`) and try again |
| OAuth login shows error then redirects | Check backend logs: `docker logs curatore-backend 2>&1 \| grep oauth` |

---

## Related Documentation

- [Platform Overview](OVERVIEW.md) — Architecture and auth flows
- [Configuration](CONFIGURATION.md) — .env vs config.yml philosophy
- [Auth & Access Model](../curatore-backend/docs/AUTH_ACCESS_MODEL.md) — Roles, org context, RBAC
