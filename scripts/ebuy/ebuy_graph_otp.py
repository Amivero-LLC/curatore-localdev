"""
Microsoft Graph OTP Email Reader for GSA eBuy Okta MFA

Reads the Okta verification code from the user's email inbox via
Microsoft Graph API (client credentials flow — app-only).

Requirements:
  - MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET in .env
  - Graph app registration must have Mail.Read permission for the target mailbox
  - EBUY_USERNAME in .env (email address whose inbox to read)

Usage:
  # Standalone test — fetch the latest Okta OTP from the inbox
  python3 scripts/ebuy/ebuy_graph_otp.py

  # Used programmatically by ebuy_auth.py
  from ebuy_graph_otp import get_okta_otp
  otp = get_okta_otp(email="dlarrimore@amivero.com", after_timestamp="2026-03-25T02:00:00Z")
"""

import os
import re
import sys
import json
import time
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from project root
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
load_dotenv(PROJECT_ROOT / ".env")

MS_TENANT_ID = os.getenv("MS_TENANT_ID")
MS_CLIENT_ID = os.getenv("MS_CLIENT_ID")
MS_CLIENT_SECRET = os.getenv("MS_CLIENT_SECRET")
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"


def get_graph_token() -> str:
    """Acquire a Microsoft Graph access token via client credentials flow."""
    if not all([MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET]):
        print("ERROR: MS_TENANT_ID, MS_CLIENT_ID, MS_CLIENT_SECRET must be set in .env")
        sys.exit(1)

    token_url = f"https://login.microsoftonline.com/{MS_TENANT_ID}/oauth2/v2.0/token"
    payload = {
        "client_id": MS_CLIENT_ID,
        "client_secret": MS_CLIENT_SECRET,
        "scope": "https://graph.microsoft.com/.default",
        "grant_type": "client_credentials",
    }

    resp = requests.post(token_url, data=payload, timeout=15)
    if resp.status_code != 200:
        print(f"ERROR: Graph token request failed ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    data = resp.json()
    return data["access_token"]


def fetch_latest_okta_email(
    access_token: str,
    mailbox: str,
    after_timestamp: str = None,
    max_retries: int = 10,
    poll_interval: float = 3.0,
) -> dict | None:
    """
    Poll the mailbox for the latest Okta verification email.

    Args:
        access_token: Microsoft Graph bearer token
        mailbox: Email address (UPN) to read from
        after_timestamp: ISO 8601 timestamp — only consider emails after this time
        max_retries: Number of polling attempts
        poll_interval: Seconds between polls

    Returns:
        The email message dict, or None if not found
    """
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }

    # Build OData filter for Okta emails
    # Okta sends from "noreply@okta.com" with subject containing "verification code"
    filter_parts = [
        "(from/emailAddress/address eq 'noreply@okta.com'"
        " or from/emailAddress/address eq 'noreply@login.gov'"
        " or contains(subject, 'verification code')"
        " or contains(subject, 'Verification Code')"
        ")",
    ]

    if after_timestamp:
        filter_parts.append(f"receivedDateTime ge {after_timestamp}")

    odata_filter = " and ".join(filter_parts)

    url = (
        f"{GRAPH_BASE_URL}/users/{mailbox}/messages"
        f"?$filter={odata_filter}"
        f"&$orderby=receivedDateTime desc"
        f"&$top=1"
        f"&$select=subject,body,receivedDateTime,from"
    )

    for attempt in range(1, max_retries + 1):
        print(f"  [Poll {attempt}/{max_retries}] Checking inbox for Okta email...")

        resp = requests.get(url, headers=headers, timeout=15)

        if resp.status_code == 403:
            print(f"ERROR: Graph API returned 403 Forbidden.")
            print(f"  The app registration likely needs Mail.Read permission")
            print(f"  for mailbox: {mailbox}")
            print(f"  Response: {resp.text[:300]}")
            return None

        if resp.status_code != 200:
            print(f"  Warning: Graph API returned {resp.status_code}: {resp.text[:200]}")
            time.sleep(poll_interval)
            continue

        data = resp.json()
        messages = data.get("value", [])

        if messages:
            msg = messages[0]
            print(f"  Found email: {msg.get('subject', 'no subject')}")
            print(f"  From: {msg.get('from', {}).get('emailAddress', {}).get('address')}")
            print(f"  Received: {msg.get('receivedDateTime')}")
            return msg

        if attempt < max_retries:
            time.sleep(poll_interval)

    print(f"  No Okta email found after {max_retries} attempts.")
    return None


