# ADR-003: pgvector for Duplicate Detection

## Status
**Accepted** — Session 5

## Context
Duplicate municipal complaints are common — multiple citizens report the same pothole, water main break, or open manhole. The system needs to identify potential duplicates using multiple similarity signals: geographic proximity, semantic content similarity, temporal recency, and category overlap.

## Decision
Use **pgvector** (PostgreSQL extension) for embedding-based semantic similarity, combined with **PostGIS** spatial distance and temporal decay for multi-factor duplicate ranking.

### Architecture:
1. **Embedding Generation**: Each complaint's text is embedded via `EmbeddingProvider` (Gemini text-embedding-004 or MockProvider) into a 768-dimension vector stored in `complaint_embeddings`.
2. **Multi-Factor Candidate Search**:
   - **Spatial**: Haversine distance within configurable radius (default 3km).
   - **Semantic**: pgvector cosine similarity on complaint embeddings.
   - **Category**: Exact category match bonus.
   - **Temporal**: Exponential decay based on age within configurable window (default 30 days).
3. **Weighted Ranking**: Candidates scored as weighted sum of all factors.
4. **Never Auto-Merge**: Candidates are presented to officers for human decision (`link` or `dismiss`). Linked complaints maintain distinct records.

### Citizen-Facing:
- `GET /complaints/nearby-similar`: Returns non-sensitive, zero-PII nearby reports.
- `POST /complaints/{id}/support`: Citizens endorse existing complaints ("same issue").

## Consequences

### Positive
- **Single database**: No separate vector store (Pinecone, Weaviate) to operate.
- **SQL-native**: Vector operations integrate naturally with existing PostGIS spatial queries.
- **Multi-signal ranking**: More robust than pure text similarity.
- **Human-in-the-loop**: Zero auto-merge risk; officers make final decisions.

### Negative
- pgvector indexing (IVFFlat/HNSW) may require tuning at scale (>100K complaints).
- Embedding quality depends on provider model — mock provider uses deterministic hashing.
- No cross-lingual semantic matching without multilingual embedding models.

### Alternatives Considered
- **Elasticsearch**: More operationally complex; overkill for similarity search at MVP scale.
- **Dedicated vector DB (Pinecone)**: External dependency; unnecessary when pgvector runs in PostgreSQL.
- **TF-IDF / BM25**: Poor semantic understanding of complaint text.
