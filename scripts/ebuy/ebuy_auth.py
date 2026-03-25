"""
GSA eBuy Okta Authentication Chain

Automates the 2-factor email authentication flow for GSA eBuy via Okta.

Flow:
1. POST /api/v1/authn with credentials → stateToken + MFA factor info
2. POST /api/v1/authn/factors/{factorId}/verify → triggers email OTP
3. User enters OTP code from email
4. POST /api/v1/authn/factors/{factorId}/verify with passCode → sessionToken
5. Use sessionToken with PKCE OIDC flow:
   a. Generate code_verifier + code_challenge
   b. GET /oauth2/{authServerId}/v1/authorize with sessionToken → authorization code
   c. POST /oauth2/{authServerId}/v1/token → Okta access_token
6. POST eBuy /seller/oktalogin/ with Okta access_token → eBuy JWT
"""

import os
import sys
import json
import time
import hashlib
import base64
import secrets
import re
from datetime import datetime, timezone
from urllib.parse import urlencode, urlparse, parse_qs
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

# --- Configuration (secrets/IDs from .env, static URLs here) ---
OKTA_DOMAIN = "https://mfalogin.fas.gsa.gov"
OKTA_REDIRECT_URI = "https://www.ebuy.gsa.gov/ebuy/pkce/callback"
OKTA_SCOPES = "openid profile email"

EBUY_BASE_URL = "https://www.ebuy.gsa.gov"
EBUY_OKTALOGIN_URL = f"{EBUY_BASE_URL}/ebuy/api/services/ebuyservices/seller/oktalogin/"
EBUY_GETUSER_URL = f"{EBUY_BASE_URL}/ebuy/api/services/ebuyservices/seller/getuser"

# All credentials and identifiers from .env
EBUY_USERNAME = os.getenv("EBUY_USERNAME")
EBUY_PASSWORD = os.getenv("EBUY_PASSWORD")
OKTA_AUTH_SERVER_ID = os.getenv("EBUY_OKTA_AUTH_SERVER_ID")
OKTA_CLIENT_ID = os.getenv("EBUY_OKTA_CLIENT_ID")

STATE_FILE = Path(__file__).parent / ".ebuy_auth_state.json"


def get_browser_headers():
    """Return headers that mimic a browser session."""
    return {
        "accept": "application/json",
        "accept-language": "en",
        "content-type": "application/json",
        "user-agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/146.0.0.0 Safari/537.36 Edg/146.0.0.0"
        ),
    }


# --- PKCE helpers ---
def generate_pkce():
    """Generate PKCE code_verifier and code_challenge (S256)."""
    code_verifier = secrets.token_urlsafe(43)  # ~57 chars
    digest = hashlib.sha256(code_verifier.encode("ascii")).digest()
    code_challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return code_verifier, code_challenge


