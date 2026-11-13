"""Stage 6 Unified Integration Tests.

Owner: Sera
Proves end-to-end integration across:
1. Ken's external evidence reaching Sera's claim verification.
2. Brand, claim, and accessibility findings reaching unified flag aggregation.
3. Deduplication preserving external sources, guidelines, and corrections.
4. Entity preservation and reverification of corrections.
5. Honest handling of visual limitations on rendered vs unrenderable PDFs.
6. Governance intelligence consuming actual stored flags via API endpoints.
7. Preservation of frontend contracts and backward compatibility.
"""

from typing import List
import pytest

from app.ai.client import GeminiClient
from app.ai.flagging import deduplicate_and_synthesize_flag_drafts
from app.ai.schemas import PreservedEntity
from app.ai.suggestions_corrections import recheck_correction
from app.config import Settings
from app.models import ContentPayload, ExternalSource, FlagDraft, GuidelineRef
from app.pipeline import run_pipeline
from app.plugins import brand_check, verification
from app.uncertainty import needs_human
from retrieval.schemas import ExternalEvidenceItem


@pytest.fixture
def mock_client() -> GeminiClient:
    return GeminiClient(settings=Settings(mock_ai=True))


class TestStage6UnifiedIntegration:
    """Test suite proving end-to-end multi-module integration in Inkloom AI."""

    def test_ken_evidence_reaches_seras_claim_verification(self, monkeypatch):
        """Ken's external search is invoked and passed into Sera's claim verification module."""
        monkeypatch.setenv("MOCK_AI", "true")

        # Simulate Ken's external retrieval returning authoritative search results
        mock_evidence = [
            ExternalEvidenceItem(
                query="rated #1",
                url="https://reports.example.com/market-share",
                title="Global Market Share Report",
                domain="reports.example.com",
                published_date="2026-01-15",
                retrieved_at="2026-11-13T10:00:00Z",
                excerpt="Comparative market surveys identify multiple enterprise leaders and directly contradict the supremacy claim. No single vendor holds #1 supremacy.",
                status="ok",
            )
        ]

        import retrieval.external_search

        monkeypatch.setattr(
            retrieval.external_search,
            "verify_claim_externally",
            lambda query, max_sources=3: mock_evidence,
        )

        content = ContentPayload(
            content_type="text",
            text="Inkloom AI is rated #1 worldwide with 99.9% uptime guaranteed.",
        )

        flags = verification.verify_claims(content)
        assert len(flags) >= 1

        for f in flags:
            assert f.finding_type == "claim"
            assert f.origin == "module"
            # Verify external evidence from Ken's search was received and preserved
            assert len(f.external_sources) >= 1
            assert any(s.url == "https://reports.example.com/market-share" for s in f.external_sources)

        # Contradicted or unverified claims must require human escalation
        assert any(needs_human(f.state) for f in flags)

    def test_brand_and_claim_findings_reach_same_aggregation_stage(self, monkeypatch):
        """run_pipeline combines brand, claim, and visual findings in a single unified stage."""
        monkeypatch.setenv("MOCK_AI", "true")

        content = ContentPayload(
            content_type="text",
            text="Inkloom AI drives disruptive synergy and is rated #1 in the world.",
        )

        flags, degraded = run_pipeline(
            content=content,
            submission_id="sub-stage6-unified",
            version=1,
        )

        assert degraded == []
        assert len(flags) >= 2

        finding_types = {f.finding_type for f in flags}
        assert "brand" in finding_types
        assert "claim" in finding_types

        # Verify all flags are stamped with submission metadata
        for f in flags:
            assert f.submission_id == "sub-stage6-unified"
            assert f.version == 1
            assert f.origin == "module"

    def test_deduplication_preserves_sources_guidelines_and_corrections(self):
        """Deduplication merges identical passages without losing sources, guidelines, or fixes."""
        source_a = ExternalSource(url="https://source-a.example.com", excerpt="Excerpt A")
        source_b = ExternalSource(url="https://source-b.example.com", excerpt="Excerpt B")
        g_ref_a = GuidelineRef(document="Doc A", passage_ref="1.1", excerpt="Guideline 1")
        g_ref_b = GuidelineRef(document="Doc B", passage_ref="2.2", excerpt="Guideline 2")

        draft1 = FlagDraft(
            finding_type="claim",
            state="insufficient_evidence",
            passage="fastest in the world",
            location="paragraph 1",
            explanation="Unsubstantiated speed claim.",
            why_it_matters="Legal compliance.",
            guideline_ref=g_ref_a,
            guideline_refs=[g_ref_a],
            external_sources=[source_a],
            suggested_correction=None,
            origin="module",
        )
        draft2 = FlagDraft(
            finding_type="claim",
            state="insufficient_evidence",
            passage="fastest in the world",
            location="paragraph 1",
            explanation="Unsubstantiated speed claim.",
            why_it_matters="Legal compliance.",
            guideline_ref=g_ref_b,
            guideline_refs=[g_ref_b],
            external_sources=[source_b],
            suggested_correction="industry-leading in verified speed",
            uncertainty_note="Needs human benchmark review.",
            origin="module",
        )

        synthesized = deduplicate_and_synthesize_flag_drafts([draft1, draft2])

        assert len(synthesized) == 1
        merged = synthesized[0]

        # Both external sources are preserved
        assert len(merged.external_sources) == 2
        source_urls = {s.url for s in merged.external_sources}
        assert "https://source-a.example.com" in source_urls
        assert "https://source-b.example.com" in source_urls

        # Both guideline references are preserved
        assert len(merged.guideline_refs) == 2

        # Suggested correction and uncertainty note from second draft are preserved
        assert merged.suggested_correction == "industry-leading in verified speed"
        assert merged.uncertainty_note == "Needs human benchmark review."

    def test_corrections_are_reverified_with_entity_preservation(self, mock_client: GeminiClient):
        """Candidate corrections are reverified and protect critical entities."""
        entities = [
            PreservedEntity(text="Inkloom AI", entity_type="proper_name", context="Platform name"),
            PreservedEntity(text="May 2026", entity_type="date", context="Release date"),
            PreservedEntity(text="99.9%", entity_type="metric", context="Uptime SLA"),
        ]

        original = "Inkloom AI delivers disruptive synergy scheduled for May 2026 with 99.9% uptime."

        # Good replacement: preserves entities and fixes buzzword
        good_replacement = "Inkloom AI delivers effective collaboration targeted for May 2026 with 99.9% availability."
        passed, note = recheck_correction(
            original_passage=original,
            suggested_replacement=good_replacement,
            finding_type="brand",
            state="potential_issue",
            preserved_entities=entities,
            client=mock_client,
        )
        assert passed is True
        assert "passed" in note.lower()

        # Bad replacement: drops critical entities
        bad_replacement = "A platform with effective collaboration."
        failed, note = recheck_correction(
            original_passage=original,
            suggested_replacement=bad_replacement,
            finding_type="brand",
            state="potential_issue",
            preserved_entities=entities,
            client=mock_client,
        )
        assert failed is False
        assert "entity protection failure" in note.lower() or "unpreserved" in note.lower()

    def test_pdf_rendering_and_honest_limitations_handling(self, mock_client: GeminiClient):
        """PDF pages are rendered for visual analysis; unrenderable files report uncertainty."""
        # 1. Unrenderable / corrupted PDF bytes -> honest uncertainty without crashing
        bad_pdf = ContentPayload(
            content_type="pdf",
            file_name="corrupted.pdf",
            file_bytes=b"%PDF-1.4 corrupted invalid bytes here",
            file_mime="application/pdf",
        )
        bad_flags = brand_check.check_brand(bad_pdf, guidelines=[], client=mock_client)

        assert len(bad_flags) >= 1
        # Must report uncertainty and escalate for human review
        assert any(f.state == "unclear" for f in bad_flags)
        assert any(needs_human(f.state) for f in bad_flags)
        assert any("manual" in (f.uncertainty_note or "").lower() or "rendering" in (f.explanation or "").lower() for f in bad_flags)

        # 2. Renderable PDF page via PyMuPDF
        import pymupdf

        doc = pymupdf.open()
        page = doc.new_page(width=300, height=300)
        page.insert_text((50, 50), "Inkloom Compliance Document", fontsize=16)
        valid_pdf_bytes = doc.tobytes()
        doc.close()

        valid_pdf = ContentPayload(
            content_type="pdf",
            file_name="renderable.pdf",
            file_bytes=valid_pdf_bytes,
            file_mime="application/pdf",
        )
        valid_flags = brand_check.check_brand(valid_pdf, guidelines=[], client=mock_client)
        assert len(valid_flags) >= 1
        # Document visual layout is evaluated
        assert any("PDF Document" in f.passage or f.location == "Document visual layout" for f in valid_flags)

    def test_governance_insights_uses_actual_stored_flags(self, client):
        """Governance intelligence computes metrics strictly from actual repository flags."""
        # Submit 2 submissions with issues
        res1 = client.post(
            "/submissions",
            data={
                "content_type": "text",
                "role": "creator",
                "text": "Inkloom AI brings disruptive synergy and cheap rates.",
            },
        )
        sub1_id = res1.json()["id"]
        client.post(f"/submissions/{sub1_id}/check", json={"role": "creator"})

        res2 = client.post(
            "/submissions",
            data={
                "content_type": "text",
                "role": "creator",
                "text": "Our engine is rated #1 worldwide with 100% guarantee.",
            },
        )
        sub2_id = res2.json()["id"]
        client.post(f"/submissions/{sub2_id}/check", json={"role": "creator"})

        # Query GET /insights/recurring
        insights_res = client.get("/insights/recurring")
        assert insights_res.status_code == 200
        data = insights_res.json()

        # Contract preservation
        assert "top_guidelines" in data
        assert "state_counts" in data
        assert data["total_flags"] >= 2
        assert "governance_insights" in data
        assert data["governance_insights"] is not None

        gov = data["governance_insights"]
        assert gov["total_reviews_analyzed"] >= 2
        assert len(gov["top_recurring_violations"]) >= 1
        assert "Executive Governance Review" in gov["summary_narrative"]

        # Query direct GET /insights/governance endpoint
        gov_res = client.get("/insights/governance")
        assert gov_res.status_code == 200
        direct_gov = gov_res.json()
        assert direct_gov["total_reviews_analyzed"] >= 2
        assert len(direct_gov["top_recurring_violations"]) >= 1

    def test_frontend_contracts_preserved(self, client):
        """GET /insights/recurring strictly satisfies Alisha's frontend contract."""
        res = client.get("/insights/recurring")
        assert res.status_code == 200
        data = res.json()

        # serverApi.ts:37 assertions:
        assert isinstance(data["top_guidelines"], list)
        assert all(isinstance(item, dict) for item in data["top_guidelines"])
        assert isinstance(data["state_counts"], dict)
        assert not isinstance(data["state_counts"], list)
        assert all(isinstance(v, int) for v in data["state_counts"].values())
        assert isinstance(data["total_flags"], int)
