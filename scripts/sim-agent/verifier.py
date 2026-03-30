"""Verifier — independently checks claims in assistant responses via MCP."""

import json
import logging
import re
from datetime import datetime, timezone

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

# ---------------------------------------------------------------------------
# data_quality diagnostic — field requirements per search tool
# ---------------------------------------------------------------------------

_FIELD_REQUIREMENTS = {
    "search_solicitations": {
        "label": "solicitation",
        "expected_fields": ["agency", "solicitation_number", "source_url", "type"],
        "ontology_fields": ["class", "domain", "agency"],
    },
    "search_notices": {
        "label": "notice",
        "expected_fields": ["agency", "notice_type", "posted_date"],
        "ontology_fields": ["class", "domain"],
    },
    "search_forecasts": {
        "label": "forecast",
        "expected_fields": [
            "agency_name", "naics_codes", "fiscal_year",
            "estimated_award_quarter", "source_url",
        ],
        "ontology_fields": [],
    },
    "search_salesforce": {
        "label": "Salesforce record",
        "expected_fields": ["stage_name", "close_date"],
        "ontology_fields": ["agency"],
    },
    "search_assets": {
        "label": "asset",
        "expected_fields": ["content_type"],
        "ontology_fields": ["class", "domain"],
    },
}

# Max items to inspect per re-executed query
_MAX_INSPECT_ITEMS = 10
# Max re-executions per search tool type
_MAX_REEXEC_PER_TOOL = 2


def _parse_items(text: str) -> list[dict]:
    """Parse tool response text into a list of item dicts.

    Handles both pipe-separated (``Key: Val | Key: Val``) and
    newline-separated (``Key: Val\\n``) key-value formats produced by
    Curatore's MCP search tools.
    """
    items: list[dict] = []
    parts = re.split(r'###\s+\d+\.\s+', text)

    for part in parts[1:]:  # skip the "Found N …" header
        item: dict[str, str] = {}
        lines = part.strip().split('\n')
        if not lines:
            continue

        item['title'] = lines[0].strip()

        for line in lines[1:]:
            line = line.strip()
            if not line:
                continue
            segments = line.split(' | ') if ' | ' in line else [line]
            for segment in segments:
                segment = segment.strip()
                if ':' not in segment:
                    continue
                key, _, value = segment.partition(':')
                key = key.strip().lower().replace(' ', '_')
                value = value.strip()
                if key and value:
                    item[key] = value

        if item.get('title'):
            items.append(item)

    return items


def _parse_date(value: str) -> datetime:
    """Best-effort ISO-ish date parse.  Always returns timezone-aware UTC."""
    value = value.strip().replace('Z', '+00:00')
    for fmt in (None, '%Y-%m-%d'):
        try:
            if fmt is None:
                dt = datetime.fromisoformat(value)
            else:
                dt = datetime.strptime(value, fmt)
            # Ensure timezone-aware for safe comparison with utcnow
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except (ValueError, TypeError):
            continue
    raise ValueError(f"Unparseable date: {value}")


