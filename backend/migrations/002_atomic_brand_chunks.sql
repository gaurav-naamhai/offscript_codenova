BEGIN;
-- V2 publishes both document and chunks in one transaction. The original RPC
-- remains available for older clients; the integrated application uses V2.
CREATE OR REPLACE FUNCTION publish_brand_document_version_v2(
    p_source_doc_id uuid, p_expected_revision integer, p_title text,
    p_category text, p_new_version text, p_source_filename text,
    p_storage_path text, p_org_id text, p_approved_by text,
    p_reason text, p_chunks jsonb
) RETURNS TABLE(new_document_id uuid, new_revision_number integer, created_at timestamptz)
LANGUAGE plpgsql SECURITY DEFINER SET search_path = public AS $$
DECLARE
    v_source brand_documents%ROWTYPE;
    v_family text := lower(trim(p_title)) || '::' || lower(trim(coalesce(p_category, 'guideline')));
    v_org text := lower(trim(p_org_id));
    v_count integer;
    v_revision integer;
    v_id uuid;
    v_chunk jsonb;
    v_now timestamptz := now();
BEGIN
    IF v_org = '' OR v_family = '::guideline' OR jsonb_typeof(p_chunks) <> 'array'
       OR jsonb_array_length(p_chunks) = 0 THEN
        RAISE EXCEPTION 'INVALID_PUBLICATION: organisation, family and chunks are required';
    END IF;
    PERFORM pg_advisory_xact_lock(hashtext(v_org || '::' || v_family));
    SELECT count(*) INTO v_count
      FROM brand_documents WHERE org_id = v_org AND document_family = v_family AND is_active;
    SELECT coalesce(max(revision_number), 0) + 1 INTO v_revision
      FROM brand_documents WHERE org_id = v_org AND document_family = v_family;
    IF v_count > 1 THEN RAISE EXCEPTION 'AMBIGUOUS_ACTIVE_BRAND_DOCUMENTS'; END IF;
    IF p_source_doc_id IS NULL THEN
        IF v_count <> 0 THEN RAISE EXCEPTION 'STALE_VERSION: active family exists'; END IF;
    ELSE
        SELECT * INTO v_source FROM brand_documents WHERE id = p_source_doc_id FOR UPDATE;
        IF NOT FOUND OR v_source.org_id <> v_org OR v_source.document_family <> v_family
           OR v_source.is_active IS NOT TRUE OR v_count <> 1
           OR p_expected_revision IS NULL OR v_source.revision_number <> p_expected_revision THEN
            RAISE EXCEPTION 'STALE_VERSION: refresh the active guideline';
        END IF;
        SELECT coalesce(max(revision_number), 0) + 1 INTO v_revision FROM brand_documents
          WHERE org_id = v_org AND document_family = v_family;
        UPDATE brand_documents SET is_active = false WHERE id = p_source_doc_id;
    END IF;
    INSERT INTO brand_documents
      (title,category,version,is_active,source_filename,storage_path,org_id,
       document_family,revision_number,previous_version_id,published_by,published_at)
    VALUES (p_title,p_category,p_new_version,true,p_source_filename,p_storage_path,v_org,
            v_family,v_revision,p_source_doc_id,p_approved_by,v_now)
    RETURNING id INTO v_id;
    FOR v_chunk IN SELECT value FROM jsonb_array_elements(p_chunks) LOOP
        INSERT INTO brand_chunks(document_id,content,page_number,section,chunk_index,embedding)
        VALUES (v_id,v_chunk->>'content',(v_chunk->>'page_number')::integer,
                v_chunk->>'section',(v_chunk->>'chunk_index')::integer,
                (v_chunk->>'embedding')::vector);
    END LOOP;
    IF p_source_doc_id IS NOT NULL THEN
        INSERT INTO brand_document_audit
          (document_id,previous_version_id,org_id,document_family,revision_number,version,action,actor,reason)
        VALUES (p_source_doc_id,v_source.previous_version_id,v_org,v_family,v_source.revision_number,
                v_source.version,'deactivated',coalesce(p_approved_by,'system'),p_reason);
    END IF;
    INSERT INTO brand_document_audit
      (document_id,previous_version_id,org_id,document_family,revision_number,version,action,actor,reason)
    VALUES (v_id,p_source_doc_id,v_org,v_family,v_revision,p_new_version,'published',
            coalesce(p_approved_by,'system'),p_reason);
    RETURN QUERY SELECT v_id,v_revision,v_now;
END; $$;
REVOKE ALL ON FUNCTION publish_brand_document_version_v2(uuid,integer,text,text,text,text,text,text,text,text,jsonb)
  FROM PUBLIC, anon, authenticated;
GRANT EXECUTE ON FUNCTION publish_brand_document_version_v2(uuid,integer,text,text,text,text,text,text,text,text,jsonb)
  TO service_role;
COMMIT;
