"""Round 2 tests for authentication, RBAC, org isolation, RAG accuracy, approvals, guideline rectification, contrast filtering, and async journeys."""

import io
import time

from fastapi.testclient import TestClient

from app.ai.brand_verification import verify_brand
from app.ai.claim_verification import verify_claims_against_evidence
from app.ai.client import GeminiClient
from app.ai.schemas import AccessibilityIssue, ExtractedClaim
from app.ai.suggestions_corrections import recheck_correction, validate_no_invented_facts
from app.ai.visual_accessibility import filter_false_positive_contrast_issues
from app.config import Settings
from app.main import create_app
from app.models import ContentPayload, GuidelineRef
from app.repository import InMemorySubmissionRepository
from retrieval.brand_rag import clear_local_brand_store, ingest_brand_doc, retrieve_guidelines
from retrieval.external_search import filter_relevant_external_evidence
from retrieval.schemas import ContentPayload as RetrievalPayload, ExternalEvidenceItem


def _make_strict_client():
    repo = InMemorySubmissionRepository()
    settings = Settings(
        frontend_origin="*",
        repo_backend="memory",
        require_auth=True,
        enforce_approval_gates=True,
        mock_ai=True,
        auth_secret="test-round2-secret",
    )
    app = create_app(repo=repo, settings=settings)
    return TestClient(app)


def _login(client: TestClient, email: str, password: str) -> str:
    res = client.post("/auth/login", json={"email": email, "password": password})
    assert res.status_code == 200, res.text
    return res.json()["access_token"]


def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_auth_login_failures_and_role_spoofing_blocked():
    client = _make_strict_client()

    # Unauthenticated requests fail with 401
    assert client.get("/submissions").status_code == 401
    assert client.post("/submissions", data={"content_type": "text", "text": "Hi"}).status_code == 401

    # Wrong password -> 401
    bad = client.post("/auth/login", json={"email": "creator@brightleaf.co", "password": "wrong"})
    assert bad.status_code == 401

    # Creator signs in and attempts to spoof manager role -> 403
    creator_tok = _login(client, "creator@brightleaf.co", "brightleaf123")
    res = client.post(
        "/submissions",
        data={"content_type": "text", "text": "BrightLeaf organic tea launch."},
        headers=_auth_header(creator_tok),
    )
    assert res.status_code == 201
    sub_id = res.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={}, headers=_auth_header(creator_tok))

    # Creator spoofing role='manager' on decision -> 403
    spoof = client.post(
        f"/submissions/{sub_id}/decision",
        json={"role": "manager", "decision": "approve"},
        headers=_auth_header(creator_tok),
    )
    assert spoof.status_code == 403


def test_separation_of_duties_prevents_self_approval():
    client = _make_strict_client()
    creator_tok = _login(client, "creator@brightleaf.co", "brightleaf123")
    manager_tok = _login(client, "manager@brightleaf.co", "brightleaf123")
    reviewer_tok = _login(client, "reviewer@brightleaf.co", "brightleaf123")

    # Create a clean compliant draft so no unresolved flags block approval
    create = client.post(
        "/submissions",
        data={"content_type": "text", "title": "Clean Tea Copy", "text": "BrightLeaf loose leaf tea is crafted in small batches."},
        headers=_auth_header(creator_tok),
    )
    assert create.status_code == 201
    sub_id = create.json()["id"]
    client.post(f"/submissions/{sub_id}/check", json={}, headers=_auth_header(creator_tok))

    # Creator cannot approve own submission
    self_mgr = client.post(
        f"/submissions/{sub_id}/decision",
        json={"decision": "approve"},
        headers=_auth_header(creator_tok),
    )
    assert self_mgr.status_code == 403

    # Manager cannot grant final approval
    mgr_ok = client.post(
        f"/submissions/{sub_id}/decision",
        json={"decision": "approve", "comment": "Looks aligned"},
        headers=_auth_header(manager_tok),
    )
    assert mgr_ok.status_code == 200

    mgr_final = client.post(
        f"/submissions/{sub_id}/decision",
        json={"decision": "approve"},
        headers=_auth_header(manager_tok),
    )
    assert mgr_final.status_code == 403

    # Authorised reviewer approves -> approved
    rev_ok = client.post(
        f"/submissions/{sub_id}/decision",
        json={"decision": "approve", "comment": "Signed off"},
        headers=_auth_header(reviewer_tok),
    )
    assert rev_ok.status_code == 200
    assert client.get(f"/submissions/{sub_id}", headers=_auth_header(creator_tok)).json()["submission"]["status"] == "approved"


