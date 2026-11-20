"""Synthetic accuracy controls; no hosted organisation data or provider calls."""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.ai.claim_verification import claim_finding_to_flag_draft, verify_claims_against_evidence
from app.ai.brand_verification import validate_and_ground_findings
from app.ai.client import GeminiClient
from app.ai.guideline_rectification import _expired_date, scan_guidelines_for_rectification
from app.ai.governance_intelligence import compute_draft_hints, compute_recurring_hints
from app.ai.schemas import BrandFinding, ClaimFinding, ClaimVerificationOutput, ExtractedClaim
from app.models import ContentPayload, Flag, GuidelineRef
from app.config import Settings
from app.main import create_app
from app.plugins.retrieval import retrieve_guidelines
from app.repository import InMemorySubmissionRepository
from retrieval.external_search import filter_relevant_external_evidence
from retrieval.chunker import compile_brand_constitution
from retrieval.brand_rag import (clear_local_brand_store, create_rectified_brand_doc_version,
                                 get_brand_doc_chunks, ingest_brand_doc, list_brand_docs)
from retrieval.schemas import ExternalEvidenceItem, PageText


CONTROL = (
    "BrightLeaf helps teams organise email campaigns. Customers can receive up to "
    "20% off selected annual plans. The offer expires on 30 November 2026."
)


def test_exact_approved_offer_and_expiry_do_not_contradict_each_other():
    guideline = GuidelineRef(document="Synthetic BrightLeaf approved offer", passage_ref="Offer",
                             excerpt="Approved fact: " + CONTROL, org_id="brightleaf",
                             category="approved_fact")
    claims = [ExtractedClaim(claim_id=str(index), text=sentence, passage=sentence,
                             claim_type="fact", location="draft")
              for index, sentence in enumerate(CONTROL.split(". "))]
    result = verify_claims_against_evidence(claims, evidence_map={}, client=GeminiClient(mock_mode=True),
                                            auto_fetch_evidence=False, guidelines=[guideline], brand_name="BrightLeaf")
    assert len(result.findings) == 3
    assert all(f.state == "supported" and f.suggested_fix is None for f in result.findings)
    sourced = claim_finding_to_flag_draft(result.findings[-1], internal_guideline=guideline)
    assert sourced.evidence_mode == "internal_only"
    assert sourced.guideline_ref.document_id == guideline.document_id
    assert sourced.internal_evidence[0].retrieved_chunk_text == guideline.excerpt
    changed = ExtractedClaim(claim_id="changed", text="The offer expires on 30 December 2026.",
                             passage="The offer expires on 30 December 2026.", claim_type="fact", location="draft")
    unsupported = verify_claims_against_evidence([changed], evidence_map={}, client=GeminiClient(mock_mode=True),
                                                  auto_fetch_evidence=False, guidelines=[guideline], brand_name="BrightLeaf")
    assert unsupported.findings[0].state != "supported"


def test_brand_finding_cannot_call_exact_current_approved_offer_unsupported():
    guideline = GuidelineRef(document="Synthetic BrightLeaf approved offer", passage_ref="Offer",
                             excerpt="Approved fact: " + CONTROL, category="approved_fact")
    finding = BrandFinding(state="potential_issue", passage="The offer expires on 30 November 2026.",
                           location="draft", explanation="The expiry is unsupported by approved facts.",
                           why_it_matters="Offer accuracy", guideline_document=guideline.document,
                           guideline_section=guideline.passage_ref,
                           suggested_fix="The offer expires on an invented date.")
    grounded = validate_and_ground_findings([finding], [guideline])[0]
    assert grounded.state == "aligned"
    assert grounded.suggested_fix is None


def test_rectification_publishes_only_selected_rule_and_rejects_stale_repeat():
    clear_local_brand_store()
    source = ingest_brand_doc(b"Use a friendly tone. Use appropriate language and avoid inappropriate wording.",
                              "synthetic-rules.txt", "Synthetic Rules", org_id="synthetic-accuracy")
    chunk = next(c for c in get_brand_doc_chunks(source.id) if "friendly tone" in c["content"])
    assert "appropriate language" in chunk["content"]
    published = create_rectified_brand_doc_version(
        source.id, chunk["id"], "Use a warm, plain-language tone.", "synthetic-accuracy",
        expected_current_version="1.0", target_rule_text="Use a friendly tone.")
    revised = get_brand_doc_chunks(published.id)[0]["content"]
    assert "Use a warm, plain-language tone." in revised
    assert "Use appropriate language and avoid inappropriate wording." in revised
    assert len([d for d in list_brand_docs(org_id="synthetic-accuracy") if d["family_id"] == source.family_id]) == 1
    with pytest.raises(ValueError, match="older guideline version"):
        create_rectified_brand_doc_version(source.id, chunk["id"], "Use a measured tone.",
                                           "synthetic-accuracy", expected_current_version="1.0",
                                           target_rule_text="Use a friendly tone.")


