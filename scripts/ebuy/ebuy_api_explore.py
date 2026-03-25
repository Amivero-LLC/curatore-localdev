"""
eBuy API Explorer — Captures response shapes from key endpoints.
Uses the saved JWT from ebuy_auth.py.
"""

import json
import time
from pathlib import Path

import requests

TOKEN_FILE = Path(__file__).parent / ".ebuy_token.json"
OUTPUT_DIR = Path(__file__).parent / "api_responses"
EBUY_API = "https://www.ebuy.gsa.gov/ebuy/api/services/ebuyservices"

CONTRACTS = [
    "47QTCA20D001V",  # MAS - AMIVERO LLC
    "47QTCA24D000Z",  # MAS - STELLA JV, LLC
    "47QRCA25DA081",  # OASIS+8A
    "47QRCA25DS654",  # OASIS+SB
    "47QRCA25DU019",  # OASIS+UR
    "47QRCA25DW124",  # OASIS+WO
]


def load_token() -> str:
    if not TOKEN_FILE.exists():
        print("ERROR: No saved token. Run ebuy_auth.py first.")
        raise SystemExit(1)
    data = json.loads(TOKEN_FILE.read_text())
    age = time.time() - data.get("saved_at", 0)
    print(f"Token age: {age:.0f}s ({age/60:.1f} min)")
    if age > 1700:
        print("WARNING: Token may be expired (>28 min)")
    return data["token"]


def headers(token: str) -> dict:
    return {
        "accept": "application/json, text/plain, */*",
        "authorization": f"Bearer {token}",
        "referer": "https://www.ebuy.gsa.gov/ebuy/seller/",
        "user-agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36",
    }


def fetch_and_save(token: str, name: str, url: str):
    """Fetch an endpoint and save the full response to a file."""
    print(f"\n--- {name} ---")
    print(f"  GET {url}")
    try:
        resp = requests.get(url, headers=headers(token), timeout=30)
        print(f"  Status: {resp.status_code}")

        if resp.status_code != 200:
            print(f"  Error: {resp.text[:300]}")
            return None

        data = resp.json()
        outfile = OUTPUT_DIR / f"{name}.json"
        outfile.write_text(json.dumps(data, indent=2))
        print(f"  Saved to: {outfile}")

        # Print summary
        response = data.get("response", data)
        if isinstance(response, list):
            print(f"  Items: {len(response)}")
        elif isinstance(response, dict):
            for k, v in response.items():
                if isinstance(v, list):
                    print(f"  {k}: {len(v)} items")
                elif isinstance(v, str) and len(v) > 100:
                    print(f"  {k}: ({len(v)} chars)")
                else:
                    print(f"  {k}: {v}")
        return data
    except Exception as e:
        print(f"  Exception: {e}")
        return None


def main():
    token = load_token()
    OUTPUT_DIR.mkdir(exist_ok=True)

    contract = CONTRACTS[0]  # MAS - AMIVERO LLC

    print("=" * 60)
    print(f"eBuy API Explorer — Contract: {contract}")
    print("=" * 60)

    # 1. Active RFQs for primary contract
    active = fetch_and_save(
        token, "activerfqs_MAS",
        f"{EBUY_API}/seller/activerfqs/{contract}",
    )

    # 2. Notifications for primary contract
    fetch_and_save(
        token, "notifications_MAS",
        f"{EBUY_API}/seller/notifications/{contract}",
    )

    # 3. Active quotes for primary contract
    fetch_and_save(
        token, "active_quotes_MAS",
        f"{EBUY_API}/seller/getquotes/a/{contract}",
    )

    # 4. Historical quotes for primary contract
    fetch_and_save(
        token, "historical_quotes_MAS",
        f"{EBUY_API}/seller/getquotes/h/{contract}",
    )

    # 5. Get detail + attachments for a specific RFQ (if we have one)
    if active:
        response = active.get("response", {})
        rfqs = []
        # The response might be a dict of category→rfq_list or a flat list
        if isinstance(response, dict):
            for key, val in response.items():
                if isinstance(val, list):
                    rfqs.extend(val)
        elif isinstance(response, list):
            rfqs = response

        if rfqs:
            # Pick the first RFQ to get its detail
            first_rfq = rfqs[0] if isinstance(rfqs[0], dict) else None
            if first_rfq:
                rfq_id = first_rfq.get("rfqId") or first_rfq.get("oid")
                if rfq_id:
                    # RFQ detail
                    fetch_and_save(
                        token, f"rfq_detail_{rfq_id}",
                        f"{EBUY_API}/seller/rfq/{rfq_id}/{contract}",
                    )

                    # RFQ attachments
                    fetch_and_save(
                        token, f"rfq_attachments_{rfq_id}",
                        f"{EBUY_API}/rfq/{rfq_id}/rfqAttachment/",
                    )

                    # Award info
                    fetch_and_save(
                        token, f"rfq_awardinfo_{rfq_id}",
                        f"{EBUY_API}/seller/rfqawardinfo/{rfq_id}/{contract}",
                    )

    # 6. Search active RFQs
    print(f"\n--- searchactiverfqs ---")
    search_url = f"{EBUY_API}/seller/searchactiverfqs"
    search_body = {
        "contractnumber": contract,
        "query": "",
        "matchtype": "all",
        "sortspec": "CloseDate dsc",
    }
    try:
        resp = requests.post(
            search_url,
            json=search_body,
            headers={**headers(token), "content-type": "application/json"},
            timeout=30,
        )
        print(f"  Status: {resp.status_code}")
        if resp.status_code == 200:
            data = resp.json()
            outfile = OUTPUT_DIR / "searchactiverfqs_MAS.json"
            outfile.write_text(json.dumps(data, indent=2))
            print(f"  Saved to: {outfile}")
        else:
            print(f"  Error: {resp.text[:300]}")
    except Exception as e:
        print(f"  Exception: {e}")

    # 7. Try a couple other contracts to see if they have different RFQs
    for other_contract in CONTRACTS[2:4]:  # OASIS+8A, OASIS+SB
        fetch_and_save(
            token, f"activerfqs_{other_contract}",
            f"{EBUY_API}/seller/activerfqs/{other_contract}",
        )

    print("\n" + "=" * 60)
    print(f"All responses saved to: {OUTPUT_DIR}/")
    print("=" * 60)


if __name__ == "__main__":
    main()