# --- Step 1: Primary Authentication ---
def step1_authenticate(session: requests.Session) -> dict:
    missing = [v for v in ["EBUY_USERNAME", "EBUY_PASSWORD", "EBUY_OKTA_AUTH_SERVER_ID", "EBUY_OKTA_CLIENT_ID"]
               if not os.getenv(v)]
    if missing:
        print(f"ERROR: Missing .env variables: {', '.join(missing)}")
        sys.exit(1)

    print(f"\n[Step 1] Authenticating as {EBUY_USERNAME}...")
    url = f"{OKTA_DOMAIN}/api/v1/authn"
    payload = {
        "password": EBUY_PASSWORD,
        "username": EBUY_USERNAME,
        "options": {
            "warnBeforePasswordExpired": True,
            "multiOptionalFactorEnroll": True,
        },
    }
    resp = session.post(url, json=payload, headers=get_browser_headers())
    if resp.status_code != 200:
        print(f"ERROR: Authentication failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    status = data.get("status")
    print(f"  Status: {status}")
    if status == "MFA_REQUIRED":
        print(f"  State token: {data['stateToken'][:20]}...")
        print(f"  Expires: {data.get('expiresAt')}")
    return data


# --- Step 2: Trigger Email MFA ---
def step2_trigger_email_mfa(session: requests.Session, authn_data: dict) -> dict:
    state_token = authn_data["stateToken"]
    factors = authn_data.get("_embedded", {}).get("factors", [])
    email_factor = next((f for f in factors if f["factorType"] == "email"), None)
    if not email_factor:
        print(f"ERROR: No email MFA factor. Available: {[f['factorType'] for f in factors]}")
        sys.exit(1)

    verify_url = email_factor["_links"]["verify"]["href"]
    print(f"\n[Step 2] Triggering email MFA to {email_factor['profile'].get('email')}...")

    resp = session.post(
        f"{verify_url}?rememberDevice=true",
        json={"stateToken": state_token},
        headers=get_browser_headers(),
    )
    if resp.status_code != 200:
        print(f"ERROR: MFA trigger failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    print(f"  Status: {data.get('status')} — Check your email for the OTP code!")
    return data


# --- Step 3: Verify Email Code ---
def _find_verify_url(mfa_data: dict) -> str:
    """Extract verify URL from MFA_CHALLENGE response."""
    # _links.next is the primary location in MFA_CHALLENGE responses
    next_link = mfa_data.get("_links", {}).get("next", {})
    if isinstance(next_link, dict) and next_link.get("href"):
        return next_link["href"]
    if isinstance(next_link, list) and next_link:
        return next_link[0].get("href", "")
    # Fallback: _embedded.factor._links.verify
    factor = mfa_data.get("_embedded", {}).get("factor", {})
    vl = factor.get("_links", {}).get("verify", {})
    if isinstance(vl, dict) and vl.get("href"):
        return vl["href"]
    return ""


def step3_verify_email_code(session: requests.Session, mfa_data: dict, passcode: str) -> dict:
    state_token = mfa_data["stateToken"]
    verify_url = _find_verify_url(mfa_data)
    if not verify_url:
        print(f"ERROR: Could not find verify URL. Response: {json.dumps(mfa_data, indent=2)[:500]}")
        sys.exit(1)

    print(f"\n[Step 3] Verifying email code...")
    resp = session.post(
        f"{verify_url}?rememberDevice=true",
        json={"stateToken": state_token, "passCode": passcode},
        headers=get_browser_headers(),
    )
    if resp.status_code != 200:
        print(f"ERROR: Verification failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    status = data.get("status")
    if status != "SUCCESS":
        print(f"ERROR: Unexpected status: {status}")
        print(f"  Response: {json.dumps(data, indent=2)[:500]}")
        sys.exit(1)

    session_token = data["sessionToken"]
    print(f"  Session token obtained: {session_token[:20]}...")
    return data


# --- Step 4: OIDC PKCE Authorization ---
def step4_oidc_authorize(session: requests.Session, session_token: str) -> tuple:
    """
    Use the Okta sessionToken to perform the OIDC Authorization Code + PKCE flow.
    Returns (authorization_code, code_verifier).
    """
    print(f"\n[Step 4] OIDC PKCE Authorization...")
    code_verifier, code_challenge = generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    params = {
        "client_id": OKTA_CLIENT_ID,
        "response_type": "code",
        "scope": OKTA_SCOPES,
        "redirect_uri": OKTA_REDIRECT_URI,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
        "sessionToken": session_token,
    }

    authorize_url = f"{OKTA_DOMAIN}/oauth2/{OKTA_AUTH_SERVER_ID}/v1/authorize?{urlencode(params)}"

    # Make the request but DON'T follow the redirect to the callback URL
    # (it would fail since that's a client-side route)
    resp = session.get(authorize_url, allow_redirects=False)
    print(f"  Authorize status: {resp.status_code}")

    if resp.status_code == 302:
        location = resp.headers.get("Location", "")
        print(f"  Redirect: {location[:100]}...")

        parsed = urlparse(location)
        qs = parse_qs(parsed.query)
        auth_code = qs.get("code", [None])[0]
        returned_state = qs.get("state", [None])[0]

        if not auth_code:
            print(f"ERROR: No authorization code in redirect. Location: {location}")
            sys.exit(1)

        if returned_state != state:
            print(f"WARNING: State mismatch! Expected {state[:20]}, got {returned_state[:20]}")

        print(f"  Authorization code: {auth_code[:20]}...")
        return auth_code, code_verifier
    else:
        print(f"ERROR: Expected 302, got {resp.status_code}")
        print(f"  Body: {resp.text[:500]}")
        sys.exit(1)


# --- Step 5: Exchange Code for Okta Access Token ---
def step5_exchange_code(session: requests.Session, auth_code: str, code_verifier: str) -> str:
    """Exchange the authorization code for an Okta access token."""
    print(f"\n[Step 5] Exchanging code for Okta access token...")

    token_url = f"{OKTA_DOMAIN}/oauth2/{OKTA_AUTH_SERVER_ID}/v1/token"
    payload = {
        "grant_type": "authorization_code",
        "code": auth_code,
        "client_id": OKTA_CLIENT_ID,
        "redirect_uri": OKTA_REDIRECT_URI,
        "code_verifier": code_verifier,
    }

    headers = get_browser_headers()
    headers["content-type"] = "application/x-www-form-urlencoded"

    resp = session.post(token_url, data=payload, headers=headers)
    if resp.status_code != 200:
        print(f"ERROR: Token exchange failed ({resp.status_code}): {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()
    access_token = data.get("access_token")
    print(f"  Token type: {data.get('token_type')}")
    print(f"  Expires in: {data.get('expires_in')}s")
    print(f"  Scopes: {data.get('scope')}")
    print(f"  Access token: {access_token[:30]}...({len(access_token)} chars)")
    return access_token


# --- Step 6: eBuy Login with Okta Token ---
def step6_ebuy_login(session: requests.Session, okta_access_token: str, contract_number: str = None) -> dict:
    """
    Two-phase eBuy login:
    1. POST seller/oktalogin/ with oktatoken → contract list
    2. POST seller/getuser with oktatoken + contractnumber → eBuy JWT
    """
    # Phase 1: oktalogin — get available contracts
    print(f"\n[Step 6a] eBuy oktalogin — retrieving contracts...")

    headers = get_browser_headers()
    headers["content-type"] = "text/plain"
    headers["referer"] = f"{EBUY_BASE_URL}/ebuy/pkce/callback"

    payload = json.dumps({"oktatoken": okta_access_token, "token": ""})
    resp = session.post(EBUY_OKTALOGIN_URL, data=payload, headers=headers, timeout=30)
    if resp.status_code != 200:
        print(f"ERROR: eBuy oktalogin failed ({resp.status_code}): {resp.text[:500]}")
        sys.exit(1)

    data = resp.json()
    response = data.get("response", {})
    print(f"  RC: {response.get('rc')}, Message: {response.get('message')}")

    contracts = response.get("sellerContractInfoList", [])
    if contracts:
        print(f"  Available contracts:")
        for c in contracts:
            print(f"    {c['contractNumber']} - {c.get('companyName')} ({c.get('contractVehicle', '').strip()})")

    # If token came back directly (single contract?), we're done
    if response.get("token"):
        print(f"\n  eBuy JWT obtained: {response['token'][:50]}...")
        return data

    # Phase 2: getuser — select contract and get JWT
    if not contract_number:
        contract_number = contracts[0]["contractNumber"] if contracts else None
    if not contract_number:
        print("ERROR: No contracts available to select")
        sys.exit(1)

    print(f"\n[Step 6b] eBuy getuser — selecting contract {contract_number}...")

    headers2 = get_browser_headers()
    headers2["content-type"] = "application/json"
    headers2["referer"] = f"{EBUY_BASE_URL}/ebuy/"

    payload2 = json.dumps({
        "contractnumber": contract_number,
        "password": None,
        "oktatoken": okta_access_token,
    })

    resp2 = session.post(EBUY_GETUSER_URL, data=payload2, headers=headers2, timeout=30)
    if resp2.status_code != 200:
        print(f"ERROR: eBuy getuser failed ({resp2.status_code}): {resp2.text[:500]}")
        sys.exit(1)

    data2 = resp2.json()
    response2 = data2.get("response", {})
    print(f"  RC: {response2.get('rc')}, Message: {response2.get('message')}")

    ebuy_token = response2.get("token")
    if ebuy_token:
        print(f"\n  eBuy JWT obtained: {ebuy_token[:50]}...({len(ebuy_token)} chars)")
    else:
        print(f"\n  Full response: {json.dumps(data2, indent=2)[:1500]}")

    return data2


# --- Test API ---
def test_ebuy_api(token: str):
    """Test the eBuy API with the obtained token."""
    print(f"\n[Test] Making eBuy API call...")
    headers = {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {token}",
        "referer": f"{EBUY_BASE_URL}/ebuy/seller/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }
    test_url = f"{EBUY_BASE_URL}/ebuy/api/services/ebuyservices/seller/rfq/RFI1793576/47QTCA20D001V"
    resp = requests.get(test_url, headers=headers, timeout=30)
    print(f"  Status: {resp.status_code}")
    try:
        data = resp.json()
        print(f"  Response: {json.dumps(data, indent=2)[:1000]}")
    except Exception:
        print(f"  Response: {resp.text[:500]}")


# --- State management for split trigger/verify workflow ---
def save_state(mfa_data: dict, cookies: list):
    state = {
        "mfa_data": mfa_data,
        "cookies": cookies,
        "saved_at": time.time(),
    }
    STATE_FILE.write_text(json.dumps(state, indent=2))
    print(f"  State saved to {STATE_FILE}")


def load_state() -> dict:
    if not STATE_FILE.exists():
        print("ERROR: No saved auth state. Run with --trigger first.")
        sys.exit(1)
    state = json.loads(STATE_FILE.read_text())
    age = time.time() - state.get("saved_at", 0)
    if age > 290:
        print(f"ERROR: State is {age:.0f}s old (expired). Run --trigger again.")
        STATE_FILE.unlink(missing_ok=True)
        sys.exit(1)
    print(f"  Loaded state (age: {age:.0f}s)")
    return state


# --- Main ---
def main():
    import argparse

    parser = argparse.ArgumentParser(description="GSA eBuy Okta Authentication")
    parser.add_argument("--otp", type=str, help="Email OTP code (uses saved state)")
    parser.add_argument("--trigger", action="store_true", help="Trigger OTP email, save state, exit")
    parser.add_argument("--auto", action="store_true", help="Fully automated — reads OTP from email via Microsoft Graph")
    parser.add_argument("--contract", type=str, help="GSA contract number to select")
    args = parser.parse_args()

    print("=" * 60)
    print("GSA eBuy Okta Authentication Chain")
    print("=" * 60)

    session = requests.Session()

    if args.otp:
        # --- VERIFY MODE: use saved state + provided OTP ---
        print("\n[Mode] Verifying OTP with saved state...")
        state = load_state()
        mfa_data = state["mfa_data"]
        for c in state.get("cookies", []):
            session.cookies.set(c["name"], c["value"], domain=c.get("domain", ""))

        verify_data = step3_verify_email_code(session, mfa_data, args.otp)
        session_token = verify_data["sessionToken"]
        STATE_FILE.unlink(missing_ok=True)

    elif args.auto:
        # --- AUTO MODE: full automation via Microsoft Graph OTP reading ---
        from ebuy_graph_otp import get_okta_otp

        print("\n[Mode] Fully automated (Graph OTP reader)")

        authn_data = step1_authenticate(session)
        if authn_data.get("status") == "SUCCESS":
            session_token = authn_data["sessionToken"]
        else:
            # Record timestamp BEFORE triggering MFA so we know when to look
            mfa_trigger_time = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            mfa_data = step2_trigger_email_mfa(session, authn_data)

            # Read OTP from email via Graph API
            passcode = get_okta_otp(
                email=EBUY_USERNAME,
                after_timestamp=mfa_trigger_time,
                max_retries=15,
                poll_interval=3.0,
            )
            if not passcode:
                print("ERROR: Could not read OTP from email via Graph API.")
                print("  Ensure Mail.Read permission is granted for this mailbox.")
                sys.exit(1)

            verify_data = step3_verify_email_code(session, mfa_data, passcode)
            session_token = verify_data["sessionToken"]

    else:
        # --- TRIGGER / INTERACTIVE MODE ---
        authn_data = step1_authenticate(session)

        if authn_data.get("status") == "SUCCESS":
            session_token = authn_data["sessionToken"]
        else:
            mfa_data = step2_trigger_email_mfa(session, authn_data)

            if args.trigger:
                cookies = [{"name": c.name, "value": c.value, "domain": c.domain} for c in session.cookies]
                save_state(mfa_data, cookies)
                print("\n" + "=" * 60)
                print("OTP email sent! Now run:")
                print(f"  python3 {__file__} --otp <CODE>")
                print("=" * 60)
                return

            # Interactive mode
            print("\n" + "=" * 60)
            passcode = input("Enter the verification code from your email: ").strip()
            print("=" * 60)
            verify_data = step3_verify_email_code(session, mfa_data, passcode)
            session_token = verify_data["sessionToken"]

    # Step 4: OIDC authorize
    auth_code, code_verifier = step4_oidc_authorize(session, session_token)

    # Step 5: Exchange for Okta access token
    okta_access_token = step5_exchange_code(session, auth_code, code_verifier)

    # Step 6: eBuy login
    ebuy_data = step6_ebuy_login(session, okta_access_token, args.contract)

    # Extract JWT and test
    ebuy_token = ebuy_data.get("response", {}).get("token")
    if ebuy_token:
        # Save token to file for reuse by other scripts
        token_file = Path(__file__).parent / ".ebuy_token.json"
        token_file.write_text(json.dumps({
            "token": ebuy_token,
            "saved_at": time.time(),
            "contract": args.contract or "47QTCA20D001V",
        }, indent=2))

        print("\n" + "=" * 60)
        print("SUCCESS! eBuy JWT obtained!")
        print(f"  Token: {ebuy_token[:80]}...")
        print(f"  Saved to: {token_file}")
        print("=" * 60)
        test_ebuy_api(ebuy_token)
    else:
        print("\n" + "=" * 60)
        print("eBuy login completed but no JWT in response.")
        print("May need contract selection or additional steps.")
        print("=" * 60)


if __name__ == "__main__":
    main()
