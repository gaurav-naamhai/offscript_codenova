"""Local end-to-end test script for verifying extraction, brand RAG, and external search."""

import pymupdf
from retrieval import (
    ContentPayload,
    extract_document,
    ingest_brand_doc,
    retrieve_guidelines,
    search_brand_rag,
    verify_claim_externally,
    verify_claims,
)


def _build_sample_brand_pdf() -> bytes:
    """Create a realistic 2-page Brand Governance PDF in memory for testing."""
    doc = pymupdf.open()

    page1 = doc.new_page()
    page1_text = (
        "# SECTION 1: BRAND TONE & TERMINOLOGY\n\n"
        "Our brand voice is clear, measured, and human. Avoid empty corporate buzzwords "
        "such as 'synergy', 'disruptive', or 'game-changing', and never use multiple exclamation marks.\n\n"
        "Never refer to our products as 'cheap'; instead, describe them as 'cost-effective' or 'accessible'."
    )
    page1.insert_text((50, 72), page1_text, fontsize=11)

    page2 = doc.new_page()
    page2_text = (
        "# SECTION 2: PROMOTIONAL CLAIMS & GUARANTEES\n\n"
        "Never promise 100% guaranteed outcomes, instant cures, or fixed timelines without "
        "explicit contractual SLA disclosures and third-party benchmark citations.\n\n"
        "All environmental and sustainability claims (such as 'net-zero' or 'carbon neutral') "
        "must cite the official annual sustainability report."
    )
    page2.insert_text((50, 72), page2_text, fontsize=11)

    pdf_bytes = doc.tobytes()
    doc.close()
    return pdf_bytes


def main() -> None:
    print("1. Creating sample 2-page Brand Guideline PDF in memory...")
    pdf_bytes = _build_sample_brand_pdf()

    print("2. Testing extract_document()...")
    extracted = extract_document(pdf_bytes, filename="inkloom_brand_guide_v1.pdf")
    print(f"   Extracted {extracted.page_count} pages ({len(extracted.full_text)} chars).")

    print("3. Testing ingest_brand_doc() -> Supabase (brand_documents + brand_chunks)...")
    record = ingest_brand_doc(
        file_bytes=pdf_bytes,
        filename="inkloom_brand_guide_v1.pdf",
        title="Inkloom Brand Governance Guide",
        category="guideline",
        version="1.0",
    )
    print(f"   Ingested doc ID={record.id} with {record.chunks_count} chunks.")

    print("4. Testing search_brand_rag()...")
    matches = search_brand_rag("Guaranteed 100% instant results!", top_k=2)
    for m in matches:
        print(
            f"   Match (similarity={m.similarity:.3f}) | {m.doc_title} p.{m.page_number}: {m.content[:100]}..."
        )

    print("5. Testing Gaurav's plugin hook retrieve_guidelines(ContentPayload)...")
    sample_payload = ContentPayload(
        content_type="text",
        text="Our disruptive platform guarantees 100% instant results!!",
    )
    guidelines = retrieve_guidelines(sample_payload, top_k=2)
    for g in guidelines:
        print(f"   GuidelineRef -> {g.document} [{g.passage_ref}]: {g.excerpt[:90]}...")

    print("6. Testing verify_claim_externally() via Exa + TinyFish...")
    evidence = verify_claim_externally("World Health Organization headquarters location", max_sources=2)
    for ev in evidence:
        print(f"   Source [{ev.status}] {ev.domain} ({ev.url}) -> {ev.excerpt[:90]}...")

    print("7. Testing Gaurav's plugin hook verify_claims(ContentPayload)...")
    flags = verify_claims(sample_payload)
    for fl in flags:
        print(f"   FlagDraft -> state={fl.state} | passage='{fl.passage}' | explanation={fl.explanation[:100]}...")

    print("\nALL RETRIEVAL & EXTERNAL VERIFICATION TESTS PASSED!")


if __name__ == "__main__":
    main()
