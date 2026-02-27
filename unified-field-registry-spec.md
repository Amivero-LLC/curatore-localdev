# Unified Field Registry & Ontology Classification — Implementation Spec

## Executive Summary

This spec describes a refactoring of Curatore's metadata field registry to create a **single source of truth** that drives classification, entity extraction, value normalization, indexing, and faceted search. The guiding principle is **"hard upfront, soft on the backend"**: the registry defines a rigorous contract for what data to collect, and once data lands in `search_chunks.metadata` with canonical names and normalized values, search/filtering/faceting work automatically with no per-content-type routing logic.

This work touches three systems:
1. **Ontology classification namespace** — rename `ontology.type` → `ontology.classification`, add materialized path
2. **Enhanced extraction profiles** — upgrade from flat string lists to structured dicts with requirement levels, extraction hints, and source overrides
3. **Facet system consolidation** — the field registry absorbs facet definitions; `facets.yaml` field-routing layer is replaced by canonical field paths

---

## Context: What Exists Today

### Current File Inventory

| File | Role | Status |
|------|------|--------|
| `registry/fields/*.yaml` | Field definitions organized by namespace (sam, sharepoint, document, ontology, etc.) with data_type, indexed, facetable, applicable_content_types, extraction_profiles | Working |
| `registry/namespaces.yaml` | 12 namespaces: source, sharepoint, sam, salesforce, forecast, scrape, sync, file_library, file, document, ontology, custom | Working |
| `registry/document_taxonomy.yaml` | Domain → Category → Type hierarchy (federal_acquisition, contractor_response, HR, finance, etc.) | Working |
| `registry/facets.yaml` | 40+ facets mapping content_type → namespace.field path (e.g., agency facet maps sam_notice → ontology.agency) | Working — **TO BE REPLACED** |
| `registry/source_ontology_mappings.yaml` | Deterministic classification: SAM notice_type → ontology type/phase, forecast → static classification | Working |
| `registry/controlled_vocabularies/*.yaml` | 6 vocabulary files: contract_type, lifecycle_phase, outcome, proposal_volume, security_clearance, vehicle | Working |
| `registry_service.py` (`MetadataRegistryService`) | Loads YAML, seeds DB, merges org overrides, resolves field definitions, taxonomy index/lookup | Working — **NEEDS ENHANCEMENT** |
| `document_extraction.py` | 3-layer extraction: profile fields + common fields + _extra bag | Working — **NEEDS ENHANCEMENT** |
| `facet_reference_service.py` | Alias resolution, fuzzy matching, AI-powered grouping, autocomplete | Working — **PARTIALLY REPLACED** |
| `field_projection.py` | Catalog-driven field projection for search results | Working |
| `validation_service.py` | Consistency checks between builders, YAML defs, and facet mappings | Working — **NEEDS UPDATE** |

### Current Extraction Profiles

8 named profiles exist: Contract, Past Performance, Proposal Response, SOW, Teaming Agreement, Modification, Capability Statement, NDA. Plus `__common__` (topics, capabilities, mentioned_agencies, mentioned_companies, mentioned_people).

**Current format** on field definitions:
```yaml
contract_number:
  namespace: document
  data_type: string
  extraction_profiles:
    - Contract
    - Task Order
    - Modification
```

**Problems with current approach:**
- Profile names are flat strings disconnected from `ontology.classification` values in the taxonomy
- No requirement level (required vs expected vs optional) — all fields treated equally
- No extraction hints to help the LLM find values
- No source override mechanism for dual-sourced fields (e.g., `response_deadline` exists in SAM structured data AND document text)
- Only 8 profiles for 70+ document types in the taxonomy — most types fall through to `__common__` only
- `facets.yaml` routes the same logical field (e.g., "agency") to different physical paths per content_type

---

## Part 1: Ontology Classification Namespace

### Problem

The current `ontology` namespace uses `ontology.type` which collides with `content_type`, `notice_type`, `account_type`, and `document.document_type`. The field stores a flat string with no explicit hierarchy — you can't walk up from "Sources Sought Notice" to "Pre-Solicitation Notices" to "Federal Acquisition" without a taxonomy lookup.

### Changes

Rename and add fields in `registry/fields/ontology.yaml`:

```yaml
# RENAME: ontology.type → ontology.classification
classification:
  namespace: ontology
  data_type: string
  description: "Leaf-node label from document_taxonomy.yaml"
  indexed: true
  facetable: true
  examples: ["Sources Sought Notice", "Contract", "Task Order", "Proposal Response"]

# RENAME: ontology.domain → ontology.classification_domain  
classification_domain:
  namespace: ontology
  data_type: string
  description: "Top-level domain from taxonomy (e.g., Federal Acquisition, Contractor Response)"
  indexed: true
  facetable: true

# RENAME: ontology.category → ontology.classification_category
classification_category:
  namespace: ontology
  data_type: string
  description: "Mid-level category from taxonomy (e.g., Pre-Solicitation Notices, Contract Instruments)"
  indexed: true
  facetable: true

# NEW: ontology.classification_path
classification_path:
  namespace: ontology
  data_type: string
  description: "Materialized taxonomy path for hierarchical queries"
  indexed: true
  facetable: false
  examples: ["federal_acquisition/pre_solicitation_notices/sources_sought_notice"]

# KEEP as-is:
lifecycle_phase:
  namespace: ontology
  data_type: string
  description: "Acquisition lifecycle phase (cross-cutting, not part of hierarchy)"
  indexed: true
  facetable: true
  vocabulary: controlled_vocabularies/lifecycle_phase.yaml
```

### Migration Strategy

1. **Dual-write**: Add new field names alongside old ones. Both `ontology.type` and `ontology.classification` get populated.
2. **Migrate consumers**: Update all code that reads `ontology.type` to read `ontology.classification`.
3. **Backfill**: SQL migration to rename fields in `search_chunks.metadata` JSONB column.
4. **Drop old fields**: Remove `ontology.type`, `ontology.domain`, `ontology.category` once all consumers migrated.

### Files to Change

- `registry/fields/ontology.yaml` — Rename field definitions
- `registry/facets.yaml` — Update facet mappings that reference `ontology_type` → `ontology_classification`
- `registry/source_ontology_mappings.yaml` — Update target field names
- `document_extraction.py` — Update `_sync_ontology_classification()` to write new field names
- `registry_service.py` — Add `classification_path` generation from taxonomy lookup
- CWR tool schemas — Update any hardcoded `ontology.type` references
- Frontend facet filters — Update filter field references

### Path Generation

In `registry_service.py`, after taxonomy lookup, generate the materialized path:

```python
def get_classification_path(self, classification_label: str) -> str | None:
    """Generate materialized path from taxonomy for a classification label.
    
    Example: "Sources Sought Notice" → "federal_acquisition/pre_solicitation_notices/sources_sought_notice"
    """
    taxonomy_entry = self._reverse_taxonomy_index.get(classification_label)
    if not taxonomy_entry:
        return None
    domain_key = slugify(taxonomy_entry['domain'])
    category_key = slugify(taxonomy_entry['category'])
    type_key = slugify(classification_label)
    return f"{domain_key}/{category_key}/{type_key}"
```

This enables hierarchical queries:
```sql
-- Find all pre-solicitation items
WHERE metadata->'ontology'->>'classification_path' LIKE 'federal_acquisition/pre_solicitation_notices/%'

-- Find all federal acquisition items
WHERE metadata->'ontology'->>'classification_path' LIKE 'federal_acquisition/%'
```

---

## Part 2: Enhanced Extraction Profiles

### The Core Idea

**Extraction profile keys MUST match `ontology.classification` values exactly.** This creates the formal bridge between "what is this thing" (classification) and "what fields to extract" (profile lookup).

When an item is classified as `"Task Order"`, the registry finds all fields whose `extraction_profiles` dict contains a `"Task Order"` key. The requirement level tells the LLM how aggressively to look. The `source_overrides` handle dual-source reconciliation at extraction time, not search time.

### New Field Definition Schema

Upgrade `extraction_profiles` from a flat list to a structured dict. The schema change is **backward-compatible** — the registry service should handle both formats during migration.

