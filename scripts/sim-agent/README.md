# BD User Simulation Agent ("Growth Team Sim")

Simulates real Amivero Growth/BD team members interacting with Curatore's MCP tools. Each scenario is **goal-driven** — the persona has an objective and the conversation evolves naturally, like a chaos monkey for the BD workflow. After the conversation, a **verifier** independently checks claims against MCP data.

## Architecture

```
scenarios/*.yaml    personas/*.yaml    LiteLLM (narrator)
      \                  |                /
       +-------  Scenario Runner  -------+
                      |
              MCP Agent Transport
           LLM (via LiteLLM proxy)
             ↕ tool-call loop ↕
           MCP Gateway (:8020/mcp)
                      |
              Curatore Backend
                      |
              Verifier (post-run)
         checks claims via same MCP
```

**Flow:**
1. Narrator generates what the persona would type (driven by goal, not scripted)
2. MCP agent transport sends to LLM → LLM picks tools → MCP executes → results fed back → repeat
3. Narrator decides if the persona should keep going or is satisfied
4. After conversation ends, verifier independently checks claims (IDs, URLs, Salesforce records, solicitation numbers) against MCP

## Setup

1. **Ensure services are running:**
   ```bash
   ./scripts/dev-up.sh --with-postgres
   ```

2. **Verify `.env` has LLM and MCP settings** (set by bootstrap):
   ```bash
   OPENAI_API_KEY=...          # LLM provider key
   OPENAI_BASE_URL=...        # LiteLLM proxy URL
   OPENAI_MODEL=...           # Model for the agent (e.g., claude-4-5-sonnet)
   MCP_API_KEY=...            # MCP gateway auth key
   ```

3. **Install dependencies:**
   ```bash
   cd scripts/sim-agent
   python3 -m venv .venv
   .venv/bin/pip install -r requirements.txt
   ```

## Usage

```bash
cd scripts/sim-agent

# List available scenarios and personas
.venv/bin/python run.py --list

# Run a specific scenario
.venv/bin/python run.py --scenario bd_pipeline_cross_reference --verbose

# Dry run (generates persona messages without sending)
.venv/bin/python run.py --scenario bd_weekly_opportunity_scan --dry-run --verbose

# Run all scenarios
.venv/bin/python run.py --scenario all --verbose

# Override the default persona
.venv/bin/python run.py --scenario capture_competitive_analysis --persona bd_lead --verbose

# Skip verification (faster, conversation only)
.venv/bin/python run.py --scenario bd_forecast_review --no-verify --verbose
```

## Personas

Each persona represents a role in the GovCon opportunity lifecycle.

| Key | Name | Role | Lifecycle Phase |
|-----|------|------|-----------------|
| `svp_growth` | Melissa Myette | SVP of Growth | All phases — gate reviews, strategy |
| `bd_lead` | Sam Poticha | Business Development Lead | Identify & Qualify |
| `capture_lead` | Courtney Porter | Capture Lead | Capture Planning & Win Strategy |
| `proposals_lead` | Mandy Owens | Proposals Lead | Proposal Development |
| `solution_architect` | Russell Dardenne | Technical Solution Architect | Solution Design & Technical Volume |

## Scenarios

Each scenario gives the persona a **goal** and lets the conversation evolve naturally. No scripted questions.

### BD Lead (Sam Poticha)

| Scenario | Goal |
|----------|------|
| `bd_pipeline_cross_reference` | Cross-reference Salesforce opportunities against SAM.gov for updates |
| `bd_weekly_opportunity_scan` | Find new early-stage SAM.gov postings in Amivero's NAICS codes |
| `bd_forecast_review` | Review DHS acquisition forecasts and check Salesforce coverage |

### SVP of Growth (Melissa Myette)

| Scenario | Goal |
|----------|------|
| `svp_pipeline_health_review` | Executive pipeline health snapshot for CEO brief |
| `svp_win_rate_analysis` | Win/loss trend analysis by agency for resource allocation |

### Capture Lead (Courtney Porter)

| Scenario | Goal |
|----------|------|
| `capture_amendment_tracking` | Monitor active solicitations for amendments and deadline changes |
| `capture_competitive_analysis` | Competitive assessment for a DHS opportunity in capture stage |

### Proposals Lead (Mandy Owens)

| Scenario | Goal |
|----------|------|
| `proposals_rfp_analysis` | Analyze a new RFP for evaluation criteria and submission requirements |
| `proposals_past_performance_search` | Find past performance references for a proposal volume |

### Solution Architect (Russell Dardenne)

| Scenario | Goal |
|----------|------|
| `architect_technical_requirements` | Extract technical requirements from SOW/PWS for solution design |

## Verification

After each conversation, the verifier independently checks claims using the same MCP tools:

| Check | What It Does |
|-------|-------------|
| **Asset/Item IDs** | Calls `get()` to verify referenced UUIDs actually exist |
| **Salesforce references** | Calls `search_salesforce()` to confirm data is accessible |
| **Solicitation numbers** | Calls `search_solicitations()` to verify cited solicitations |
| **URLs** | Validates URLs point to expected external systems (SAM.gov, Salesforce) |

Results are tagged with **diagnostic categories**:

| Diagnostic | What It Means |
|-----------|---------------|
| `mcp` | MCP tool issue — wrong tool, missing parameters, no results |
| `cwr` | CWR function/backend issue — data unavailable or incorrect |
| `system_prompt` | System prompt issue — response format or tone wrong |
| `llm` | LLM reasoning issue — wrong conclusions, failed correlation |

## Output

Reports are written to `results/<timestamp>_<scenario>/`:
- `report.md` — Conversation transcript, persona reactions, verification results
- `timeline.json` — Timing, token usage, tool calls, verification data
- `raw_responses.json` — Full responses with tool call details

## Creating New Scenarios

```yaml
name: "My Scenario"
persona: "bd_lead"
description: |
  Context about what the persona is trying to do and why.

goal: |
  What the persona wants to accomplish. Be specific about the
  information they need but don't script the questions.

acceptance_criteria:
  - criterion: "What should be true about the response"
    diagnostic: "mcp|cwr|system_prompt|llm"
    detail: "Technical detail for debugging"

max_turns: 6
```

## Creating New Personas

```yaml
name: "Full Name"
title: "Job Title"
team: "Growth"
company: "Amivero"

lifecycle_role: |
  Where this person sits in the opportunity lifecycle and what they own.

expertise:
  - Domain knowledge areas

agencies_of_interest: ["DHS", "VA"]

systems_used:
  - "System name (what they use it for)"

communication_style: |
  How this person talks, their tone, what they expect from responses.
```