def test_cross_organisation_isolation_submissions_and_rag():
    clear_local_brand_store()
    client = _make_strict_client()
    bl_creator = _login(client, "creator@brightleaf.co", "brightleaf123")
    bl_manager = _login(client, "manager@brightleaf.co", "brightleaf123")
    nk_creator = _login(client, "creator@nike.demo", "nike123")
    nk_manager = _login(client, "manager@nike.demo", "nike123")

    # BrightLeaf Manager uploads BrightLeaf-only guidelines
    bl_doc = b"Approved Fact: BrightLeaf sources 100% single-origin organic tea leaves.\nNever use buzzwords like synergy."
    up_bl = client.post(
        "/brand-docs",
        data={"title": "BrightLeaf Brand Book", "category": "guideline", "version": "1.0"},
        files={"file": ("brightleaf.txt", io.BytesIO(bl_doc), "text/plain")},
        headers=_auth_header(bl_manager),
    )
    assert up_bl.status_code == 201

    # Nike Manager uploads Nike-only guidelines
    nk_doc = b"Nike Swoosh clearspace must be 20px minimum. Just Do It campaign rules."
    up_nk = client.post(
        "/brand-docs",
        data={"title": "Nike Brand Identity", "category": "guideline", "version": "1.0"},
        files={"file": ("nike.txt", io.BytesIO(nk_doc), "text/plain")},
        headers=_auth_header(nk_manager),
    )
    assert up_nk.status_code == 201

    # Brand doc listing is strictly isolated per org
    bl_docs = client.get("/brand-docs", headers=_auth_header(bl_creator)).json()["documents"]
    nk_docs = client.get("/brand-docs", headers=_auth_header(nk_creator)).json()["documents"]
    assert all(d["org_id"] == "brightleaf" for d in bl_docs)
    assert all(d["org_id"] == "nike" for d in nk_docs)
    assert not any("Nike" in d["title"] for d in bl_docs)

    # RAG retrieval for BrightLeaf NEVER returns Nike rules
    retrieved_bl = retrieve_guidelines(
        RetrievalPayload(content_type="text", text="Swoosh logo and organic tea leaves", org_id="brightleaf", brand_name="BrightLeaf"),
        org_id="brightleaf",
        brand_name="BrightLeaf",
    )
    assert retrieved_bl
    assert all("Nike" not in g.document and "Swoosh" not in g.excerpt for g in retrieved_bl)

    # BrightLeaf submission is invisible to Nike
    sub_res = client.post(
        "/submissions",
        data={"content_type": "text", "text": "BrightLeaf organic tea is fresh."},
        headers=_auth_header(bl_creator),
    )
    sub_id = sub_res.json()["id"]
    assert len(client.get("/submissions", headers=_auth_header(nk_creator)).json()) == 0
    assert client.get(f"/submissions/{sub_id}", headers=_auth_header(nk_creator)).status_code == 404


def test_external_evidence_rejects_unrelated_company_and_prioritizes_brand_facts():
    unrelated = ExternalEvidenceItem(
        query="BrightLeaf organic tea sourced from Assam",
        url="https://solarleaf-power.example.com/about",
        title="SolarLeaf Power — Industrial Solar Grids",
        domain="solarleaf-power.example.com",
        published_date="2026-01-01",
        retrieved_at="2026-11-19T10:00:00Z",
        excerpt="SolarLeaf Power installs commercial rooftop panels in Texas.",
        status="ok",
    )
    related = ExternalEvidenceItem(
        query="BrightLeaf organic tea sourced from Assam",
        url="https://brightleaf.example.com/sourcing",
        title="BrightLeaf Sourcing Report",
        domain="brightleaf.example.com",
        published_date="2026-02-10",
        retrieved_at="2026-11-19T10:00:00Z",
        excerpt="BrightLeaf imports certified organic tea leaves directly from Assam estates.",
        status="ok",
    )
    filtered = filter_relevant_external_evidence(
        [unrelated, related],
        claim_text="BrightLeaf organic tea is sourced from Assam.",
        brand_name="BrightLeaf",
        org_domain="brightleaf.example.com",
    )
    assert filtered[0].status == "unavailable"
    assert filtered[0].entity_matched is False
    assert "unrelated_company_source" in (filtered[0].rejected_reason or "")
    assert filtered[1].status == "ok"
    assert filtered[1].entity_matched is True

    # Approved internal brand fact prioritizes internal truth even without external sources
    claim = ExtractedClaim(
        claim_id="c-1",
        text="BrightLeaf uses 100% single-origin organic tea leaves.",
        claim_type="fact",
        passage="BrightLeaf uses 100% single-origin organic tea leaves.",
        location="paragraph 1",
    )
    fact_guideline = GuidelineRef(
        document="BrightLeaf Approved Facts",
        passage_ref="Section 1",
        excerpt="Approved Fact: BrightLeaf uses 100% single-origin organic tea leaves.",
        category="approved_fact",
        match_type="approved_fact",
    )
    out = verify_claims_against_evidence(
        claims=[claim],
        evidence_map={"c-1": [unrelated]},
        client=GeminiClient(mock_mode=True),
        auto_fetch_evidence=False,
        guidelines=[fact_guideline],
        brand_name="BrightLeaf",
    )
    assert out.findings[0].state == "supported"
    assert out.findings[0].suggested_fix is None