```yaml
# ═══════════════════════════════════════════════════════
# FULL FIELD DEFINITION SCHEMA (enhanced)
# ═══════════════════════════════════════════════════════

rfp_release_date:
  # ─── IDENTITY ───
  namespace: document
  canonical_name: rfp_release_date
  display_name: "RFP Release Date"
  data_type: date
  description: "Date the solicitation/RFP was officially released or posted"
  
  # ─── EXTRACTION PROFILES (many-to-many with ontology classifications) ───
  # Keys MUST match values in document_taxonomy.yaml leaf nodes
  # These are the ontology.classification values that need this field extracted
  extraction_profiles:
    "Solicitation":
      requirement: expected        # required | expected | optional
      extraction_hints:            # helps LLM find the value in text
        - "release date"
        - "issue date"
        - "posted date"
        - "solicitation date"
    "Sources Sought Notice":
      requirement: optional
      extraction_hints:
        - "anticipated release date"
        - "expected RFP date"
        - "anticipated solicitation date"
    "Amendment":
      requirement: optional
      extraction_hints:
        - "original release date"
        - "amended release date"
    "Pre-Solicitation Notice":
      requirement: optional
      extraction_hints:
        - "expected release"
        - "anticipated posting"
  
  # ─── SOURCE OVERRIDES (dual-source reconciliation) ───
  # When this content_type already has the field from a structured source,
  # use that value instead of (or in addition to) LLM extraction
  source_overrides:
    sam_notice:
      field: sam.posted_date          # Use this field's value instead
      reconciliation: source_wins     # source_wins | extracted_wins | merge
    sam_solicitation:
      field: sam.posted_date
      reconciliation: source_wins
  
  # ─── SEARCH & FACETING ───
  indexed: true                       # Goes into search index
  facetable: true                     # Available as a filter in UI
  facet_type: date_range              # date_range | keyword | numeric_range | boolean
  
  # ─── VOCABULARY (for fields with controlled values) ───
  # vocabulary: null  (dates don't need this)


# ─── EXAMPLE: Field WITH vocabulary ───

ordering_agency:
  namespace: document
  canonical_name: ordering_agency
  display_name: "Ordering Agency"
  data_type: string
  description: "The government agency placing the order or issuing the solicitation"
  
  extraction_profiles:
    "Task Order":
      requirement: expected
      extraction_hints:
        - "ordering agency"
        - "ordering activity"
        - "requiring activity"
    "Delivery Order":
      requirement: expected
    "Award Notice":
      requirement: expected
      extraction_hints:
        - "awarding agency"
        - "contracting agency"
    "Solicitation":
      requirement: expected
      extraction_hints:
        - "issuing agency"
        - "contracting office"
  
  source_overrides:
    sam_notice:
      field: sam.agency
      reconciliation: source_wins
    sam_solicitation:
      field: sam.agency
      reconciliation: source_wins
  
  indexed: true
  facetable: true
  facet_type: keyword
  
  vocabulary:
    reference: controlled_vocabularies/agency.yaml
    normalize_at: index_time           # index_time | query_time | both
    fuzzy_match: true


# ─── EXAMPLE: __common__ field (no extraction_profiles needed) ───

topics:
  namespace: document
  canonical_name: topics
  display_name: "Topics"
  data_type: list[string]
  description: "Key topics and subject areas identified in the document"
  extraction_profiles: "__common__"    # Special value: extracted for ALL classified documents
  indexed: true
  facetable: true
  facet_type: keyword
```

### Requirement Levels

These control both the LLM extraction prompt and post-extraction validation:

| Level | Meaning | LLM Prompt Guidance | Validation |
|-------|---------|-------------------|------------|
| `required` | This field MUST be present for this classification to be valid | "You MUST extract this field. If not found, flag as missing." | Warn if absent |
| `expected` | This field should be present in most documents of this type | "Look for this field. Extract if present." | Note if absent |
| `optional` | This field may or may not be present | "Extract if you find it, but don't force it." | No validation |

### Profile Name Validation

**CRITICAL**: Extraction profile keys must exist in `document_taxonomy.yaml` as leaf-node type labels. Add a validation check in `validation_service.py`:

```python
def validate_extraction_profile_names(self):
    """Ensure all extraction_profiles keys match taxonomy leaf nodes."""
    taxonomy_types = self.registry_service.get_all_taxonomy_types()  # Set of all leaf labels
    
    for field_name, field_def in self.all_fields.items():
        profiles = field_def.get('extraction_profiles', {})
        if profiles == "__common__" or isinstance(profiles, list):
            continue  # Legacy format or __common__
        for profile_name in profiles.keys():
            if profile_name not in taxonomy_types:
                self.errors.append(
                    f"Field '{field_name}' has extraction_profile '{profile_name}' "
                    f"which does not exist in document_taxonomy.yaml"
                )
```

### Backward Compatibility

The registry service must handle both old and new formats during migration:

```python
def get_extraction_fields(self, classification: str, content_type: str) -> dict:
    """Get fields to extract for a given ontology classification.
    
    Returns dict of {field_name: {requirement, extraction_hints, ...}}
    Handles both legacy flat list and new structured dict formats.
    """
    result = {}
    
    for field_name, field_def in self.all_fields.items():
        profiles = field_def.get('extraction_profiles', {})
        
        # Legacy format: flat list of profile names
        if isinstance(profiles, list):
            if classification in profiles:
                result[field_name] = {
                    'requirement': 'expected',  # Default for legacy
                    'extraction_hints': [],
                    'field_def': field_def,
                }
            continue
        
        # __common__ profile: applies to all classifications
        if profiles == "__common__":
            result[field_name] = {
                'requirement': 'expected',
                'extraction_hints': [],
                'field_def': field_def,
                'is_common': True,
            }
            continue
        
        # New format: structured dict
        if classification in profiles:
            profile_config = profiles[classification]
            
            # Check source_overrides — skip extraction if source provides it
            source_overrides = field_def.get('source_overrides', {})
            if content_type in source_overrides:
                override = source_overrides[content_type]
                if override.get('reconciliation') == 'source_wins':
                    continue  # Source system provides this — don't extract
            
            result[field_name] = {
                'requirement': profile_config.get('requirement', 'expected'),
                'extraction_hints': profile_config.get('extraction_hints', []),
                'field_def': field_def,
            }
    
    return result
```

---

## Part 3: Extraction Pipeline Changes

### Changes to `document_extraction.py`

The extraction prompt builder needs to use the enhanced profile data:

```python
def build_extraction_prompt(self, classification: str, content_type: str) -> str:
    """Build tiered extraction prompt from registry.
    
    Groups fields by requirement level so the LLM knows priority.
    """
    fields = self.registry_service.get_extraction_fields(classification, content_type)
    
    required_fields = {k: v for k, v in fields.items() if v['requirement'] == 'required'}
    expected_fields = {k: v for k, v in fields.items() if v['requirement'] == 'expected'}
    optional_fields = {k: v for k, v in fields.items() if v['requirement'] == 'optional'}
    common_fields = {k: v for k, v in fields.items() if v.get('is_common')}
    
    prompt_parts = []
    
    if required_fields:
        prompt_parts.append("REQUIRED FIELDS (you MUST extract these):")
        for name, info in required_fields.items():
            hints = f" (look for: {', '.join(info['extraction_hints'])})" if info['extraction_hints'] else ""
            prompt_parts.append(f"  - {name}: {info['field_def']['description']}{hints}")
    
    if expected_fields:
        prompt_parts.append("\nEXPECTED FIELDS (extract if present):")
        for name, info in expected_fields.items():
            hints = f" (look for: {', '.join(info['extraction_hints'])})" if info['extraction_hints'] else ""
            prompt_parts.append(f"  - {name}: {info['field_def']['description']}{hints}")
    
    if optional_fields:
        prompt_parts.append("\nOPTIONAL FIELDS (extract if you find them, don't force):")
        for name, info in optional_fields.items():
            prompt_parts.append(f"  - {name}: {info['field_def']['description']}")
    
    if common_fields:
        prompt_parts.append("\nCOMMON FIELDS (always extract):")
        for name, info in common_fields.items():
            prompt_parts.append(f"  - {name}: {info['field_def']['description']}")
    
    return "\n".join(prompt_parts)
```

### Source Override Reconciliation

After extraction, reconcile dual-sourced fields. This happens in the indexing step, not the extraction step:

```python
def reconcile_source_overrides(self, extracted_metadata: dict, source_metadata: dict, 
                                content_type: str) -> dict:
    """Apply source_overrides: when a source system already has a field value,
    use it instead of (or merged with) the extracted value.
    
    Args:
        extracted_metadata: Fields extracted by LLM (document.* namespace)
        source_metadata: Fields from source system (sam.*, sharepoint.*, etc.)
        content_type: The content_type of this record
    
    Returns:
        Reconciled metadata dict
    """
    result = dict(extracted_metadata)
    
    for field_name, field_def in self.all_fields.items():
        overrides = field_def.get('source_overrides', {})
        if content_type not in overrides:
            continue
            
        override = overrides[content_type]
        source_field = override['field']  # e.g., "sam.posted_date"
        reconciliation = override.get('reconciliation', 'source_wins')
        
        # Parse namespace.field from source_field
        ns, fname = source_field.split('.', 1)
        source_value = source_metadata.get(ns, {}).get(fname)
        
        if source_value is None:
            continue  # Source doesn't have it — keep extracted value
        
        if reconciliation == 'source_wins':
            result[field_name] = source_value
        elif reconciliation == 'extracted_wins':
            if field_name not in result or result[field_name] is None:
                result[field_name] = source_value
        elif reconciliation == 'merge':
            # For list fields, combine. For scalars, prefer source.
            if isinstance(source_value, list) and isinstance(result.get(field_name), list):
                result[field_name] = list(set(source_value + result.get(field_name, [])))
            else:
                result[field_name] = source_value
    
    return result
```

