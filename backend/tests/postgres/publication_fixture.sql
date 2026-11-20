-- Synthetic pre-001 schema for a newly created, disposable PostgreSQL cluster.
-- Three-dimensional vectors keep test input small and exercise real pgvector casts.
CREATE EXTENSION vector;
CREATE ROLE anon;
CREATE ROLE authenticated;
CREATE ROLE service_role;
CREATE TABLE brand_documents (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    title text NOT NULL, category text NOT NULL, version text NOT NULL,
    is_active boolean NOT NULL, source_filename text NOT NULL, storage_path text,
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE brand_chunks (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES brand_documents(id),
    content text NOT NULL, page_number integer, section text, chunk_index integer NOT NULL,
    embedding vector(3) NOT NULL,
    UNIQUE (document_id, chunk_index)
);