def test_anti_fabrication_blocks_invented_descriptions_and_compliant_has_no_false_warnings():
    ok, reason = validate_no_invented_facts(
        original_passage="Our software saves teams time.",
        suggested_replacement="Our Horizon Pro X9 saves teams 47% time using ISO-9999 encryption.",
    )
    assert ok is False
    assert "Anti-fabrication guard" in (reason or "")

    passed, notes = recheck_correction(
        original_passage="Our software delivers value.",
        suggested_replacement="Our Acme Ultra Suite delivers 88% ROI and $5000 savings every month with guaranteed zero downtime.",
        finding_type="brand",
        state="potential_issue",
        client=GeminiClient(mock_mode=True),
    )
    assert passed is False
    assert "Anti-fabrication" in notes or "superlative" in notes.lower()

    # Compliant text yields aligned finding with suggested_fix=None
    bv = verify_brand(
        ContentPayload(content_type="text", text="BrightLeaf crafts clean, plain-language organic tea."),
        guidelines=[
            GuidelineRef(
                document="Brand Playbook",
                passage_ref="Section 1.3",
                excerpt="Use clear, plain English and avoid buzzwords.",
            )
        ],
        client=GeminiClient(mock_mode=True),
    )
    assert bv.overall_alignment == "aligned"
    assert all(f.state == "aligned" and f.suggested_fix is None for f in bv.findings)


def test_unsafe_approval_blocked_unless_authorised_override_and_edit_invalidates_approval():
    client = _make_strict_client()
    creator_tok = _login(client, "creator@inkloom.ai", "inkloom123")
    manager_tok = _login(client, "manager@inkloom.ai", "inkloom123")
    reviewer_tok = _login(client, "reviewer@inkloom.ai", "inkloom123")

    # Draft with unresolved issue ("disruptive synergy")
    res = client.post(
        "/submissions",
        data={"content_type": "text", "title": "Synergy Launch", "text": "Our tool brings disruptive synergy."},
        headers=_auth_header(creator_tok),
    )
    sub_id = res.json()["id"]
    check = client.post(f"/submissions/{sub_id}/check", json={}, headers=_auth_header(creator_tok)).json()
    open_blocking = [f for f in check["flags"] if f["state"] in ("potential_issue", "contradicted", "insufficient_evidence", "unclear")]
    assert len(open_blocking) >= 1

    # Manager approval without resolving or override -> 409 Conflict!
    blocked = client.post(
        f"/submissions/{sub_id}/decision",
        json={"decision": "approve"},
        headers=_auth_header(manager_tok),
    )
    assert blocked.status_code == 409

    # Manager approval WITH authorised override and >= 10 char reason -> 200 & audited
    override_ok = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "decision": "approve",
            "override_unresolved": True,
            "override_reason": "Executive campaign deadline approved by legal counsel.",
        },
        headers=_auth_header(manager_tok),
    )
    assert override_ok.status_code == 200
    assert override_ok.json()["override_unresolved"] is True

    # Final reviewer approves with override -> approved
    rev_ok = client.post(
        f"/submissions/{sub_id}/decision",
        json={
            "decision": "approve",
            "override_unresolved": True,
            "override_reason": "Final legal compliance waiver documented.",
        },
        headers=_auth_header(reviewer_tok),
    )
    assert rev_ok.status_code == 200
    assert client.get(f"/submissions/{sub_id}", headers=_auth_header(creator_tok)).json()["submission"]["status"] == "approved"

    # Editing approved content creates v2, resets status to draft, preserves v1 snapshot & decisions!
    revise = client.post(
        f"/submissions/{sub_id}/revise",
        data={"content_type": "text", "text": "Our tool brings effective collaboration."},
        headers=_auth_header(creator_tok),
    )
    assert revise.status_code == 200
    rev_data = revise.json()
    assert rev_data["version"] == 2
    assert rev_data["status"] == "draft"

    # v1 snapshot, flags, and decisions are preserved when querying ?version=1
    v1_detail = client.get(f"/submissions/{sub_id}?version=1", headers=_auth_header(creator_tok)).json()
    assert v1_detail["version_snapshot"]["text"] == "Our tool brings disruptive synergy."
    assert len(v1_detail["decisions"]) == 2
    assert len(v1_detail["flags"]) >= 1

    audit_actions = [e["action"] for e in client.get(f"/submissions/{sub_id}/audit", headers=_auth_header(creator_tok)).json()]
    assert "authorised_override" in audit_actions
    assert "approval_invalidated" in audit_actions