---

## Part 4: Facet System Consolidation

### What Gets Replaced

`facets.yaml` currently does per-content-type field routing:
```yaml
# CURRENT facets.yaml (to be replaced):
agency:
  display_name: "Agency"
  field_mappings:
    sam_notice: ontology.agency
    sam_solicitation: ontology.agency
    ag_forecast: ontology.agency
    asset: ontology.agency
    salesforce_contact: salesforce.account_name
```

This routing layer exists because different content types store "agency" at different field paths. With the unified registry + source overrides, all content types write agency to the SAME canonical path (`document.ordering_agency` or `ontology.agency`) with the same canonical value. The routing is unnecessary.

### What Survives

1. **Controlled vocabularies** — Still needed. LLMs are messy, source data has variants. But normalization moves from query-time to **index-time**.
2. **Alias resolution on user input** — When a user types "DHS" in a search box, it still needs to resolve to "Department of Homeland Security". But the INDEX already has the canonical value, so this is just on the query input side.
3. **`facet_reference_service.py`** — The alias resolution, fuzzy matching, and autocomplete features survive. What changes is they no longer need to know which field path to query per content_type.

### New Facet Derivation from Field Registry

Instead of a separate `facets.yaml`, facets are derived directly from field definitions:

```python
def get_facetable_fields(self) -> list[dict]:
    """Derive facet definitions from field registry.
    
    Any field with facetable: true becomes a search facet.
    No separate facet definition file needed.
    """
    facets = []
    for field_name, field_def in self.all_fields.items():
        if not field_def.get('facetable'):
            continue
        
        ns = field_def['namespace']
        facets.append({
            'field_path': f"{ns}.{field_name}",
            'display_name': field_def.get('display_name', field_name),
            'facet_type': field_def.get('facet_type', 'keyword'),
            'vocabulary': field_def.get('vocabulary'),
        })
    
    return facets
```

### Migration Path for Facets

1. **Phase 1**: Keep `facets.yaml` working. Add `facetable: true` and `facet_type` to all field definitions that correspond to existing facets.
2. **Phase 2**: Build `get_facetable_fields()` in registry service. Frontend reads facets from registry instead of `facets.yaml`.
3. **Phase 3**: Remove `facets.yaml`. The field registry IS the facet definition.

The exception is `salesforce.account_name` → "agency" mapping — Salesforce stores agency info in a differently-named field. This can be handled with a `facet_alias` property on the field definition:

```yaml
# In salesforce fields:
account_name:
  namespace: salesforce
  facetable: true
  facet_alias: agency  # "Treat this field as the 'agency' facet for this content_type"
```

---

## Part 5: Value Normalization at Index Time

### Current Behavior

The `_VOCAB_FIELD_TO_FACET` mapping in the indexing pipeline already normalizes some extracted values against controlled vocabularies. This pattern is correct — it just needs to be expanded and driven by the field registry.

### New Behavior

Every field with a `vocabulary` property gets normalized at index time:

```python
def normalize_field_value(self, field_name: str, raw_value: str) -> str:
    """Normalize an extracted value against its controlled vocabulary.
    
    Uses the vocabulary reference from the field definition.
    Falls back to raw value if no match found.
    """
    field_def = self.get_field_definition(field_name)
    vocab_config = field_def.get('vocabulary')
    if not vocab_config:
        return raw_value
    
    vocab = self.load_vocabulary(vocab_config['reference'])
    
    # Try exact match first
    if raw_value in vocab.canonical_values:
        return raw_value
    
    # Try alias resolution
    canonical = vocab.resolve_alias(raw_value)
    if canonical:
        return canonical
    
    # Try fuzzy match if enabled
    if vocab_config.get('fuzzy_match'):
        match = vocab.fuzzy_match(raw_value, threshold=0.85)
        if match:
            return match
    
    # No match — return raw value (and optionally flag for review)
    return raw_value
```