def test_failed_local_replacement_keeps_previous_active_guideline():
    clear_local_brand_store()
    source = ingest_brand_doc(b"Use a friendly tone.", "rules.txt", "Synthetic Rules",
                              org_id="synthetic-failure")
    with pytest.raises(ValueError, match="No readable text"):
        ingest_brand_doc(b"", "empty.txt", "Synthetic Rules", org_id="synthetic-failure",
                         previous_version_id=source.id)
    active = list_brand_docs(org_id="synthetic-failure")
    assert [d["id"] for d in active] == [source.id]
    assert "Use a friendly tone." in get_brand_doc_chunks(source.id)[0]["content"]


def test_brand_specific_external_source_requires_exact_approved_domain():
    def evidence(host):
        return ExternalEvidenceItem(query=CONTROL, url=f"https://{host}/offer", domain=host,
                                    title="BrightLeaf offer", excerpt=CONTROL,
                                    retrieved_at="2026-11-20T00:00:00Z")
    bad, suffix, good = filter_relevant_external_evidence(
        [evidence("brightleaf-solar.example"), evidence("brightleaf.example.evil"),
         evidence("offers.brightleaf.example")], CONTROL, brand_name="BrightLeaf",
        org_domain="brightleaf.example")
    assert not bad.entity_matched and bad.status == "unavailable"
    assert not suffix.entity_matched and suffix.status == "unavailable"
    assert good.entity_matched and good.status == "ok"
    spoof = evidence("unrelated.example")
    spoof.domain = "brightleaf.example"
    assert not filter_relevant_external_evidence([spoof], CONTROL, brand_name="BrightLeaf",
                                                 org_domain="brightleaf.example")[0].entity_matched


def test_negated_approved_fact_does_not_support_positive_claim():
    guideline = GuidelineRef(document="Synthetic facts", passage_ref="Offer", category="approved_fact",
                             excerpt="Approved fact: Customers cannot receive 20% off selected annual plans.")
    claim = ExtractedClaim(claim_id="offer", text="Customers can receive 20% off selected annual plans.",
                           passage="Customers can receive 20% off selected annual plans.",
                           claim_type="fact", location="draft")
    result = verify_claims_against_evidence([claim], evidence_map={}, client=GeminiClient(mock_mode=True),
                                            auto_fetch_evidence=False, guidelines=[guideline])
    assert result.findings[0].state == "insufficient_evidence"


def test_live_verdict_cannot_promote_reachable_but_inexact_source_to_support():
    claim = ExtractedClaim(claim_id="offer", text="Customers receive 20% off annual plans.",
                           passage="Customers receive 20% off annual plans.", claim_type="fact", location="draft")
    evidence = ExternalEvidenceItem(query=claim.text, url="https://brightleaf.example/annual",
                                    domain="brightleaf.example", title="Annual plans",
                                    excerpt="BrightLeaf offers selected annual plans and discounts to customers.",
                                    retrieved_at="2026-11-20T00:00:00Z")
    class ModelStub:
        mock_mode = False

        def generate_structured(self, **_kwargs):
            return ClaimVerificationOutput(findings=[ClaimFinding(
                claim_text=claim.text, passage=claim.passage, location="draft", state="supported",
                explanation="The page supports the offer.", why_it_matters="Offer accuracy",
                evidence_source_url=evidence.url, evidence_quality="reliable",
                suggested_fix="Customers receive a guaranteed 20% off annual plans.")])

    result = verify_claims_against_evidence([claim], evidence_map={"offer": [evidence]},
                                            client=ModelStub(), auto_fetch_evidence=False,
                                            brand_name="BrightLeaf")
    assert result.findings[0].state == "insufficient_evidence"
    assert result.findings[0].suggested_fix is None