def test_guideline_rectification_scan_approve_and_version_preservation():
    clear_local_brand_store()
    client = _make_strict_client()
    bl_manager = _login(client, "manager@brightleaf.co", "brightleaf123")
    bl_creator = _login(client, "creator@brightleaf.co", "brightleaf123")

    # Upload guidelines containing expired, unclear, conflicting, and duplicate rules
    doc_v1 = (
        "1. Campaign Rule\n"
        "Summer 2024 promo pricing ends 2024: offer 50% off only in Q2 2024.\n\n"
        "2. Tone Standard\n"
        "Always use an appropriate and reasonable tone as needed.\n\n"
        "3. Punctuation Rule A\n"
        "Never use exclamation marks in marketing copy!\n\n"
        "4. Punctuation Rule B\n"
        "Always encourage exclamation marks in marketing copy for energy.\n\n"
        "5. Duplicate Rule\n"
        "Always use an appropriate and reasonable tone as needed.\n"
    ).encode("utf-8")
    up = client.post(
        "/brand-docs",
        data={"title": "BrightLeaf Rules", "category": "guideline", "version": "1.0"},
        files={"file": ("rules.txt", io.BytesIO(doc_v1), "text/plain")},
        headers=_auth_header(bl_manager),
    )
    assert up.status_code == 201
    doc1_id = up.json()["id"]

    # Scan for rectification issues
    scan = client.post("/brand-docs/rectifications/scan", headers=_auth_header(bl_manager))
    assert scan.status_code == 200
    rects = scan.json()["rectifications"]
    issue_types = {r["issue_type"] for r in rects}
    assert "expired" in issue_types
    assert "unclear" in issue_types
    assert "duplicate" in issue_types or "conflicting" in issue_types

    # Creator cannot approve guideline rectification (403)
    target = next(r for r in rects if r["issue_type"] == "unclear")
    forbidden = client.post(
        f"/brand-docs/rectifications/{target['id']}/approve",
        json={"approved_wording": "Use active voice and avoid vague superlatives."},
        headers=_auth_header(bl_creator),
    )
    assert forbidden.status_code == 403

    # Manager edits & approves rectification -> publishes v1.1 while keeping v1.0 archived!
    approved = client.post(
        f"/brand-docs/rectifications/{target['id']}/approve",
        json={"approved_wording": "Use measured, plain-English sentences without slang or corporate buzzwords."},
        headers=_auth_header(bl_manager),
    )
    assert approved.status_code == 200
    new_doc = approved.json()["new_document"]
    assert new_doc["version"] == "1.1"
    assert new_doc["previous_version_id"] == doc1_id

    # Previous version remains inspectable in version history
    versions = client.get(f"/brand-docs/{new_doc['id']}/versions", headers=_auth_header(bl_creator)).json()["versions"]
    assert len(versions) == 2
    assert any(v["version"] == "1.0" and v["is_active"] is False for v in versions)
    assert any(v["version"] == "1.1" and v["is_active"] is True for v in versions)

    # Future RAG retrieval uses v1.1 wording, not v1.0!
    rag = retrieve_guidelines(
        RetrievalPayload(content_type="text", text="corporate buzzwords and tone", org_id="brightleaf"),
        org_id="brightleaf",
    )
    assert any("1.1" in g.document and "corporate buzzwords" in g.excerpt for g in rag)


def test_contrast_false_positive_filter_drops_passing_pairs():
    passing_dark_on_white = AccessibilityIssue(
        issue_type="contrast",
        description="[Visual Estimate: Calculated Contrast] Body text #111827 on #FFFFFF has 17.7:1 contrast.",
        severity="low",
        element_location="body paragraph",
        recommendation="Keep dark text.",
    )
    passing_large_cta = AccessibilityIssue(
        issue_type="contrast",
        description="[Visual Estimate: Calculated Contrast] Large headline #767676 on #FFFFFF yields 4.54:1 contrast.",
        severity="low",
        element_location="hero heading",
        recommendation="No change needed.",
    )
    failing_light_gray = AccessibilityIssue(
        issue_type="contrast",
        description="[Visual Estimate: Calculated Contrast] Label text #94A3B8 on #FFFFFF yields 2.61:1 contrast, below 4.5:1.",
        severity="high",
        element_location="footer caption",
        recommendation="Darken text to #475569.",
    )
    kept = filter_false_positive_contrast_issues([passing_dark_on_white, passing_large_cta, failing_light_gray])
    assert len(kept) == 1
    assert "#94A3B8" in kept[0].description


