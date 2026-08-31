-- Phase 9: turn on real vector search (sections 12 level 4, and 13).
--
-- Apply this only when an embedder is configured. Until then the platform runs
-- levels 1-3 (lexical, symbol, dependency), which need no vectors at all -
-- section 12 is explicit that vector search is not where you start.
--
-- Requires the pgvector/pgvector:pg16 image (or the extension installed).
-- Set the dimension to match your embedding model before applying.

BEGIN;

CREATE EXTENSION IF NOT EXISTS vector;

-- The POC stores embeddings as a JSON array in a TEXT column so the ORM is
-- identical on SQLite and PostgreSQL. This converts that column in place.
ALTER TABLE code_chunks
    ALTER COLUMN embedding TYPE vector(1536)
    USING CASE
        WHEN embedding IS NULL OR embedding = '' THEN NULL
        ELSE embedding::vector
    END;

-- HNSW for cosine distance: the right default for code retrieval, where recall
-- matters more than exact nearest neighbours.
CREATE INDEX IF NOT EXISTS ix_code_chunks_embedding_hnsw
    ON code_chunks
    USING hnsw (embedding vector_cosine_ops)
    WITH (m = 16, ef_construction = 64);

-- After this migration, retrieval/search/vector.py can push similarity into
-- SQL instead of scoring in Python:
--
--   SELECT id, file_path, symbol_name, content,
--          1 - (embedding <=> :query_embedding) AS similarity
--   FROM code_chunks
--   WHERE repository_id = :repository_id AND embedding IS NOT NULL
--   ORDER BY embedding <=> :query_embedding
--   LIMIT :limit;
--
-- Nothing above retrieval/search/ changes.

COMMIT;