def test_rectification_detects_atomic_rules_and_only_past_expiry():
    content = ("Use a friendly tone. Use a friendly tone.\n"
               "Headlines must always use exclamation marks. Headlines must never use exclamation marks.\n"
               "Use appropriate language and avoid inappropriate wording.\n"
               "The offer expires on 30 November 2026.\n"
               "The old offer expired on 30 October 2026.")
    chunks = [{"id": "chunk-1", "document_id": "doc-1", "doc_title": "Synthetic Rules",
               "doc_version": "1.0", "content": content}]
    proposals = scan_guidelines_for_rectification(chunks, org_id="brightleaf")
    kinds = {p.issue_type for p in proposals}
    assert {"duplicate", "conflicting", "unclear", "expired"} <= kinds
    assert _expired_date("Expires on 30 November 2026", date(2026, 11, 20)) is None
    assert _expired_date("Expired on 30 October 2026", date(2026, 11, 20)) == date(2026, 10, 30)
    assert all("inapproved" not in p.suggested_wording.lower() for p in proposals)
    assert all("WCAG" not in p.suggested_wording for p in proposals)


def test_discount_ceiling_and_prohibited_example_are_compatible():
    chunks = [{"id": "one", "document_id": "doc", "content":
               "Maximum 20% discount on annual plans. Never advertise 99% off annual plans."}]
    proposals = scan_guidelines_for_rectification(chunks, org_id="synthetic")
    assert not any(p.issue_type == "conflicting" for p in proposals)


def test_colour_palette_does_not_inherit_forbidden_terms_section():
    constitution = compile_brand_constitution([PageText(page_number=1,
        text="Forbidden Terms:\n'cheap'\nColour Palette:\nPrimary: #AABBCC\nSecondary: #112233",
        extraction_method="plain_text")])
    assert "cheap" in constitution["forbidden_terms"]
    assert not any("#" in term for term in constitution["forbidden_terms"])
    assert {"#AABBCC", "#112233"} <= set(constitution["brand_colors"])


def _flag(submission_id, passage, status="open", version=1):
    return Flag(id=f"{submission_id}-{version}-{status}", submission_id=submission_id, version=version,
                finding_type="brand", state="potential_issue", passage=passage, location="draft",
                explanation="Incorrect brand terminology", why_it_matters="Use approved spelling",
                status=status, created_at="2026-11-20T00:00:00Z")


def test_coaching_respects_case_resolution_and_unique_submissions():
    constitution = compile_brand_constitution([
        PageText(page_number=1, text="Avoid 'Brightleaf'; use 'BrightLeaf'.", extraction_method="plain_text")
    ])
    assert constitution["forbidden_terms"] == ["Brightleaf"]
    assert constitution["preferred_terms"] == ["BrightLeaf"]
    assert not compute_draft_hints("BrightLeaf is ready.", constitution=constitution)
    assert compute_draft_hints("Brightleaf is ready.", constitution=constitution)
    history = [_flag("one", "Brightleaf"), _flag("one", "Brightleaf", version=2),
               _flag("two", "Brightleaf", status="dismissed")]
    assert not compute_draft_hints("Brightleaf is ready.", historical_flags=history)
    assert not compute_recurring_hints([_flag("current", "Brightleaf")], history)
    history.append(_flag("three", "Brightleaf"))
    assert compute_draft_hints("Brightleaf is ready.", historical_flags=history)
    assert not compute_draft_hints("BrightLeaf is ready.", historical_flags=history)
    assert compute_recurring_hints([_flag("current", "Brightleaf")], history)[0].count == 2


def test_live_retrieval_never_substitutes_generic_fixture_for_missing_org(monkeypatch):
    monkeypatch.setattr("retrieval.config.GEMINI_API_KEY", "")
    monkeypatch.setattr("retrieval.config.SUPABASE_URL", "")
    monkeypatch.setattr("retrieval.config.SUPABASE_KEY", "")
    monkeypatch.setenv("MOCK_AI", "false")
    with pytest.raises(RuntimeError, match="not configured"):
        retrieve_guidelines(ContentPayload(content_type="text", text="Synthetic", org_id="isolated-missing-org"))


def test_insights_separate_finding_events_from_unique_current_open_issues():
    repo = InMemorySubmissionRepository()
    client = TestClient(create_app(repo=repo, settings=Settings(repo_backend="memory", require_auth=False,
                                                               mock_ai=True, auth_secret="synthetic-test-secret")))
    sub_id = client.post("/submissions", data={"content_type": "text", "role": "creator",
                                               "text": "Synthetic Brightleaf claim"}).json()["id"]
    repo._flags[sub_id][1] = [_flag(sub_id, "Brightleaf"), _flag(sub_id, "Brightleaf", version=1),
                              _flag(sub_id, "Other", status="dismissed")]
    result = client.get("/insights/recurring").json()
    assert result["total_flags"] == 3
    assert result["unique_open_issues"] == 1
    assert result["affected_submissions"] == 1