### Vocabularies to Add

Current vocabularies: contract_type, lifecycle_phase, outcome, proposal_volume, security_clearance, vehicle.

**New vocabularies needed:**
- `agency.yaml` — Federal agencies with aliases (DHS, DoD, etc.). This is the big one — replaces the agency alias resolution currently in `facet_reference_service.py`.
- `naics.yaml` — NAICS code descriptions (optional — may be too large for YAML)
- `set_aside.yaml` — Set-aside types (SB, WOSB, 8(a), HUBZone, SDVOSB, etc.)

---

## Part 6: Web Library Context Inheritance

Web Libraries (SharePoint doc libraries, file library roots) don't get an ontology classification — they're organizational containers, not business documents. But they carry context that helps classify their children.

### Current Behavior

The LLM classifier already receives `file_library.*` metadata as context when classifying documents. This is implicit.

### Enhancement (Low Priority)

Make context inheritance explicit in the registry:

```yaml
# In a new section of the registry or as part of file_library fields:
context_inheritance:
  file_library:
    library_name:
      patterns:
        - pattern: "* Proposals"
          hints:
            ontology.classification: "Proposal Response"
        - pattern: "* Task Orders"
          hints:
            ontology.classification: "Task Order"
    tags:
      pass_to_classifier: true  # Include library tags as classification context
```

This is **low priority** — the implicit context passing already works. Formalize it only if classification accuracy for library files is poor.

---

## Implementation Order

### Phase 1: Schema Enhancement (Non-Breaking)
**Effort: Small | Risk: Low**

1. Add `facetable`, `facet_type`, `display_name`, `canonical_name` properties to existing field definitions in `registry/fields/*.yaml`
2. Enhance `MetadataRegistryService` to parse new properties (ignore if missing — backward compatible)
3. Add `get_facetable_fields()` method to registry service
4. Add validation in `validation_service.py` for new schema properties
5. **Test**: Existing system works unchanged. New properties are available but not yet consumed.

### Phase 2: Enhanced Extraction Profiles (Non-Breaking)
**Effort: Medium | Risk: Low**

1. Add support for structured `extraction_profiles` dict format in `MetadataRegistryService.get_extraction_fields()`
2. Handle both old (flat list) and new (structured dict) formats
3. Convert existing 8 profiles from flat list to structured dict with requirement levels
4. Add `extraction_hints` to existing profile fields
5. Add `source_overrides` to dual-sourced fields (response_deadline, agency, naics_codes, etc.)
6. Add extraction profile name validation against taxonomy
7. **Test**: Extraction still works with both old and new format. New format fields get tiered prompts.

### Phase 3: Extraction Pipeline Enhancement
**Effort: Medium | Risk: Medium**

1. Update `document_extraction.py` to use `build_extraction_prompt()` with tiered fields
2. Implement `reconcile_source_overrides()` in the indexing pipeline
3. Add vocabulary normalization at index time for fields with `vocabulary` property
4. **Test**: Extraction produces same fields but with better prompts. Source override reconciliation works for SAM notice fields.

### Phase 4: Ontology Namespace Rename
**Effort: Medium | Risk: Medium-High (breaking change)**

1. Add new field names (`classification`, `classification_domain`, `classification_category`, `classification_path`) to `ontology.yaml`
2. Dual-write: `_sync_ontology_classification()` writes both old and new field names
3. Generate `classification_path` from taxonomy lookup
4. Migrate all consumers (search queries, facet filters, CWR tools) to new field names
5. Backfill migration for existing `search_chunks.metadata`
6. Drop old field names
7. **Test**: All search/filter functionality works with new field names. Hierarchical path queries work.

### Phase 5: Facet Consolidation
**Effort: Medium | Risk: Medium**

1. Frontend reads facet definitions from `get_facetable_fields()` instead of `facets.yaml`
2. Add `facet_alias` support for cross-namespace field mapping (salesforce.account_name → agency)
3. Move agency alias resolution from `facet_reference_service.py` to `controlled_vocabularies/agency.yaml`
4. Remove `facets.yaml` field routing layer
5. **Test**: All faceted search works. Alias resolution still works for user input.

### Phase 6: Expand Profile Coverage
**Effort: Large (but incremental) | Risk: Low**

