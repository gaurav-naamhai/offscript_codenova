import pytest

from app.ai.suggestions_corrections import validate_no_invented_facts
from app.models import FlagDraft, GuidelineRef
from app.pipeline import ground_visual_finding
from retrieval.chunker import compile_brand_constitution
from retrieval.schemas import PageText


def test_numeric_prohibition_is_never_an_approved_fact():
    result = compile_brand_constitution([PageText(page_number=1, text='Approved facts\nFictional Stride sells shoes.\nDo not claim 50% off all shoes.')])
    assert not any('50%' in fact for fact in result['approved_facts'])
    assert any('Do not claim 50%' in rule for rule in result['forbidden_terms'])


def test_unsupported_short_product_benefit_requires_human_edit():
    assert not validate_no_invented_facts('Nike is best.', 'Nike helps you achieve your running goals.')[0]
    guidance = [GuidelineRef(document='Fictional facts', passage_ref='1', excerpt='Fictional Stride helps you achieve your running goals.')]
    assert validate_no_invented_facts('Fictional Stride is best.', guidance[0].excerpt, guidelines=guidance)[0]


@pytest.mark.parametrize('format', ['image', 'pdf'])
def test_visual_observation_cannot_borrow_unrelated_guideline(format):
    unrelated = GuidelineRef(document='Fictional offers', passage_ref='1', excerpt='Offers must not exceed 20% off.')
    draft = FlagDraft(finding_type='brand', state='potential_issue', passage='Logo is distorted', location=format,
                      explanation='Logo appears stretched', why_it_matters='Visual observation', guideline_ref=unrelated)
    result = ground_visual_finding(draft, [unrelated])
    assert result.state == 'unclear' and result.guideline_ref is None
    assert result.suggested_correction is None and result.uncertainty_note
    assert 'General visual' in result.explanation


def test_matching_visual_rule_retains_real_reference():
    rule = GuidelineRef(document='Fictional identity', passage_ref='1', excerpt='The logo must not be stretched.')
    draft = FlagDraft(finding_type='brand', state='potential_issue', passage='Logo is stretched', location='image',
                      explanation='Logo distortion', why_it_matters='Identity', guideline_ref=rule)
    assert ground_visual_finding(draft, [rule]).guideline_ref == rule


def test_word_review_is_rejected(client):
    response = client.post('/submissions', data={'content_type': 'docx', 'role': 'creator'}, files={'file': ('synthetic.docx', b'synthetic', 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
    assert response.status_code == 422


def test_fictional_pdf_guideline_preserves_negative_rule():
    import fitz
    from retrieval.extractor import extract_document

    pdf = fitz.open()
    page = pdf.new_page()
    page.insert_text((50, 70), 'Fictional Stride sells shoes.\nDo not claim 50% off all shoes.\nMaximum discount is 20%.')
    data = pdf.tobytes()
    pdf.close()
    extracted = extract_document(data, 'fictional-guidelines.pdf', 'application/pdf')
    result = compile_brand_constitution(extracted.pages)
    assert any('Do not claim 50%' in rule for rule in result['forbidden_terms'])
    assert not any('50%' in fact for fact in result['approved_facts'])
