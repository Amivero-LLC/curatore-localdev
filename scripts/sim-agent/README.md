# BD User Simulation Agent ("Growth Team Sim")

Simulates real Amivero Growth/BD team members interacting with Curatore's MCP tools. Each scenario exercises a specific role-based workflow — from BD opportunity scanning to capture analysis to proposal prep — testing the full LLM + MCP + backend pipeline.

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
```

The transport handles the full agentic loop using the official MCP Python SDK: LLM decides tools → execute via MCP → feed results back → repeat until final answer.

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

# Run a specific scenario (persona auto-selected from scenario YAML)
.venv/bin/python run.py --scenario bd_pipeline_cross_reference --verbose

# Dry run (generates persona messages without sending)
.venv/bin/python run.py --scenario bd_weekly_opportunity_scan --dry-run --verbose

# Run all scenarios
.venv/bin/python run.py --scenario all --verbose

# Override the default persona for a scenario
.venv/bin/python run.py --scenario capture_competitive_analysis --persona bd_lead --verbose
```

## Personas

Each persona represents a real role in the GovCon opportunity lifecycle with specific responsibilities, expertise, and communication style.

| Key | Name | Role | Lifecycle Phase |
|-----|------|------|-----------------|
| `svp_growth` | Melissa Myette | SVP of Growth | All phases — gate reviews, strategy |
| `bd_lead` | Sam Poticha | Business Development Lead | Identify & Qualify |
| `capture_lead` | Courtney Porter | Capture Lead | Capture Planning & Win Strategy |
| `proposals_lead` | Mandy Owens | Proposals Lead | Proposal Development |
| `solution_architect` | Russell Dardenne | Technical Solution Architect | Solution Design & Technical Volume |

## Scenarios

Each scenario is tied to a persona and tests a specific workflow with acceptance criteria that diagnose **where** failures occur.

### BD Lead (Sam Poticha)

| Scenario | Description | Beats |
|----------|-------------|-------|
| `bd_pipeline_cross_reference` | Cross-reference open Salesforce opportunities with SAM.gov/APFS updates | 4 |
| `bd_weekly_opportunity_scan` | Monday scan for new SAM.gov opportunities by NAICS and set-aside | 4 |
| `bd_forecast_review` | Review APFS/acquisition forecasts for upcoming DHS opportunities | 3 |

### SVP of Growth (Melissa Myette)

| Scenario | Description | Beats |
|----------|-------------|-------|
| `svp_pipeline_health_review` | Executive pipeline health check — value, stages, deadlines | 4 |
| `svp_win_rate_analysis` | Win/loss trend analysis by agency for resource allocation | 3 |

### Capture Lead (Courtney Porter)

| Scenario | Description | Beats |
|----------|-------------|-------|
| `capture_amendment_tracking` | Monitor active solicitations for amendments and deadline changes | 4 |
| `capture_competitive_analysis` | Build competitive assessment for a DHS opportunity | 4 |

### Proposals Lead (Mandy Owens)

| Scenario | Description | Beats |
|----------|-------------|-------|
| `proposals_rfp_analysis` | Analyze RFP evaluation criteria and submission requirements | 4 |
| `proposals_past_performance_search` | Find relevant past performance references for a proposal | 3 |

### Solution Architect (Russell Dardenne)

| Scenario | Description | Beats |
|----------|-------------|-------|
| `architect_technical_requirements` | Extract and analyze technical requirements from SOW/PWS | 4 |

## Acceptance Criteria & Diagnostics

Each scenario includes acceptance criteria tagged with a **diagnostic category** that identifies where failures originate:

| Diagnostic | What It Means |
|-----------|---------------|
| `mcp` | MCP tool call issue — wrong tool selected, missing parameters, no results |
| `cwr` | CWR function/backend issue — data not available, incorrect metadata |
| `system_prompt` | System prompt issue — response format, tone, or structure not appropriate |
| `llm` | LLM reasoning issue — fails to correlate data, wrong conclusions |

Example acceptance criteria from `bd_pipeline_cross_reference`:
```yaml
acceptance_criteria:
  - criterion: "URLs point to external systems (SAM.gov, Salesforce)"
    diagnostic: "mcp"
    detail: "search_salesforce and search_solicitations must return valid external URLs"

  - criterion: "SAM.gov data is cross-referenced with Salesforce records"
    diagnostic: "llm"
    detail: "LLM must correlate solicitation numbers between systems"
```

## Output

Reports are written to `results/<timestamp>_<scenario>/`:
- `report.md` — Human-readable transcript with reactions, beat assessments, tool calls, and acceptance criteria
- `timeline.json` — Timing, token usage, tool calls per turn, beat assessments
- `raw_responses.json` — Full API responses with tool call details

## Creating New Scenarios

Scenarios define conversation **beats** (goals) with acceptance criteria. The LLM decides which MCP tools to use.

```yaml
name: "My Scenario"
persona: "bd_lead"                         # Which persona runs this scenario
description: |
  Context for what the persona is trying to accomplish.

goal: |
  What success looks like.

conversation_beats:
  - intent: "What the persona wants to know"
    context: "Situational context for the narrator"
    success_signal: "How to assess if the response was adequate"

acceptance_criteria:
  - criterion: "What should be true about the response"
    diagnostic: "mcp|cwr|system_prompt|llm"  # Where the failure would originate
    detail: "Specific technical detail for debugging"

max_turns: 8
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