def test_async_check_status_retry_draft_hints_and_recurring_coaching():
    clear_local_brand_store()
    client = _make_strict_client()
    creator_tok = _login(client, "creator@brightleaf.co", "brightleaf123")
    manager_tok = _login(client, "manager@brightleaf.co", "brightleaf123")

    # Upload guideline with forbidden term
    ingest_brand_doc(
        file_bytes=b'Terminology Rules\nProhibited: never use "synergy" or "game-changing".\nUse "effective collaboration" instead.',
        filename="lexicon.txt",
        title="BrightLeaf Lexicon",
        org_id="brightleaf",
        brand_name="BrightLeaf",
    )

    # 1. Brand Constitution endpoint surfaces extracted forbidden terms
    const = client.get("/brand-constitution", headers=_auth_header(creator_tok)).json()
    assert "synergy" in [t.lower() for t in const["forbidden_terms"]]

    # 2. Live draft hints catch prohibited term while typing
    hint_res = client.post(
        "/submissions/draft-hints",
        json={"text": "Line 1 ok.\nLine 2 brings synergy to tea."},
        headers=_auth_header(creator_tok),
    )
    assert hint_res.status_code == 200
    assert any("synergy" in h["message"].lower() and h["line_number"] == 2 for h in hint_res.json()["hints"])

    # 3. Create two prior submissions with 'synergy' so recurring hints trigger on the 3rd!
    for idx in range(2):
        r = client.post(
            "/submissions",
            data={"content_type": "text", "text": f"Prior draft {idx} with disruptive synergy."},
            headers=_auth_header(creator_tok),
        )
        client.post(f"/submissions/{r.json()['id']}/check", json={}, headers=_auth_header(creator_tok))

    # 4. Async check + status polling on 3rd submission
    r3 = client.post(
        "/submissions",
        data={"content_type": "text", "text": "Line 1 clean.\nLine 2 disruptive synergy campaign."},
        headers=_auth_header(creator_tok),
    )
    sub_id = r3.json()["id"]
    async_res = client.post(
        f"/submissions/{sub_id}/check",
        json={"async_mode": True},
        headers=_auth_header(creator_tok),
    )
    assert async_res.status_code == 200
    assert async_res.json()["submission"]["status"] == "ai_review"

    for _ in range(30):
        st = client.get(f"/submissions/{sub_id}/status", headers=_auth_header(creator_tok)).json()
        if st["status"] == "manager_review":
            break
        time.sleep(0.05)

    detail = client.get(f"/submissions/{sub_id}", headers=_auth_header(creator_tok)).json()
    assert detail["submission"]["status"] == "manager_review"
    assert len(detail["recurring_hints"]) >= 1
    assert "recurring" in detail["recurring_hints"][0]["message"].lower()
    assert detail["brand_score"] is not None

    # 5. Image file replacement on revision creates v2 cleanly
    png1 = b"\x89PNG\r\n\x1a\n" + b"\x00" * 30
    png2 = b"\x89PNG\r\n\x1a\n" + b"\x01" * 40
    img_sub = client.post(
        "/submissions",
        data={"content_type": "image", "title": "Ad Banner"},
        files={"file": ("v1.png", io.BytesIO(png1), "image/png")},
        headers=_auth_header(creator_tok),
    ).json()
    client.post(f"/submissions/{img_sub['id']}/check", json={}, headers=_auth_header(creator_tok))
    client.post(
        f"/submissions/{img_sub['id']}/decision",
        json={"decision": "request_changes", "comment": "Replace logo image"},
        headers=_auth_header(manager_tok),
    )
    rep = client.post(
        f"/submissions/{img_sub['id']}/revise",
        data={"content_type": "image"},
        files={"file": ("v2.png", io.BytesIO(png2), "image/png")},
        headers=_auth_header(creator_tok),
    )
    assert rep.status_code == 200
    assert rep.json()["file_name"] == "v2.png"

    # 6. Compliance certificate endpoint returns structured summary
    cert = client.get(f"/submissions/{sub_id}/certificate", headers=_auth_header(creator_tok))
    assert cert.status_code == 200
    assert cert.json()["organisation"] == "BrightLeaf"
