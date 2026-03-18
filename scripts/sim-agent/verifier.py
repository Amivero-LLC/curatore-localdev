"""Verifier — independently checks claims in assistant responses via MCP."""

import logging
import re

from mcp.client.session import ClientSession

logger = logging.getLogger(__name__)

# Item types to try when verifying UUIDs, in priority order
_ID_TYPES = [
    "asset",
    "solicitation",
    "notice",
    "salesforce_opportunity",
    "salesforce_account",
    "salesforce_contact",
    "scraped_asset",
]

# Words that are NOT solicitation numbers (common false positives from regex)
_SOL_STOPWORDS = {
    "number", "numbers", "release", "utions", "icitation", "icitations",
    "olution", "olutions", "services", "support", "contract", "amendment",
}


class Verifier:
    """Parses assistant responses for verifiable claims and checks them via MCP."""

    def __init__(self, mcp_session: ClientSession):
        self.session = mcp_session

    async def verify_conversation(self, conversation: list[dict]) -> list[dict]:
        """Verify all assistant responses in a conversation.

        Returns a list of verification results, each with:
          - claim: what was claimed
          - check: what we verified
          - result: "verified", "not_found", "mismatch", "error"
          - detail: explanation
          - diagnostic: "mcp", "cwr", "llm", "system_prompt"
        """
        results = []

        # Deduplicate across turns — only verify each claim once
        seen_uuids = set()
        seen_sol_nums = set()
        seen_sf_check = False
        seen_urls = False

        for msg in conversation:
            if msg["role"] != "assistant":
                continue

            content = msg["content"]

            # Check referenced asset/item IDs (deduplicated)
            new_ids = await self._verify_ids(content, seen_uuids)
            results.extend(new_ids)

            # Check Salesforce data accessibility (once per conversation)
            if not seen_sf_check:
                sf_results = await self._verify_salesforce_refs(content)
                if sf_results:
                    results.extend(sf_results)
                    seen_sf_check = True

            # Check SAM.gov solicitation numbers (deduplicated)
            new_sols = await self._verify_solicitation_numbers(content, seen_sol_nums)
            results.extend(new_sols)

            # Check URLs (once per conversation)
            if not seen_urls:
                url_results = self._verify_urls(content)
                if url_results:
                    results.extend(url_results)
                    seen_urls = True

        return results

    async def _verify_ids(self, content: str, seen: set) -> list[dict]:
        """Find UUIDs in content and verify they exist via get()."""
        results = []
        uuids = set(re.findall(
            r'[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}',
            content, re.IGNORECASE,
        ))

        # Skip already-verified UUIDs
        new_uuids = uuids - seen
        seen.update(new_uuids)

        for uid in list(new_uuids)[:10]:
            uid_lower = uid.lower()
            try:
                found_type = None
                for item_type in _ID_TYPES:
                    result = await self.session.call_tool(
                        "get", {"item_type": item_type, "item_id": uid_lower}
                    )
                    text = _extract_text(result)
                    if "not found" not in text.lower() and "error" not in text.lower():
                        found_type = item_type
                        break

                if found_type:
                    # Use friendly type name
                    friendly = found_type.replace("salesforce_", "Salesforce ").replace("_", " ")
                    results.append({
                        "claim": f"Referenced {friendly} ID {uid[:12]}...",
                        "check": f"get({found_type}, {uid_lower})",
                        "result": "verified",
                        "detail": f"{friendly} exists",
                        "diagnostic": "mcp",
                    })
                else:
                    results.append({
                        "claim": f"Referenced ID {uid[:12]}...",
                        "check": f"get(all types, {uid_lower})",
                        "result": "not_found",
                        "detail": "ID not found as any item type — possible LLM hallucination",
                        "diagnostic": "llm",
                    })
            except Exception as e:
                results.append({
                    "claim": f"Referenced ID {uid[:12]}...",
                    "check": "get()",
                    "result": "error",
                    "detail": str(e)[:200],
                    "diagnostic": "mcp",
                })

        return results

    async def _verify_salesforce_refs(self, content: str) -> list[dict]:
        """Check if Salesforce data is accessible when referenced."""
        results = []

        sf_indicators = [
            "salesforce", "pipeline", "CRM", "opportunity record",
            "opportunity_url", "salesforce.com", "SF Opp",
        ]
        has_sf_ref = any(ind.lower() in content.lower() for ind in sf_indicators)
        if not has_sf_ref:
            return results

        try:
            result = await self.session.call_tool(
                "search_salesforce",
                {"query": "*", "entity_types": ["opportunity"], "is_open": True, "limit": 3},
            )
            text = _extract_text(result)
            if "error" in text.lower():
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "error",
                    "detail": f"Salesforce search failed: {text[:200]}",
                    "diagnostic": "mcp",
                })
            elif "0 results" in text.lower() or "no results" in text.lower():
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "mismatch",
                    "detail": "No open Salesforce opportunities found — data may not be synced",
                    "diagnostic": "cwr",
                })
            else:
                results.append({
                    "claim": "References Salesforce data",
                    "check": "search_salesforce(query=*, is_open=true)",
                    "result": "verified",
                    "detail": "Salesforce data accessible and contains opportunities",
                    "diagnostic": "mcp",
                })
        except Exception as e:
            results.append({
                "claim": "References Salesforce data",
                "check": "search_salesforce()",
                "result": "error",
                "detail": str(e)[:200],
                "diagnostic": "mcp",
            })

        return results

    async def _verify_solicitation_numbers(self, content: str, seen: set) -> list[dict]:
        """Find solicitation numbers and verify they exist."""
        results = []

        # Match realistic solicitation number patterns
        sol_patterns = [
            # Agency-prefixed: 70SBUR26I00000011, 75H71326Q00021
            r'\b(\d{2}[A-Z]{2,6}\d{2}[A-Z]\d{5,})\b',
            # Dash-separated: FY26-0046, W519TC-25-R-0001, 697DCK-25-R-00302
            r'\b([A-Z0-9]{3,8}-\d{2,4}-[A-Z]-\d{3,})\b',
            r'\b(FY\d{2}-\d{4,})\b',
            # PR-prefixed: PR20156685
            r'\b(PR\d{8,})\b',
        ]

        found_sols = set()
        for pattern in sol_patterns:
            matches = re.findall(pattern, content)
            for m in matches:
                m = m.strip()
                if len(m) >= 8 and m.lower() not in _SOL_STOPWORDS:
                    found_sols.add(m)

        # Skip already-verified
        new_sols = found_sols - seen
        seen.update(new_sols)

        for sol_num in list(new_sols)[:5]:
            try:
                result = await self.session.call_tool(
                    "search_solicitations",
                    {"keyword": sol_num, "limit": 1},
                )
                text = _extract_text(result)
                if "0 results" in text.lower() or "no results" in text.lower():
                    results.append({
                        "claim": f"Referenced solicitation {sol_num}",
                        "check": f"search_solicitations(keyword={sol_num})",
                        "result": "not_found",
                        "detail": "Solicitation number not found in system",
                        "diagnostic": "llm",
                    })
                else:
                    results.append({
                        "claim": f"Referenced solicitation {sol_num}",
                        "check": f"search_solicitations(keyword={sol_num})",
                        "result": "verified",
                        "detail": "Solicitation exists in system",
                        "diagnostic": "mcp",
                    })
            except Exception as e:
                results.append({
                    "claim": f"Referenced solicitation {sol_num}",
                    "check": "search_solicitations()",
                    "result": "error",
                    "detail": str(e)[:200],
                    "diagnostic": "mcp",
                })

        return results

    def _verify_urls(self, content: str) -> list[dict]:
        """Check that URLs in responses point to expected external systems."""
        results = []
        urls = re.findall(r'https?://[^\s)\]>"\']+', content)

        if not urls:
            return results

        valid_domains = [
            "sam.gov", "amivero.my.salesforce.com",
            "usaspending.gov", "apfs-cloud.dhs.gov",
        ]

        external_count = 0
        internal_count = 0
        for url in urls[:20]:
            is_external = any(domain in url.lower() for domain in valid_domains)
            if is_external:
                external_count += 1
            elif "localhost" in url or "127.0.0.1" in url:
                internal_count += 1

        if external_count > 0:
            results.append({
                "claim": f"Provided {external_count} external URL(s)",
                "check": "URL domain validation",
                "result": "verified",
                "detail": f"{external_count} URLs point to known external systems",
                "diagnostic": "mcp",
            })

        if internal_count > 0:
            results.append({
                "claim": f"Provided {internal_count} internal URL(s)",
                "check": "URL domain validation",
                "result": "mismatch",
                "detail": f"{internal_count} URLs point to localhost — not useful for the user",
                "diagnostic": "system_prompt",
            })

        return results


def _extract_text(result) -> str:
    """Extract text content from an MCP tool result."""
    parts = []
    for block in result.content:
        if hasattr(block, "text"):
            parts.append(block.text)
        else:
            parts.append(str(block))
    return "\n".join(parts)