Add extraction profiles for high-value document types currently falling through to `__common__` only:
- Task Order (contract_number, ordering_agency, ceiling_value, period_of_performance, parent_contract)
- Award Notice (awardee, contract_value, effective_date)
- Sources Sought Notice (anticipated_release_date, response_deadline, naics_codes)
- QASP (surveillance_methods, frequency, quality_standards)
- White Paper (author, topic_area, recommendations)
- Status Report (reporting_period, milestones, risks)
- Proposal Response — split into distinct volume profiles (Technical, Management, Past Performance, Cost)

Each profile is a small addition to existing field YAML files — add the classification key to the field's `extraction_profiles` dict.

---

## Key Design Decisions

### Why Not Domain Namespaces (acquisition.*, hr.*, etc.)?

We considered creating new namespaces per ontology domain (`acquisition.contract_number` instead of `document.contract_number`). Decided against because:
- Major migration — all existing `document.*` fields would need to move
- All facet mappings break
- Some fields cross domains (e.g., `effective_date` matters in acquisition AND corporate)
- The extraction pipeline would need to know which namespace to write to based on classification
- Current `document` namespace works fine — it's just "fields extracted from document content"

### Why Profile Names = Taxonomy Labels (Not Slugified Keys)?

Extraction profile keys use the human-readable taxonomy label ("Sources Sought Notice") not a slug ("sources_sought_notice") because:
- The taxonomy labels are already canonical and unique within the system
- Less indirection — you can read a field definition and immediately know which document types use it
- The `classification_path` field carries the slugified version for technical queries

### Why Normalize at Index Time (Not Query Time)?

Moving normalization from query time to index time means:
- Aggregation queries are fast — the index has canonical values, not raw variants
- Facet counts are accurate — "DHS" and "Department of Homeland Security" aren't double-counted
- Query-time alias resolution is still needed for USER INPUT but not for index data
- Trade-off: re-indexing needed if vocabulary changes (acceptable — vocabulary changes are rare)

### What Happens to Records Without Ontology Classification?

Some content types (Web Libraries, Salesforce contacts, generic files) may not receive an ontology classification. They still have:
- Source-native fields in their namespace (sharepoint.*, salesforce.*, file_library.*)
- No extraction profiles are triggered (no classification → no profile → no extraction)
- They're still searchable by their source-native fields
- Web Libraries carry context that flows down to classify children (see Part 6)

---

## Validation Checklist

After implementation, the following should all pass:

- [ ] `validation_service.py` reports no errors for profile name ↔ taxonomy mismatches
- [ ] `get_extraction_fields("Task Order", "asset")` returns correct field set with requirement levels
- [ ] `get_extraction_fields("Task Order", "sam_notice")` skips fields with `source_wins` overrides for sam_notice
- [ ] `get_facetable_fields()` returns equivalent facets to current `facets.yaml` (minus the per-content-type routing)
- [ ] Dual-source fields (response_deadline, agency) use SAM structured value when available, extracted value as fallback
- [ ] `ontology.classification_path` enables LIKE queries for hierarchical filtering
- [ ] Controlled vocabulary normalization at index time produces canonical values
- [ ] Legacy flat `extraction_profiles` format still works alongside new structured format
- [ ] All existing search/filter functionality works unchanged during migration

---

## Appendix: Complete Field-to-Classification Map

Key extracted fields and which ontology classifications use them:

| Field | Required For | Expected For | Optional For |
|-------|-------------|-------------|-------------|
| contract_number | Contract, Task Order, Modification | QASP, CDRL | Proposal Response |
| rfp_release_date | | Solicitation | Sources Sought, Amendment, Pre-Solicitation |
| response_deadline | Solicitation | Sources Sought, Amendment | |
| total_contract_value | | Contract, Task Order, Award Notice | Modification |
| period_of_performance | | Contract, Task Order, SOW | Solicitation |
| security_clearance | | Solicitation, SOW, PWS | Task Order, Sources Sought |
| evaluation_criteria | | Solicitation | Sources Sought |
| ordering_agency | | Task Order, Award Notice, Solicitation | |
| vehicle | | Contract, Task Order | Solicitation, Proposal Response |
| set_aside_type | | Solicitation, Sources Sought | Award Notice |
| naics_codes | | Solicitation, Sources Sought | Award Notice |
| awardee | | Award Notice | Contract |
| parent_contract | | Task Order | Modification |
