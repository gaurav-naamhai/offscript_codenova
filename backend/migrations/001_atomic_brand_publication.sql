-- Migration: 001_atomic_brand_publication.sql
-- Purpose: Atomic brand guideline publication, single-active-version enforcement,
--          optimistic revision concurrency guard, and publication audit history.
-- Safe for existing data: non-destructive ALTERs + explicit ambiguity detection.

BEGIN;

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- 1. Non-destructive schema evolution on brand_documents
ALTER TABLE brand_documents
    ADD COLUMN IF NOT EXISTS org_id text NOT NULL DEFAULT 'default',
    ADD COLUMN IF NOT EXISTS document_family text,
    ADD COLUMN IF NOT EXISTS revision_number integer NOT NULL DEFAULT 1,
    ADD COLUMN IF NOT EXISTS previous_version_id uuid REFERENCES brand_documents(id),
    ADD COLUMN IF NOT EXISTS published_by text,
    ADD COLUMN IF NOT EXISTS published_at timestamptz;

-- Backfill org_id and previous_version_id from legacy storage_path metadata if present
UPDATE brand_documents
SET org_id = COALESCE(
        NULLIF(substring(storage_path FROM '__org=([^|]+)'), ''),
        NULLIF(org_id, ''),
        'default'
    )
WHERE org_id = 'default' OR org_id IS NULL;

UPDATE brand_documents
SET previous_version_id = substring(storage_path FROM '__prev=([0-9a-fA-F-]{36})')::uuid
WHERE previous_version_id IS NULL
  AND storage_path ~ '__prev=[0-9a-fA-F-]{36}';

UPDATE brand_documents
SET document_family = lower(trim(title)) || '::' || lower(trim(COALESCE(category, 'guideline')))
WHERE document_family IS NULL OR document_family = '';

ALTER TABLE brand_documents
    ALTER COLUMN document_family SET NOT NULL;

-- Assign deterministic monotonic revision numbers per (org_id, document_family)
WITH ranked AS (
    SELECT
        id,
        ROW_NUMBER() OVER (
            PARTITION BY org_id, document_family
            ORDER BY created_at ASC NULLS LAST, id ASC
        ) AS rn
    FROM brand_documents
)
UPDATE brand_documents d
SET revision_number = r.rn
FROM ranked r
WHERE d.id = r.id;

