#!/usr/bin/env python3
"""
Salesforce API Connectivity Test

Tests OAuth2 client_credentials flow authentication and basic API access
against the Salesforce REST API.

Usage:
    python scripts/salesforce/test_connectivity.py

Requires SALESFORCE_CONSUMER_KEY, SALESFORCE_CONSUMER_SECRET, and
SALESFORCE_DOMAIN to be set in the root .env file.
"""

import os
import sys
from pathlib import Path

import requests
from dotenv import load_dotenv

# Load .env from the repo root
env_path = Path(__file__).resolve().parents[2] / ".env"
load_dotenv(env_path)

CONSUMER_KEY = os.getenv("SALESFORCE_CONSUMER_KEY")
CONSUMER_SECRET = os.getenv("SALESFORCE_CONSUMER_SECRET")
DOMAIN = os.getenv("SALESFORCE_DOMAIN")

TOKEN_URL = f"https://{DOMAIN}/services/oauth2/token"


def authenticate():
    """Authenticate using OAuth2 client_credentials flow."""
    print(f"Authenticating to {DOMAIN} ...")
    print(f"Token endpoint: {TOKEN_URL}")

    resp = requests.post(
        TOKEN_URL,
        data={
            "grant_type": "client_credentials",
            "client_id": CONSUMER_KEY,
            "client_secret": CONSUMER_SECRET,
        },
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"\nAuthentication FAILED (HTTP {resp.status_code})")
        print(f"Response: {resp.text}")
        return None

    token_data = resp.json()
    print(f"\nAuthentication SUCCEEDED")
    print(f"  Instance URL : {token_data.get('instance_url')}")
    print(f"  Token type   : {token_data.get('token_type')}")
    print(f"  Issued at    : {token_data.get('issued_at')}")
    print(f"  Access token : {token_data.get('access_token', '')[:20]}...")
    return token_data


def test_api_versions(instance_url, access_token):
    """Fetch available API versions — a lightweight connectivity check."""
    url = f"{instance_url}/services/data/"
    print(f"\nFetching API versions from {url} ...")

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  FAILED (HTTP {resp.status_code}): {resp.text}")
        return False

    versions = resp.json()
    latest = versions[-1] if versions else None
    print(f"  Available versions: {len(versions)}")
    if latest:
        print(f"  Latest API version: {latest.get('version')} ({latest.get('url')})")
    return True


def test_org_info(instance_url, access_token, api_version):
    """Fetch basic org info to verify data access."""
    url = f"{instance_url}/services/data/{api_version}/query/"
    query = "SELECT Id, Name, OrganizationType, IsSandbox FROM Organization LIMIT 1"
    print(f"\nQuerying Organization info ...")

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": query},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  FAILED (HTTP {resp.status_code}): {resp.text}")
        return False

    records = resp.json().get("records", [])
    if records:
        org = records[0]
        print(f"  Org Name     : {org.get('Name')}")
        print(f"  Org Type     : {org.get('OrganizationType')}")
        print(f"  Is Sandbox   : {org.get('IsSandbox')}")
    return True


def test_sobjects(instance_url, access_token, api_version):
    """List a few available SObjects to confirm data access."""
    url = f"{instance_url}/services/data/{api_version}/sobjects/"
    print(f"\nFetching available SObjects ...")

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  FAILED (HTTP {resp.status_code}): {resp.text}")
        return False

    sobjects = resp.json().get("sobjects", [])
    print(f"  Total SObjects: {len(sobjects)}")
    # Show a handful of commonly useful objects
    notable = {"Account", "Contact", "Opportunity", "Lead", "Case", "Task", "ContentDocument"}
    found = [s["name"] for s in sobjects if s["name"] in notable]
    print(f"  Notable objects available: {', '.join(sorted(found))}")
    return True


def test_opportunities(instance_url, access_token, api_version):
    """Fetch 10 Opportunities to inspect available data."""
    url = f"{instance_url}/services/data/{api_version}/query/"
    query = (
        "SELECT Id, Name, StageName, Amount, CloseDate, AccountId, "
        "Account.Name, OwnerId, Owner.Name, CreatedDate, LastModifiedDate, "
        "Type, LeadSource, Probability, IsClosed, IsWon "
        "FROM Opportunity ORDER BY LastModifiedDate DESC LIMIT 10"
    )
    print(f"\nFetching 10 most recently modified Opportunities ...")

    resp = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        params={"q": query},
        timeout=30,
    )

    if resp.status_code != 200:
        print(f"  FAILED (HTTP {resp.status_code}): {resp.text}")
        return False

    data = resp.json()
    records = data.get("records", [])
    total_size = data.get("totalSize", 0)
    print(f"  Total Opportunities in org: {total_size}")
    print(f"  Showing: {len(records)}")

    for i, opp in enumerate(records, 1):
        account_name = (opp.get("Account") or {}).get("Name", "N/A")
        owner_name = (opp.get("Owner") or {}).get("Name", "N/A")
        amount = opp.get("Amount")
        amount_str = f"${amount:,.2f}" if amount else "N/A"
        print(f"\n  --- Opportunity {i} ---")
        print(f"  Name         : {opp.get('Name')}")
        print(f"  Stage        : {opp.get('StageName')}")
        print(f"  Amount       : {amount_str}")
        print(f"  Close Date   : {opp.get('CloseDate')}")
        print(f"  Account      : {account_name}")
        print(f"  Owner        : {owner_name}")
        print(f"  Type         : {opp.get('Type', 'N/A')}")
        print(f"  Lead Source  : {opp.get('LeadSource', 'N/A')}")
        print(f"  Probability  : {opp.get('Probability', 'N/A')}%")
        print(f"  Closed/Won   : {opp.get('IsClosed')}/{opp.get('IsWon')}")
        print(f"  Last Modified: {opp.get('LastModifiedDate')}")
        print(f"  Id           : {opp.get('Id')}")

    return True


def main():
    # Validate config
    missing = []
    if not CONSUMER_KEY:
        missing.append("SALESFORCE_CONSUMER_KEY")
    if not CONSUMER_SECRET:
        missing.append("SALESFORCE_CONSUMER_SECRET")
    if not DOMAIN:
        missing.append("SALESFORCE_DOMAIN")

    if missing:
        print(f"Missing environment variables: {', '.join(missing)}")
        print(f"Set them in {env_path}")
        sys.exit(1)

    print("=" * 60)
    print("Salesforce API Connectivity Test")
    print("=" * 60)

    # Step 1: Authenticate
    token_data = authenticate()
    if not token_data:
        sys.exit(1)

    instance_url = token_data["instance_url"]
    access_token = token_data["access_token"]

    # Step 2: Check API versions
    if not test_api_versions(instance_url, access_token):
        sys.exit(1)

    # Determine latest API version
    resp = requests.get(
        f"{instance_url}/services/data/",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )
    api_version = resp.json()[-1]["url"]  # e.g. "/services/data/v62.0"

    # Step 3: Org info
    test_org_info(instance_url, access_token, api_version.split("/")[-1])

    # Step 4: List SObjects
    test_sobjects(instance_url, access_token, api_version.split("/")[-1])

    # Step 5: Fetch Opportunities
    test_opportunities(instance_url, access_token, api_version.split("/")[-1])

    print("\n" + "=" * 60)
    print("All connectivity checks PASSED")
    print("=" * 60)


if __name__ == "__main__":
    main()
