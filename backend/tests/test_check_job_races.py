import asyncio
import threading

from fastapi.testclient import TestClient

from app.config import Settings
from app.main import create_app
from app.models import Submission, VersionSnapshot
from app.repository import InMemorySubmissionRepository


def test_running_check_rejects_retry_edit_and_request_changes(monkeypatch):
    import app.main as main

    started, release = threading.Event(), threading.Event()

    def blocked_pipeline(*args):
        started.set()
        assert release.wait(5)
        return [], []

    monkeypatch.setattr(main, 'run_pipeline', blocked_pipeline)
    app = create_app(repo=InMemorySubmissionRepository(), settings=Settings(require_auth=False, demo_mode=False))
    with TestClient(app) as client:
        sid = client.post('/submissions', data={'content_type': 'text', 'role': 'creator', 'text': 'Synthetic false claim'}).json()['id']
        try:
            assert client.post(f'/submissions/{sid}/check', json={'role': 'creator', 'async_mode': True}).status_code == 200
            assert started.wait(2)
            assert client.post(f'/submissions/{sid}/retry-check', json={'role': 'creator', 'async_mode': True}).status_code == 409
            assert client.post(f'/submissions/{sid}/revise', data={'content_type': 'text', 'role': 'creator', 'text': 'Changed', 'create_new_version': 'true'}).status_code == 409
            assert client.post(f'/submissions/{sid}/decision', json={'role': 'manager', 'decision': 'request_changes'}).status_code == 409
        finally:
            release.set()


def test_stale_job_cannot_replace_newer_version_or_approval():
    async def run():
        repo = InMemorySubmissionRepository()
        sub = Submission(id='synthetic', content_type='text', role='creator', text='old', created_at='2026', updated_at='2026')
        await repo.create_submission(sub)
        job = sub.model_copy(update={'status': 'ai_review', 'processing_job_id': 'job-a'})
        assert await repo.begin_check(job, 1, 'draft')
        competing = sub.model_copy(update={'status': 'ai_review', 'processing_job_id': 'job-b'})
        assert not await repo.begin_check(competing, 1, 'draft')
        current = await repo.get_submission(sub.id)
        newer = current.model_copy(update={'version': 2, 'status': 'approved', 'text': 'new', 'processing_job_id': None})
        await repo.update_submission(newer)
        old_result = job.model_copy(update={'status': 'manager_review', 'processing_job_id': None})
        snapshot = VersionSnapshot(version=1, content_type='text', text='old', created_at='2026')
        assert not await repo.complete_check(old_result, 1, 'job-a', [], snapshot)
        assert not await repo.fail_check('synthetic', 1, 'job-a', 'old failure')
        current = await repo.get_submission('synthetic')
        assert (current.version, current.status, current.text) == (2, 'approved', 'new')
        assert await repo.get_version_snapshot('synthetic', 1) is None
    asyncio.run(run())


def test_simultaneous_revision_and_check_have_only_one_winner():
    from concurrent.futures import ThreadPoolExecutor
    from app.repository import ConcurrentSubmissionChange

    repo = InMemorySubmissionRepository()
    original = Submission(id='race', content_type='text', role='creator', text='old', created_at='2026', updated_at='2026')
    asyncio.run(repo.create_submission(original))
    barrier = threading.Barrier(2)

    def mutate(check):
        sub = asyncio.run(repo.get_submission('race'))
        barrier.wait(timeout=3)
        if check:
            sub.status = 'ai_review'
            sub.processing_job_id = 'concurrent-job'
            return asyncio.run(repo.begin_check(sub, 1, 'draft'))
        sub.text = 'new'
        try:
            asyncio.run(repo.update_submission(sub))
            return True
        except ConcurrentSubmissionChange:
            return False

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(mutate, check) for check in (True, False)]
        assert sum(f.result() for f in futures) == 1


def test_simultaneous_retries_only_one_claim_succeeds():
    from concurrent.futures import ThreadPoolExecutor

    repo = InMemorySubmissionRepository()
    asyncio.run(repo.create_submission(Submission(id='retry', content_type='text', role='creator', created_at='2026', updated_at='2026')))
    barrier = threading.Barrier(2)

    def start(job_id):
        sub = asyncio.run(repo.get_submission('retry'))
        sub.status = 'ai_review'
        sub.processing_job_id = job_id
        barrier.wait(timeout=3)
        return asyncio.run(repo.begin_check(sub, 1, 'draft'))

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(start, job) for job in ('a', 'b')]
        assert sum(f.result() for f in futures) == 1


def test_concurrent_decisions_commit_only_one_transition():
    from concurrent.futures import ThreadPoolExecutor

    barrier = threading.Barrier(2)

    class RacingRepository(InMemorySubmissionRepository):
        async def get_submission(self, submission_id):
            sub = await super().get_submission(submission_id)
            if sub and sub.status == 'manager_review':
                barrier.wait(timeout=5)
            return sub

    repo = RacingRepository()
    asyncio.run(repo.create_submission(Submission(
        id='decision-race', content_type='text', role='creator', status='manager_review',
        processing_stage='completed', text='Synthetic text', created_at='2026', updated_at='2026',
    )))
    app = create_app(repo=repo, settings=Settings(require_auth=False, demo_mode=False))

    def decide(action):
        with TestClient(app) as client:
            return client.post('/submissions/decision-race/decision', json={
                'role': 'manager', 'decision': action, 'comment': 'Synthetic decision',
            }).status_code

    with ThreadPoolExecutor(2) as pool:
        futures = [pool.submit(decide, action) for action in ('approve', 'request_changes')]
        assert sorted(f.result() for f in futures) == [200, 409]
    assert len(asyncio.run(repo.get_decisions('decision-race'))) == 1