-- 2. Audit history table preserving every publication & deactivation event
CREATE TABLE IF NOT EXISTS brand_document_audit (
    id uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    document_id uuid NOT NULL REFERENCES brand_documents(id) ON DELETE RESTRICT,
    previous_version_id uuid REFERENCES brand_documents(id) ON DELETE RESTRICT,
    org_id text NOT NULL,
    document_family text NOT NULL,
    revision_number integer NOT NULL,
    version text NOT NULL,
    action text NOT NULL CHECK (action IN ('published', 'deactivated')),
    actor text NOT NULL,
    reason text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_brand_document_audit_family
    ON brand_document_audit (org_id, document_family, created_at DESC);

-- 3. Ambiguous duplicate active-version detector (never guesses or deletes)
CREATE OR REPLACE FUNCTION detect_ambiguous_active_brand_documents()
RETURNS TABLE (
    org_id text,
    document_family text,
    active_count bigint,
    active_document_ids uuid[]
)
LANGUAGE sql
STABLE
AS $$
    SELECT
        d.org_id,
        d.document_family,
        COUNT(*) AS active_count,
        ARRAY_AGG(d.id ORDER BY d.created_at ASC NULLS LAST, d.id ASC) AS active_document_ids
    FROM brand_documents d
    WHERE d.is_active = true
    GROUP BY d.org_id, d.document_family
    HAVING COUNT(*) > 1;
$$;

DO $$
DECLARE
    v_conflicts text;
BEGIN
    SELECT string_agg(
        format('%s / %s (active_count=%s, ids=%s)', org_id, document_family, active_count, active_document_ids::text),
        '; '
    )
    INTO v_conflicts
    FROM detect_ambiguous_active_brand_documents();

    IF v_conflicts IS NOT NULL THEN
        RAISE EXCEPTION 'AMBIGUOUS_ACTIVE_BRAND_DOCUMENTS: Cannot enforce single active version because multiple active rows exist: %', v_conflicts;
    END IF;
END;
$$;

-- 4. Database-level invariants: at most one active version per family, unique revision numbers
CREATE UNIQUE INDEX IF NOT EXISTS uq_brand_docs_one_active_per_family
    ON brand_documents (org_id, document_family)
    WHERE is_active = true;

CREATE UNIQUE INDEX IF NOT EXISTS uq_brand_docs_family_revision
    ON brand_documents (org_id, document_family, revision_number);

-- 5. Atomic publication RPC callable by the backend application
CREATE OR REPLACE FUNCTION publish_brand_document_version(
    p_source_doc_id uuid,
    p_expected_revision integer,
    p_title text,
    p_category text,
    p_new_version text,
    p_source_filename text,
    p_storage_path text,
    p_org_id text,
    p_approved_by text,
    p_reason text DEFAULT NULL
)
RETURNS TABLE (
    new_document_id uuid,
    new_revision_number integer,
    document_family text,
    previous_version_id uuid,
    created_at timestamptz
)
LANGUAGE plpgsql
SECURITY DEFINER
SET search_path = public
AS $$
DECLARE
    v_source brand_documents%ROWTYPE;
    v_family text;
    v_org text;
    v_next_rev integer;
    v_new_id uuid;
    v_now timestamptz := now();
BEGIN
    -- Lock the source row first, then serialize all publications in the same family
    SELECT *
    INTO v_source
    FROM brand_documents
    WHERE id = p_source_doc_id
    FOR UPDATE;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'NOT_FOUND: Source brand document % does not exist.', p_source_doc_id;
    END IF;

    v_org := COALESCE(NULLIF(trim(p_org_id), ''), v_source.org_id, 'default');
    IF v_source.org_id <> v_org THEN
        RAISE EXCEPTION 'ORG_MISMATCH: Source document % belongs to organisation %, not %.', p_source_doc_id, v_source.org_id, v_org;
    END IF;

    v_family := v_source.document_family;
    PERFORM pg_advisory_xact_lock(hashtext(v_org || '::' || v_family));

    -- Re-read source row after acquiring family lock to detect concurrent updates
    SELECT *
    INTO v_source
    FROM brand_documents
    WHERE id = p_source_doc_id;

    IF v_source.is_active IS NOT TRUE THEN
        RAISE EXCEPTION 'STALE_VERSION: Brand document % (revision %) is no longer active; refresh and review the latest version before publishing.',
            p_source_doc_id, v_source.revision_number;
    END IF;

    IF p_expected_revision IS NOT NULL AND v_source.revision_number <> p_expected_revision THEN
        RAISE EXCEPTION 'STALE_VERSION: Expected revision % for document %, but current revision is %.',
            p_expected_revision, p_source_doc_id, v_source.revision_number;
    END IF;

    SELECT COALESCE(MAX(d.revision_number), 0) + 1
    INTO v_next_rev
    FROM brand_documents d
    WHERE d.org_id = v_org
      AND d.document_family = v_family;

    -- Deactivate previous active version while preserving its row and chunks
    UPDATE brand_documents
    SET is_active = false
    WHERE id = v_source.id
      AND is_active = true;

    INSERT INTO brand_document_audit (
        document_id,
        previous_version_id,
        org_id,
        document_family,
        revision_number,
        version,
        action,
        actor,
        reason,
        created_at
    ) VALUES (
        v_source.id,
        v_source.previous_version_id,
        v_org,
        v_family,
        v_source.revision_number,
        v_source.version,
        'deactivated',
        COALESCE(NULLIF(trim(p_approved_by), ''), 'system'),
        COALESCE(p_reason, 'Superseded by new guideline publication'),
        v_now
    );

    -- Insert new active version
    INSERT INTO brand_documents (
        title,
        category,
        version,
        is_active,
        source_filename,
        storage_path,
        org_id,
        document_family,
        revision_number,
        previous_version_id,
        published_by,
        published_at,
        created_at
    ) VALUES (
        COALESCE(NULLIF(trim(p_title), ''), v_source.title),
        COALESCE(NULLIF(trim(p_category), ''), v_source.category, 'guideline'),
        p_new_version,
        true,
        p_source_filename,
        p_storage_path,
        v_org,
        v_family,
        v_next_rev,
        v_source.id,
        COALESCE(NULLIF(trim(p_approved_by), ''), 'system'),
        v_now,
        v_now
    )
    RETURNING id INTO v_new_id;

    INSERT INTO brand_document_audit (
        document_id,
        previous_version_id,
        org_id,
        document_family,
        revision_number,
        version,
        action,
        actor,
        reason,
        created_at
    ) VALUES (
        v_new_id,
        v_source.id,
        v_org,
        v_family,
        v_next_rev,
        p_new_version,
        'published',
        COALESCE(NULLIF(trim(p_approved_by), ''), 'system'),
        COALESCE(p_reason, 'Published rectified guideline version'),
        v_now
    );

    RETURN QUERY
    SELECT v_new_id, v_next_rev, v_family, v_source.id, v_now;
END;
$$;

COMMIT;