class Verifier:
    """Parses assistant responses for verifiable claims and checks them via MCP."""

    def __init__(self, mcp_session: ClientSession):
        self.session = mcp_session

    async def verify_conversation(
        self,
        conversation: list[dict],
        tool_calls: list[dict] | None = None,
    ) -> list[dict]:
        """Verify all assistant responses in a conversation.

        Returns a list of verification results, each with:
          - claim: what was claimed
          - check: what we verified
          - result: "verified", "not_found", "mismatch", "error"
          - detail: explanation
          - diagnostic: "mcp", "cwr", "llm", "system_prompt", "data_quality"
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

        # Data quality — re-execute search queries and inspect returned data
        if tool_calls:
            dq_results = await self._verify_data_quality(tool_calls)
            results.extend(dq_results)

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


    # ------------------------------------------------------------------
    # data_quality diagnostic methods
    # ------------------------------------------------------------------

    async def _verify_data_quality(self, tool_calls: list[dict]) -> list[dict]:
        """Re-execute search queries independently and inspect returned data.

        Acts as an independent "judge" — makes its own API calls with the
        same parameters the LLM used, then checks the actual data for:
        1. Field completeness (are expected fields populated?)
        2. Ontology namespace presence
        3. Status / date consistency
        4. Filter correctness (do results honour the query filters?)
        """
        results: list[dict] = []
        reexec_counts: dict[str, int] = {}

        for tc in tool_calls:
            tool_name = tc.get("tool", "")
            if tool_name not in _FIELD_REQUIREMENTS:
                continue
            if reexec_counts.get(tool_name, 0) >= _MAX_REEXEC_PER_TOOL:
                continue

            reqs = _FIELD_REQUIREMENTS[tool_name]
            args = dict(tc.get("arguments", {}))
            args["limit"] = min(int(args.get("limit", 5)), _MAX_INSPECT_ITEMS)

            try:
                mcp_result = await self.session.call_tool(tool_name, args)
                text = _extract_text(mcp_result)
            except Exception as e:
                results.append({
                    "claim": f"Data quality check for {reqs['label']}s",
                    "check": f"{tool_name} re-execution",
                    "result": "error",
                    "detail": str(e)[:200],
                    "diagnostic": "data_quality",
                })
                continue

            reexec_counts[tool_name] = reexec_counts.get(tool_name, 0) + 1

            if "error" in text.lower()[:100]:
                results.append({
                    "claim": f"Data quality check for {reqs['label']}s",
                    "check": f"{tool_name}(…)",
                    "result": "error",
                    "detail": f"Re-execution returned error: {text[:200]}",
                    "diagnostic": "data_quality",
                })
                continue

            items = _parse_items(text)
            if not items:
                logger.debug("No parseable items from %s", tool_name)
                continue

            # --- 1. Field completeness ---
            results.extend(
                self._check_field_completeness(items, tool_name, reqs)
            )

            # --- 2. Ontology namespace ---
            results.extend(
                self._check_ontology(items, tool_name, reqs)
            )

            # --- 3. Status / date consistency ---
            results.extend(
                self._check_consistency(items, tool_name, reqs)
            )

            # --- 4. Filter correctness ---
            results.extend(
                self._check_filter_correctness(items, args, tool_name, reqs)
            )

        return results

    def _check_field_completeness(
        self, items: list[dict], tool_name: str, reqs: dict,
    ) -> list[dict]:
        """Check that expected fields are populated on returned items."""
        missing_counts: dict[str, int] = {}
        for field in reqs["expected_fields"]:
            count = sum(1 for item in items if not item.get(field))
            if count > 0:
                missing_counts[field] = count

        if missing_counts:
            summary = ", ".join(
                f"{f} ({c}/{len(items)})" for f, c in missing_counts.items()
            )
            return [{
                "claim": f"Field completeness for {reqs['label']}s",
                "check": f"{tool_name} — {len(items)} items inspected",
                "result": "mismatch",
                "detail": f"Missing fields: {summary}",
                "diagnostic": "data_quality",
            }]

        return [{
            "claim": f"Field completeness for {reqs['label']}s",
            "check": f"{tool_name} — {len(items)} items inspected",
            "result": "verified",
            "detail": f"All expected fields present across {len(items)} items",
            "diagnostic": "data_quality",
        }]

    def _check_ontology(
        self, items: list[dict], tool_name: str, reqs: dict,
    ) -> list[dict]:
        """Check that ontology namespace fields are populated."""
        required_onto = reqs.get("ontology_fields", [])
        if not required_onto:
            return []

        items_with_ontology = 0
        missing_onto: dict[str, int] = {}

        for item in items:
            ontology_text = item.get("ontology", "")
            if not ontology_text:
                continue
            items_with_ontology += 1
            for field in required_onto:
                if not re.search(
                    rf'\b{re.escape(field)}\s*:', ontology_text, re.IGNORECASE
                ):
                    missing_onto[field] = missing_onto.get(field, 0) + 1

        if items_with_ontology == 0:
            return [{
                "claim": f"Ontology metadata for {reqs['label']}s",
                "check": f"{tool_name} — {len(items)} items inspected",
                "result": "mismatch",
                "detail": f"0/{len(items)} items have ontology namespace",
                "diagnostic": "data_quality",
            }]

        # Partial ontology coverage — some items missing entirely
        if items_with_ontology < len(items):
            missing_count = len(items) - items_with_ontology
            detail = (
                f"{items_with_ontology}/{len(items)} items have ontology "
                f"({missing_count} missing entirely)"
            )
            if missing_onto:
                summary = ", ".join(
                    f"{f} ({c} missing)" for f, c in missing_onto.items()
                )
                detail += f"; incomplete fields on those present: {summary}"
            return [{
                "claim": f"Ontology metadata for {reqs['label']}s",
                "check": (
                    f"{tool_name} — "
                    f"{items_with_ontology}/{len(items)} items with ontology"
                ),
                "result": "mismatch",
                "detail": detail,
                "diagnostic": "data_quality",
            }]

        if missing_onto:
            summary = ", ".join(
                f"{f} ({c} missing)" for f, c in missing_onto.items()
            )
            return [{
                "claim": f"Ontology completeness for {reqs['label']}s",
                "check": (
                    f"{tool_name} — "
                    f"{items_with_ontology}/{len(items)} items with ontology"
                ),
                "result": "mismatch",
                "detail": f"Incomplete ontology: {summary}",
                "diagnostic": "data_quality",
            }]

        return [{
            "claim": f"Ontology metadata for {reqs['label']}s",
            "check": (
                f"{tool_name} — "
                f"{items_with_ontology}/{len(items)} items with ontology"
            ),
            "result": "verified",
            "detail": "Ontology fields present and complete",
            "diagnostic": "data_quality",
        }]

    def _check_consistency(
        self, items: list[dict], tool_name: str, reqs: dict,
    ) -> list[dict]:
        """Check logical consistency (e.g. status vs close_date)."""
        results: list[dict] = []

        if tool_name not in ("search_solicitations", "search_notices"):
            return results

        now = datetime.now(timezone.utc)
        stale_active = 0
        checked = 0

        for item in items:
            status = (item.get("status") or "").lower()
            close_str = item.get("close_date") or item.get("response_deadline") or ""
            if status != "active" or not close_str:
                continue
            try:
                close_dt = _parse_date(close_str)
                checked += 1
                if close_dt < now:
                    stale_active += 1
            except (ValueError, TypeError):
                pass

        if stale_active > 0:
            results.append({
                "claim": "Status consistency for solicitations",
                "check": (
                    f"close_date vs status — "
                    f"{checked} items with parseable dates"
                ),
                "result": "mismatch",
                "detail": (
                    f"{stale_active}/{checked} show status=active "
                    f"but close_date is in the past"
                ),
                "diagnostic": "data_quality",
            })
        elif checked > 0:
            results.append({
                "claim": "Status consistency for solicitations",
                "check": f"{checked} items checked",
                "result": "verified",
                "detail": "No stale active-status solicitations found",
                "diagnostic": "data_quality",
            })

        return results

    def _check_filter_correctness(
        self,
        items: list[dict],
        args: dict,
        tool_name: str,
        reqs: dict,
    ) -> list[dict]:
        """Verify returned data respects the original query filters."""
        results: list[dict] = []
        now = datetime.now(timezone.utc)

        # --- close_date_next_days ---
        next_days = args.get("close_date_next_days")
        if next_days is not None and items:
            violations = 0
            checked = 0
            for item in items:
                close_str = (
                    item.get("close_date")
                    or item.get("response_deadline")
                    or ""
                )
                if not close_str:
                    continue
                try:
                    close_dt = _parse_date(close_str)
                    checked += 1
                    if (close_dt - now).days > int(next_days):
                        violations += 1
                except (ValueError, TypeError):
                    pass

            if violations > 0:
                results.append({
                    "claim": (
                        f"Filter correctness: "
                        f"close_date_next_days={next_days}"
                    ),
                    "check": f"{checked} items with parseable close dates",
                    "result": "mismatch",
                    "detail": (
                        f"{violations}/{checked} items have close_date "
                        f"beyond {next_days} days"
                    ),
                    "diagnostic": "data_quality",
                })
            elif checked > 0:
                results.append({
                    "claim": (
                        f"Filter correctness: "
                        f"close_date_next_days={next_days}"
                    ),
                    "check": f"{checked} items with parseable close dates",
                    "result": "verified",
                    "detail": (
                        f"All {checked} items have close_date "
                        f"within {next_days} days"
                    ),
                    "diagnostic": "data_quality",
                })

        # --- posted_within_days ---
        posted_days = args.get("posted_within_days")
        if posted_days is not None and items:
            violations = 0
            checked = 0
            for item in items:
                posted_str = item.get("posted_date") or ""
                if not posted_str:
                    continue
                try:
                    posted_dt = _parse_date(posted_str)
                    checked += 1
                    if (now - posted_dt).days > int(posted_days) + 1:
                        violations += 1
                except (ValueError, TypeError):
                    pass

            if violations > 0:
                results.append({
                    "claim": (
                        f"Filter correctness: "
                        f"posted_within_days={posted_days}"
                    ),
                    "check": f"{checked} items with parseable posted dates",
                    "result": "mismatch",
                    "detail": (
                        f"{violations}/{checked} items posted more than "
                        f"{posted_days} days ago"
                    ),
                    "diagnostic": "data_quality",
                })
            elif checked > 0:
                results.append({
                    "claim": (
                        f"Filter correctness: "
                        f"posted_within_days={posted_days}"
                    ),
                    "check": f"{checked} items with parseable posted dates",
                    "result": "verified",
                    "detail": (
                        f"All {checked} items posted within "
                        f"{posted_days} days"
                    ),
                    "diagnostic": "data_quality",
                })

        # --- is_open filter for Salesforce ---
        if tool_name == "search_salesforce" and args.get("is_open") and items:
            closed_count = sum(
                1 for item in items
                if (item.get("is_closed") or "").lower() == "true"
            )
            if closed_count > 0:
                results.append({
                    "claim": "Filter correctness: is_open=true",
                    "check": f"{len(items)} items inspected",
                    "result": "mismatch",
                    "detail": (
                        f"{closed_count}/{len(items)} returned items "
                        f"are marked closed"
                    ),
                    "diagnostic": "data_quality",
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