def extract_otp_from_email(message: dict) -> str | None:
    """
    Extract the OTP code from an Okta verification email body.

    Okta emails typically contain a 6-digit verification code.
    """
    body = message.get("body", {})
    content = body.get("content", "")
    content_type = body.get("contentType", "text")

    # Strip HTML tags if needed
    if content_type.lower() == "html":
        text = re.sub(r"<[^>]+>", " ", content)
    else:
        text = content

    # Pattern 1: "Your verification code is 123456"
    match = re.search(r"(?:verification|security)\s*code\s*(?:is)?\s*[:\s]*(\d{6})", text, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern 2: "Enter code: 123456" or "Code: 123456"
    match = re.search(r"(?:enter\s*)?code\s*[:\s]+(\d{6})", text, re.IGNORECASE)
    if match:
        return match.group(1)

    # Pattern 3: Standalone 6-digit number (common in OTP emails)
    # Look for a prominent 6-digit number
    matches = re.findall(r"\b(\d{6})\b", text)
    if len(matches) == 1:
        return matches[0]

    # Pattern 4: If multiple 6-digit numbers, try to find one near "code" or "verify"
    if matches:
        for m in re.finditer(r"\b(\d{6})\b", text):
            start = max(0, m.start() - 100)
            context = text[start : m.end()].lower()
            if any(kw in context for kw in ["code", "verify", "verification", "one-time"]):
                return m.group(1)
        # Fallback: return the first one
        return matches[0]

    print(f"  WARNING: Could not extract OTP from email body")
    print(f"  Body preview: {text[:500]}")
    return None


def get_okta_otp(
    email: str = None,
    after_timestamp: str = None,
    max_retries: int = 10,
    poll_interval: float = 3.0,
) -> str | None:
    """
    High-level function: get the Okta OTP code from the user's email.

    Args:
        email: Mailbox to read (defaults to EBUY_USERNAME from .env)
        after_timestamp: Only consider emails received after this ISO 8601 time
        max_retries: Number of polling attempts
        poll_interval: Seconds between polls

    Returns:
        The 6-digit OTP string, or None if not found
    """
    if not email:
        email = os.getenv("EBUY_USERNAME")
    if not email:
        print("ERROR: No email specified and EBUY_USERNAME not set in .env")
        return None

    if not after_timestamp:
        # Default: only look at emails from the last 2 minutes
        after_timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    print(f"\n[Graph OTP] Reading inbox for {email}...")
    print(f"  Looking for emails after: {after_timestamp}")

    token = get_graph_token()
    message = fetch_latest_okta_email(
        token, email, after_timestamp, max_retries, poll_interval
    )

    if not message:
        return None

    otp = extract_otp_from_email(message)
    if otp:
        print(f"  OTP extracted: {otp}")
    return otp


def main():
    print("=" * 60)
    print("Microsoft Graph OTP Reader — Test Mode")
    print("=" * 60)

    email = os.getenv("EBUY_USERNAME")
    if not email:
        print("ERROR: EBUY_USERNAME not set in .env")
        sys.exit(1)

    # For testing, look back at the last 5 minutes
    from datetime import timedelta
    after = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime("%Y-%m-%dT%H:%M:%SZ")

    otp = get_okta_otp(email=email, after_timestamp=after, max_retries=3, poll_interval=2.0)

    if otp:
        print(f"\nOTP Code: {otp}")
    else:
        print("\nNo OTP found. Make sure:")
        print("  1. An Okta verification email was sent recently")
        print("  2. Graph app has Mail.Read permission for this mailbox")
        print(f"  3. Mailbox: {email}")


if __name__ == "__main__":
    main()
