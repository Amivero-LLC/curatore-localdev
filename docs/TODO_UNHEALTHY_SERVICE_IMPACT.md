# TODO: Unhealthy Service Impact Policy

How should Curatore react when external services are unhealthy? This document captures questions and current behavior for a future initiative.

## Questions to Resolve

1. **SharePoint syncs**: Should syncs pre-check Graph API health before starting? Or try anyway and rely on retry logic?
2. **CWR/LLM procedures**: Should CWR procedures that require LLM pre-check LLM health? Or let them fail naturally?
3. **Extraction queue**: Should the extraction queue pause submissions if document-service is unhealthy? (Currently: circuit breaker fast-fails individual requests)
4. **SAM.gov pulls**: Should SAM.gov tasks pre-check API availability? Or try with existing retry logic?
5. **UI warnings**: Should the frontend show warnings on pages that depend on unhealthy services?

## Current Behavior

| Service | Pre-flight Check | Failure Handling |
|---------|-----------------|------------------|
| **LLM** | Checks `llm_service.is_available` (client initialized) | Calls fail naturally; error returned to caller |
| **SharePoint** | None | 3 retries with 30s backoff; fail after exhaustion |
| **Document Service** | None | Circuit breaker: fast-fails with 503 after 3 consecutive failures; auto-recovers after 30s half-open probe |
| **SAM.gov** | None | Rate limiting (1000 calls/day), exponential backoff retries |

## Context

The event-driven `ExternalServiceMonitor` (see `app/core/shared/external_service_monitor.py`) now tracks health status for LLM and SharePoint in real-time. This opens the door for pre-flight checks, but the policy decision of _what to do_ with that information is separate from the monitoring mechanism itself.
