# Embedding Models & pgvector

How Curatore uses vector embeddings for semantic search, which models are supported, and how to switch between them.

---

## Table of Contents

1. [How pgvector Works in Curatore](#how-pgvector-works-in-curatore)
2. [Supported Embedding Models](#supported-embedding-models)
3. [Model Comparison](#model-comparison)
4. [Dimension Auto-Resolution](#dimension-auto-resolution)
5. [Choosing a Model](#choosing-a-model)
6. [Switching Models (Local Development)](#switching-models-local-development)
7. [Switching Models (Production)](#switching-models-production)
8. [Impact of Changing Models](#impact-of-changing-models)
9. [Troubleshooting](#troubleshooting)

---

## How pgvector Works in Curatore

Curatore uses [pgvector](https://github.com/pgvector/pgvector), a PostgreSQL extension that adds vector data types and similarity search operators. Every piece of searchable content (documents, SAM notices, Salesforce records, forecasts) is:

1. **Chunked** into ~1500-character segments (documents only; other types are a single chunk)
2. **Embedded** via an embedding API into a fixed-length numeric vector
3. **Stored** in the `search_chunks` table alongside a PostgreSQL `tsvector` for keyword search

```
Document text ──> Chunking ──> Embedding API ──> vector(N) ──> search_chunks table
                                                     │
                                    ┌────────────────┘
                                    ▼
                          PostgreSQL + pgvector
                          ├── tsvector  (keyword search)
                          └── vector(N) (semantic search via cosine similarity)
```

The `embedding` column is declared as `vector(N)` where N is the model's native dimension count. **All vectors in a column must have the same number of dimensions.** This is a hard constraint enforced by PostgreSQL — you cannot mix 1024-dim and 3072-dim vectors in the same column.

### Two tables use pgvector

| Table | Purpose | Index Type |
|-------|---------|------------|
| `search_chunks` | Core search index (all content) | IVFFlat (100 lists) |
| `collection_chunks` | Isolated per-collection vector stores | HNSW |

Both tables have their `embedding` column sized to match the configured model's native dimensions.

---

## Supported Embedding Models

| Model | Provider | Dimensions | Config Value |
|-------|----------|-----------|--------------|
| `text-embedding-3-large` | OpenAI | 3072 | `text-embedding-3-large` |
| `text-embedding-3-small` | OpenAI | 1536 | `text-embedding-3-small` |
| `text-embedding-ada-002` | OpenAI (legacy) | 1536 | `text-embedding-ada-002` |
| `amazon-titan-embed-text-v2:0` | AWS Bedrock | 1024 | `amazon-titan-embed-text-v2:0` |

Dimensions are auto-resolved from the model name. You only set `LLM_EMBEDDING_MODEL` in your `.env` — the system derives the correct dimension count automatically.

---

## Model Comparison

### text-embedding-3-large (OpenAI)

**Dimensions:** 3072 | **Max tokens:** 8191 | **Cost:** ~$0.13 / 1M tokens

| Strengths | Weaknesses |
|-----------|------------|
| Highest retrieval accuracy (MTEB benchmark leader) | Largest vectors = more storage and slower indexing |
| Best semantic understanding for nuanced queries | Highest per-token cost among OpenAI models |
| Supports native dimension reduction via API `dimensions` param | Requires OpenAI API access |
| Excellent for domain-specific content (legal, procurement, technical) | 3072-dim vectors use ~2x storage vs 1536-dim |

**Best for:** Production deployments where search quality is critical and content is complex or domain-specific.

### text-embedding-3-small (OpenAI)

**Dimensions:** 1536 | **Max tokens:** 8191 | **Cost:** ~$0.02 / 1M tokens

| Strengths | Weaknesses |
|-----------|------------|
| Strong accuracy for the cost (best quality-per-dollar) | Lower retrieval accuracy than 3-large on complex queries |
| 6.5x cheaper than 3-large | Still requires OpenAI API access |
| Smaller vectors = faster indexing and less storage | |
| Good general-purpose performance | |

**Best for:** Cost-sensitive deployments, development/staging, or datasets where content is straightforward.

### text-embedding-ada-002 (OpenAI, Legacy)

**Dimensions:** 1536 | **Max tokens:** 8191 | **Cost:** ~$0.10 / 1M tokens

| Strengths | Weaknesses |
|-----------|------------|
| Mature, well-tested model | Superseded by text-embedding-3-small (cheaper and better) |
| Same 1536 dimensions as 3-small | No dimension reduction support |
| | 5x more expensive than 3-small for similar quality |

**Best for:** Legacy compatibility only. New deployments should use `text-embedding-3-small` or `text-embedding-3-large` instead.

### amazon-titan-embed-text-v2:0 (AWS Bedrock)

**Dimensions:** 1024 | **Max tokens:** 8192 | **Cost:** ~$0.02 / 1M tokens (Bedrock pricing)

| Strengths | Weaknesses |
|-----------|------------|
| Runs on AWS Bedrock (no OpenAI dependency) | Requires LiteLLM proxy or Bedrock-compatible API endpoint |
| Competitive accuracy for the dimension count | Smaller vector space may lose nuance on complex queries |
| Smallest vectors = fastest indexing, least storage | Fewer community benchmarks vs OpenAI models |
| Good for AWS-native environments | Not directly compatible with OpenAI API without proxy |
| Supports 256/512/1024 native dimension modes | |

**Best for:** AWS-native deployments, environments that cannot use OpenAI, or development/testing where cost and speed matter more than peak accuracy.

### Quick Decision Matrix

| Priority | Recommended Model |
|----------|-------------------|
| Maximum search quality | `text-embedding-3-large` |
| Best value (quality per dollar) | `text-embedding-3-small` |
| AWS-native / no OpenAI | `amazon-titan-embed-text-v2:0` |
| Development / testing | `text-embedding-3-small` or `amazon-titan-embed-text-v2:0` |
| Legacy system compatibility | `text-embedding-ada-002` |

---

## Dimension Auto-Resolution

When you set `LLM_EMBEDDING_MODEL` in your `.env`, dimensions are determined automatically in two places:

### 1. Config generation (`generate-env.sh`)

```bash
LLM_EMBEDDING_MODEL="$(env_get LLM_EMBEDDING_MODEL "text-embedding-3-large")"
case "$LLM_EMBEDDING_MODEL" in
  text-embedding-3-large)          LLM_EMBEDDING_DIMENSIONS=3072 ;;
  text-embedding-3-small)          LLM_EMBEDDING_DIMENSIONS=1536 ;;
  amazon-titan-embed-text-v2:0)    LLM_EMBEDDING_DIMENSIONS=1024 ;;
  text-embedding-ada-002)          LLM_EMBEDDING_DIMENSIONS=1536 ;;
  *)                               LLM_EMBEDDING_DIMENSIONS=1536 ;;
esac
```

This writes the resolved dimensions into `config.yml` under `llm.task_types.embedding.dimensions`.

### 2. Runtime (`EmbeddingService`)

The backend's `EmbeddingService` has a matching lookup:

```python
EMBEDDING_DIMENSIONS = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "amazon-titan-embed-text-v2:0": 1024,
}
```

If `config.yml` specifies explicit dimensions, those take precedence. Otherwise, the service uses the model's native dimensions from this mapping.

### 3. Fresh install schema (`prestart.py`)

On a fresh database (no Alembic version), `prestart.py` reads the configured dimensions from `config.yml` and creates the `search_chunks` and `collection_chunks` tables with `vector(N)` columns sized accordingly.

**You never need to set `LLM_EMBEDDING_DIMENSIONS` manually.** It is always derived from the model name.

---

## Choosing a Model

### Storage Impact

Vector storage grows linearly with dimension count. For a typical Curatore deployment:

| Model | Dims | Per-chunk storage | 100K chunks | 1M chunks |
|-------|------|------------------|-------------|-----------|
| `text-embedding-3-large` | 3072 | ~12 KB | ~1.2 GB | ~12 GB |
| `text-embedding-3-small` | 1536 | ~6 KB | ~600 MB | ~6 GB |
| `amazon-titan-embed-text-v2:0` | 1024 | ~4 KB | ~400 MB | ~4 GB |

*(Approximate; includes index overhead.)*

### Indexing Speed

Higher dimensions mean more data per embedding API call and more data written to PostgreSQL. In practice:

- **1024d (Titan):** Fastest indexing, smallest IVFFlat index
- **1536d (3-small):** ~50% more data than Titan
- **3072d (3-large):** ~3x more data than Titan, noticeably slower bulk reindex

For development and testing, smaller models (Titan or 3-small) provide faster iteration cycles.

### Search Quality

Larger dimension counts capture more semantic nuance:

- **3072d:** Best at distinguishing similar-but-different concepts. Ideal for procurement/legal content where precise meaning matters.
- **1536d:** Strong general-purpose performance. Handles most queries well.
- **1024d:** Good for straightforward content. May lose subtle distinctions on domain-specific queries.

---

## Switching Models (Local Development)

Switching embedding models requires a **factory reset** because:
1. The `vector(N)` column dimensions must match the model
2. Embeddings from different models exist in incompatible vector spaces (even if dimensions happen to match)

### Steps

```bash
# 1. Set the new model in .env
#    Edit .env and change LLM_EMBEDDING_MODEL:
#    LLM_EMBEDDING_MODEL=amazon-titan-embed-text-v2:0

# 2. Regenerate configs (auto-resolves dimensions)
./scripts/generate-env.sh

# 3. Factory reset: destroy all data and rebuild
./scripts/dev-down.sh
docker ps -a --filter "name=curatore-" --format "{{.ID}}" | xargs docker rm -f
docker images --format "{{.Repository}} {{.ID}}" | grep curatore | awk '{print $2}' | xargs docker rmi -f
docker volume ls --format "{{.Name}}" | grep curatore | xargs docker volume rm -f
docker network rm curatore-network

# 4. Start fresh
./scripts/dev-up.sh --with-postgres

# 5. Create admin account
#    Visit http://localhost:3000/setup
#    Or: docker exec curatore-backend python -m app.core.commands.seed --create-admin
```

### Verify

```bash
# Check the vector column dimensions
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT attname, atttypmod FROM pg_attribute
   WHERE attrelid = 'search_chunks'::regclass AND attname = 'embedding';"

# Should show atttypmod = <your model's dimension count>
```

---

## Switching Models (Production)

Switching embedding models in production is a **breaking change** that requires careful planning. There is no in-place migration path — all existing embeddings must be discarded and regenerated.

### Why It's Breaking

1. **Column dimensions:** PostgreSQL's `vector(1536)` column physically cannot store a 3072-dim vector (or vice versa). The column must be recreated.
2. **Vector space incompatibility:** Even between models with the same dimension count (e.g., `text-embedding-3-small` and `text-embedding-ada-002`, both 1536d), the vectors are in completely different vector spaces. Mixing them produces meaningless similarity scores.
3. **Index rebuild required:** The IVFFlat/HNSW indexes must be rebuilt for the new vector dimensions and data distribution.

### Production Migration Procedure

#### Phase 1: Preparation

1. **Schedule a maintenance window.** Semantic search will be unavailable during the migration. Keyword search continues to work.
2. **Back up the database.**
3. **Update configuration:**
   ```bash
   # In your deployment's .env:
   LLM_EMBEDDING_MODEL=text-embedding-3-large

   # Regenerate configs:
   ./scripts/generate-env.sh
   ```
4. **Verify the new model is accessible** from your LLM endpoint (OpenAI, LiteLLM proxy, Bedrock, etc.).

#### Phase 2: Schema Migration

Run an Alembic migration to alter the vector columns. Example migration:

```python
"""Switch embedding dimensions from 1536 to 3072."""

from alembic import op

NEW_DIMS = 3072  # Must match the new model's native dimensions

def upgrade():
    # Drop existing vector indexes (they reference the old dimensions)
    op.drop_index("ix_search_chunks_embedding", table_name="search_chunks")
    op.drop_index("ix_collection_chunks_embedding", table_name="collection_chunks")

    # Alter vector columns to new dimensions
    # This drops all existing embedding data (columns are recreated)
    op.execute("ALTER TABLE search_chunks DROP COLUMN embedding")
    op.execute(f"ALTER TABLE search_chunks ADD COLUMN embedding vector({NEW_DIMS})")
    op.execute("ALTER TABLE collection_chunks DROP COLUMN embedding")
    op.execute(f"ALTER TABLE collection_chunks ADD COLUMN embedding vector({NEW_DIMS})")

    # Rebuild indexes
    op.execute(f"""
        CREATE INDEX ix_search_chunks_embedding ON search_chunks
        USING ivfflat(embedding vector_cosine_ops) WITH (lists = 100)
    """)
    op.execute(f"""
        CREATE INDEX ix_collection_chunks_embedding ON collection_chunks
        USING hnsw(embedding vector_cosine_ops)
    """)

    # Clear indexed_at timestamps to force full reindex
    op.execute("UPDATE assets SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE sam_solicitations SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE sam_notices SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE salesforce_accounts SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE salesforce_contacts SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE salesforce_opportunities SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE ag_forecasts SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE apfs_forecasts SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
    op.execute("UPDATE state_forecasts SET indexed_at = NULL WHERE indexed_at IS NOT NULL")
```

Run the migration:

```bash
docker exec curatore-backend alembic upgrade head
```

#### Phase 3: Re-embed All Content

Trigger a full reindex from the admin UI (System Maintenance > Search Reindex > Full Reindex) or via API:

```bash
curl -X POST http://localhost:8000/api/v1/search/reindex \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"force": true}'
```

Monitor progress:

```bash
# Watch reindex progress
./scripts/dev-logs.sh worker-documents

# Check indexing coverage
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT source_type, COUNT(*) as total,
          COUNT(CASE WHEN embedding IS NOT NULL THEN 1 END) as embedded
   FROM search_chunks GROUP BY source_type;"
```

#### Phase 4: Verification

```bash
# Verify new vector dimensions
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT attname, atttypmod as dimensions FROM pg_attribute
   WHERE attrelid = 'search_chunks'::regclass AND attname = 'embedding';"

# Verify search works
curl http://localhost:8000/api/v1/search/health

# Test a search query
curl -X POST http://localhost:8000/api/v1/search \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/json" \
  -d '{"query": "test search", "search_mode": "hybrid"}'
```

### Time Estimates for Re-embedding

Re-embedding time depends on content volume and the embedding API's throughput:

| Content Volume | Batch API Calls | Approximate Time |
|---------------|-----------------|------------------|
| 1,000 items | ~20 batches | < 1 minute |
| 10,000 items | ~200 batches | ~5 minutes |
| 100,000 items | ~2,000 batches | ~30-60 minutes |

Assets take longer because each requires a MinIO download + chunking step before embedding.

### Rollback Plan

If the new model causes issues, reverse the process:

1. Restore the database backup (or run the reverse migration to change dimensions back)
2. Revert `LLM_EMBEDDING_MODEL` in `.env` and regenerate configs
3. Run a full reindex with the original model

---

## Impact of Changing Models

### What Breaks

| Component | Impact | Recovery |
|-----------|--------|----------|
| `search_chunks.embedding` column | Column dimension mismatch; semantic search fails | Alter column + full reindex |
| `collection_chunks.embedding` column | Same as above for search collections | Alter column + repopulate collections |
| External vector syncs (Pinecone, etc.) | External indexes have wrong dimensions | Re-sync all collections |
| IVFFlat / HNSW indexes | Indexes reference old dimensions | Drop + recreate |
| Cached embeddings | Any in-memory or Redis-cached vectors are invalid | Restart services |

### What Survives

| Component | Status |
|-----------|--------|
| Keyword search (tsvector) | Unaffected — works without embeddings |
| Document content (MinIO) | Unaffected — stored separately |
| Database records (assets, SAM, etc.) | Unaffected — only `indexed_at` is reset |
| User accounts, organizations, configs | Unaffected |
| Extraction results | Unaffected |

---

## Troubleshooting

### "different vector dimensions 1536 and 1024"

The configured model produces vectors with different dimensions than the database column expects.

**Cause:** The embedding model was changed without altering the database column.

**Fix:** Follow the [Switching Models](#switching-models-local-development) procedure (factory reset for dev, migration for production).

### Semantic search returns no results but keyword search works

**Cause:** Embeddings are missing (NULL) or were generated by a different model.

**Check:**
```bash
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT COUNT(*) as total,
          COUNT(embedding) as has_embedding,
          COUNT(*) - COUNT(embedding) as missing_embedding
   FROM search_chunks;"
```

**Fix:** Run a full reindex: Admin UI > System Maintenance > Search Reindex > Full.

### "OPENAI_API_KEY not set" when using Titan

**Cause:** The Titan model requires an API key like any other embedding model. The key is passed through the same `OPENAI_API_KEY` / `llm.api_key` config path via a LiteLLM proxy.

**Fix:** Ensure your LiteLLM proxy (or Bedrock endpoint) is configured at `OPENAI_BASE_URL` and accepts the configured API key.

### How to check current model and dimensions

```bash
# Check config.yml
grep -A2 'embedding:' curatore-backend/config.yml

# Check actual database column dimensions
docker exec curatore-postgres psql -U curatore -d curatore -c \
  "SELECT attname, atttypmod as dimensions FROM pg_attribute
   WHERE attrelid = 'search_chunks'::regclass AND attname = 'embedding';"

# Check what the backend reports
curl -s http://localhost:8000/api/v1/search/health | python3 -m json.tool
```

---

## Related Documentation

| Document | Description |
|----------|-------------|
| [Search & Indexing](https://github.com/Amivero-LLC/curatore-backend/blob/main/docs/SEARCH_INDEXING.md) | Full search architecture, chunking, hybrid scoring, API endpoints |
| [Configuration](CONFIGURATION.md) | .env vs config.yml philosophy |
| [Platform Overview](OVERVIEW.md) | Service architecture and data flow |
| [Document Processing](DOCUMENT_PROCESSING.md) | Upload to extraction to indexing pipeline |
