from types import SimpleNamespace
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest

from app.ai import client
from app.models import ContentPayload, FlagDraft
from app.pipeline import run_pipeline


@pytest.mark.parametrize('code', [429, 503])
def test_provider_cooldown_prevents_another_call_and_respects_delay(monkeypatch, code):
    monkeypatch.setattr(client, '_COOLDOWN_UNTIL', 0)
    now = [100.0]
    monkeypatch.setattr(client.time, 'monotonic', lambda: now[0])
    calls = []
    def unavailable(**kw):
        calls.append(1)
        exc = RuntimeError('synthetic diagnostic must not reach user')
        exc.code = code
        exc.response = SimpleNamespace(headers={'Retry-After': '12'})
        raise exc
    with pytest.raises(client.GeminiQuotaError, match='13 seconds'):
        client.bounded_generate(unavailable)
    with pytest.raises(client.GeminiQuotaError):
        client.bounded_generate(unavailable)
    assert len(calls) == 1
    now[0] = 113
    assert client.bounded_generate(lambda: 'recovered') == 'recovered'


def test_google_retry_delay_is_parsed():
    assert client.provider_retry_delay(RuntimeError('{"retryDelay": "45s"}')) == 45


def test_concurrent_generation_is_bounded(monkeypatch):
    monkeypatch.setattr(client, '_COOLDOWN_UNTIL', 0)
    active = 0
    peak = 0
    lock = threading.Lock()
    two_started = threading.Event()
    release = threading.Event()
    def call():
        nonlocal active, peak
        with lock:
            active += 1
            peak = max(peak, active)
            if active == 2: two_started.set()
        assert release.wait(3)
        with lock: active -= 1
    with ThreadPoolExecutor(4) as pool:
        futures = [pool.submit(client.bounded_generate, call) for _ in range(4)]
        assert two_started.wait(2)
        release.set()
        for future in futures: future.result()
    assert peak == 2


def test_partial_findings_survive_provider_error():
    def failure(*args, **kw):
        raise client.GeminiQuotaError('AI request limit reached. Retry in about 20 seconds.')
    flags, degraded = run_pipeline(ContentPayload(content_type='text', text='Synthetic claim'), 'synthetic',
        retrieval_fn=lambda _: [], verification_fn=failure,
        brand_check_fn=lambda *_: [FlagDraft(finding_type='brand', state='potential_issue', passage='Synthetic claim', location='1', explanation='Synthetic finding', why_it_matters='Test')])
    assert len(flags) == 2
    assert any(f.origin == 'error' and '20 seconds' in f.explanation for f in flags)
    assert any(f.origin != 'error' for f in flags)
    assert degraded[0].module == 'verification'


def test_unsubstantiated_positive_visual_summary_is_omitted():
    from app.pipeline import ground_visual_finding
    draft = FlagDraft(finding_type='brand', state='aligned', passage='Logo looks fine', location='image', explanation='Logo aligned', why_it_matters='Visual identity')
    assert ground_visual_finding(draft, []) is None
    draft.state = 'potential_issue'
    assert ground_visual_finding(draft, []) is not None


def test_public_provider_error_does_not_include_raw_response():
    from app.pipeline import _make_error_flag
    flag = _make_error_flag('verification', 'synthetic', 1, '2026', '429 RESOURCE_EXHAUSTED SECRET_RESPONSE_BODY Retry in about 12 seconds')
    assert 'SECRET_RESPONSE_BODY' not in flag.explanation
    assert 'SECRET_RESPONSE_BODY' not in flag.uncertainty_note
    assert '12 seconds' in flag.explanation


def test_sdk_retry_layer_is_disabled_and_503_is_not_repeated(monkeypatch):
    from pydantic import BaseModel
    class Output(BaseModel):
        ok: bool
    monkeypatch.setattr(client, '_COOLDOWN_UNTIL', 0)
    calls = []
    def generate(**kwargs):
        calls.append(kwargs)
        assert kwargs['config'].http_options.retry_options.attempts == 1
        exc = RuntimeError('503 UNAVAILABLE')
        exc.code = 503
        raise exc
    instance = client.GeminiClient(mock_mode=True)
    instance.mock_mode = False
    instance._client = SimpleNamespace(models=SimpleNamespace(generate_content=generate))
    with pytest.raises(client.GeminiQuotaError, match='busy'):
        instance.generate_structured('Synthetic request', Output)
    assert len(calls) == 1
