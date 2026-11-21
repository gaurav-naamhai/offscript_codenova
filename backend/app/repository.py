"""Repository pattern for submissions, version snapshots, flags, decisions, comments, audit events, and guideline rectifications."""

from abc import ABC, abstractmethod
import threading
from typing import Dict, List, Optional

from app.ai.guideline_rectification import GuidelineRectification
from app.models import AuditEvent, Comment, Decision, Flag, Submission, VersionSnapshot

MAX_SUBMISSIONS = 40


class ConcurrentSubmissionChange(Exception):
    """A mutation attempted to replace a newer stored submission."""


class SubmissionRepository(ABC):
    """Abstract storage interface for brand compliance assets."""

    async def begin_check(self, submission: Submission, expected_version: int, expected_status: str) -> bool:
        raise NotImplementedError("Atomic check start is required")

    async def complete_check(self, submission: Submission, expected_version: int, job_id: str, flags: List[Flag], snapshot: VersionSnapshot) -> bool:
        raise NotImplementedError("Atomic check completion is required")

    async def fail_check(self, submission_id: str, version: int, job_id: str, error: str) -> bool:
        raise NotImplementedError("Atomic check failure is required")

    def update_check_stage(self, submission_id: str, version: int, job_id: str, stage: str) -> None:
        raise NotImplementedError("Conditional stage update is required")

    @abstractmethod
    async def create_submission(self, submission: Submission) -> Submission: ...
    @abstractmethod
    async def get_submission(self, submission_id: str) -> Optional[Submission]: ...
    @abstractmethod
    async def list_submissions(
        self, status: Optional[str] = None, org_id: Optional[str] = None
    ) -> List[Submission]: ...
    @abstractmethod
    async def update_submission(self, submission: Submission) -> Submission: ...
    @abstractmethod
    async def set_flags(self, submission_id: str, flags: List[Flag], version: Optional[int] = None) -> List[Flag]: ...
    @abstractmethod
    async def get_flags(self, submission_id: str, version: Optional[int] = None) -> List[Flag]: ...
    @abstractmethod
    async def get_all_flags(
        self, submission_id: Optional[str] = None, org_id: Optional[str] = None
    ) -> List[Flag]: ...
    @abstractmethod
    async def update_flag(self, submission_id: str, flag: Flag) -> Flag: ...
    @abstractmethod
    async def get_versions(self, submission_id: str) -> List[int]: ...
    @abstractmethod
    async def save_version_snapshot(self, submission_id: str, snapshot: VersionSnapshot) -> VersionSnapshot: ...
    @abstractmethod
    async def get_version_snapshot(self, submission_id: str, version: int) -> Optional[VersionSnapshot]: ...
    @abstractmethod
    async def list_version_snapshots(self, submission_id: str) -> List[VersionSnapshot]: ...
    @abstractmethod
    async def add_decision(self, decision: Decision) -> Decision: ...
    @abstractmethod
    async def get_decisions(self, submission_id: str) -> List[Decision]: ...
    @abstractmethod
    async def add_comment(self, comment: Comment) -> Comment: ...
    @abstractmethod
    async def get_comments(self, submission_id: str) -> List[Comment]: ...
    @abstractmethod
    async def add_audit_event(self, submission_id: str, event: AuditEvent) -> AuditEvent: ...
    @abstractmethod
    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]: ...

    # Guideline Rectification persistence (optional default in-memory / concrete override)
    async def save_rectifications(self, org_id: str, items: List[GuidelineRectification]) -> List[GuidelineRectification]:
        return items

    async def list_rectifications(self, org_id: str) -> List[GuidelineRectification]:
        return []

    async def get_rectification(self, org_id: str, rect_id: str) -> Optional[GuidelineRectification]:
        return None

    async def update_rectification(self, item: GuidelineRectification) -> GuidelineRectification:
        return item


class InMemorySubmissionRepository(SubmissionRepository):
    """Thread-safe in-memory repository implementation with max submission capacity."""

    def __init__(self, max_submissions: int = MAX_SUBMISSIONS):
        self._lock = threading.Lock()
        self._max = max_submissions
        self._submissions: Dict[str, Submission] = {}
        self._snapshots: Dict[str, Dict[int, VersionSnapshot]] = {}
        self._flags: Dict[str, Dict[int, List[Flag]]] = {}
        self._decisions: Dict[str, List[Decision]] = {}
        self._comments: Dict[str, List[Comment]] = {}
        self._audit_events: Dict[str, List[AuditEvent]] = {}
        self._rectifications: Dict[str, List[GuidelineRectification]] = {}

    async def create_submission(self, submission: Submission) -> Submission:
        with self._lock:
            while len(self._submissions) >= self._max:
                oldest_id = min(self._submissions, key=lambda k: self._submissions[k].created_at)
                for d in (
                    self._submissions,
                    self._snapshots,
                    self._flags,
                    self._decisions,
                    self._comments,
                    self._audit_events,
                ):
                    d.pop(oldest_id, None)

            self._submissions[submission.id] = submission.model_copy(deep=True)
            self._snapshots[submission.id] = {}
            self._flags[submission.id] = {submission.version: []}
            self._decisions[submission.id] = []
            self._comments[submission.id] = []
            self._audit_events[submission.id] = []
            return submission

    async def get_submission(self, submission_id: str) -> Optional[Submission]:
        with self._lock:
            item = self._submissions.get(submission_id)
            return item.model_copy(deep=True) if item else None

    async def list_submissions(
        self, status: Optional[str] = None, org_id: Optional[str] = None
    ) -> List[Submission]:
        with self._lock:
            items = list(reversed(list(self._submissions.values())))
            if org_id:
                norm_org = org_id.strip().lower()
                items = [s for s in items if (s.org_id or "inkloom").lower() == norm_org]
            if status:
                items = [s for s in items if s.status == status]
            return [s.model_copy(deep=True) for s in sorted(items, key=lambda s: s.created_at, reverse=True)]

    async def update_submission(self, submission: Submission) -> Submission:
        with self._lock:
            current = self._submissions.get(submission.id)
            if not current or current.storage_revision != submission.storage_revision:
                raise ConcurrentSubmissionChange()
            submission.storage_revision += 1
            self._submissions[submission.id] = submission.model_copy(deep=True)
            if submission.id in self._flags and submission.version not in self._flags[submission.id]:
                self._flags[submission.id][submission.version] = []
            return submission

    async def begin_check(self, submission: Submission, expected_version: int, expected_status: str) -> bool:
        with self._lock:
            current = self._submissions.get(submission.id)
            if not current or current.version != expected_version or current.status != expected_status or current.processing_job_id or current.storage_revision != submission.storage_revision:
                return False
            submission.storage_revision += 1
            self._submissions[submission.id] = submission.model_copy(deep=True)
            return True

    async def complete_check(self, submission: Submission, expected_version: int, job_id: str, flags: List[Flag], snapshot: VersionSnapshot) -> bool:
        with self._lock:
            current = self._submissions.get(submission.id)
            if not current or current.version != expected_version or current.status != 'ai_review' or current.processing_job_id != job_id:
                return False
            submission.storage_revision = current.storage_revision + 1
            self._submissions[submission.id] = submission.model_copy(deep=True)
            self._flags.setdefault(submission.id, {})[expected_version] = list(flags)
            self._snapshots.setdefault(submission.id, {})[expected_version] = snapshot
            return True

    async def fail_check(self, submission_id: str, version: int, job_id: str, error: str) -> bool:
        with self._lock:
            current = self._submissions.get(submission_id)
            if not current or current.version != version or current.status != 'ai_review' or current.processing_job_id != job_id:
                return False
            self._submissions[submission_id] = current.model_copy(update={'status': 'draft', 'processing_stage': 'failed', 'processing_error': error, 'processing_job_id': None, 'storage_revision': current.storage_revision + 1})
            return True

    def update_check_stage(self, submission_id: str, version: int, job_id: str, stage: str) -> None:
        with self._lock:
            current = self._submissions.get(submission_id)
            if current and current.version == version and current.processing_job_id == job_id and current.status == 'ai_review':
                current.processing_stage = stage

    async def set_flags(
        self, submission_id: str, flags: List[Flag], version: Optional[int] = None
    ) -> List[Flag]:
        with self._lock:
            if submission_id not in self._flags:
                self._flags[submission_id] = {}
            v = version if version is not None else (
                flags[0].version if flags else (
                    self._submissions[submission_id].version
                    if submission_id in self._submissions else 1
                )
            )
            self._flags[submission_id][v] = list(flags)
            return list(flags)

    async def get_flags(self, submission_id: str, version: Optional[int] = None) -> List[Flag]:
        with self._lock:
            sub_flags = self._flags.get(submission_id, {})
            if version is not None:
                return list(sub_flags.get(version, []))
            sub = self._submissions.get(submission_id)
            if sub and sub.version in sub_flags:
                return list(sub_flags[sub.version])
            return list(sub_flags[max(sub_flags.keys())]) if sub_flags else []

    async def get_all_flags(
        self, submission_id: Optional[str] = None, org_id: Optional[str] = None
    ) -> List[Flag]:
        with self._lock:
            if submission_id:
                sub_flags = self._flags.get(submission_id, {})
                return [f for v in sub_flags.values() for f in v]
            if org_id:
                norm_org = org_id.strip().lower()
                allowed_ids = {
                    sid
                    for sid, sub in self._submissions.items()
                    if (sub.org_id or "inkloom").lower() == norm_org
                }
                return [
                    f
                    for sid, sf in self._flags.items()
                    if sid in allowed_ids
                    for v in sf.values()
                    for f in v
                ]
            return [f for sf in self._flags.values() for v in sf.values() for f in v]

    async def update_flag(self, submission_id: str, flag: Flag) -> Flag:
        with self._lock:
            for flags_list in self._flags.get(submission_id, {}).values():
                for idx, existing in enumerate(flags_list):
                    if existing.id == flag.id:
                        flags_list[idx] = flag
                        return flag
            return flag

    async def get_versions(self, submission_id: str) -> List[int]:
        with self._lock:
            sub = self._submissions.get(submission_id)
            versions = set(self._flags.get(submission_id, {}).keys())
            versions.update(self._snapshots.get(submission_id, {}).keys())
            if sub:
                versions.update(range(1, sub.version + 1))
            return sorted(versions) if versions else [1]

    async def save_version_snapshot(self, submission_id: str, snapshot: VersionSnapshot) -> VersionSnapshot:
        with self._lock:
            current = self._submissions.get(submission_id)
            if current and snapshot.version == current.version and snapshot.status != current.status:
                raise ConcurrentSubmissionChange()
            self._snapshots.setdefault(submission_id, {})[snapshot.version] = snapshot
            return snapshot

    async def get_version_snapshot(self, submission_id: str, version: int) -> Optional[VersionSnapshot]:
        with self._lock:
            return self._snapshots.get(submission_id, {}).get(version)

    async def list_version_snapshots(self, submission_id: str) -> List[VersionSnapshot]:
        with self._lock:
            snaps = self._snapshots.get(submission_id, {})
            return [snaps[k] for k in sorted(snaps.keys())]

    async def add_decision(self, decision: Decision) -> Decision:
        with self._lock:
            self._decisions.setdefault(decision.submission_id, []).append(decision)
            return decision

    async def get_decisions(self, submission_id: str) -> List[Decision]:
        with self._lock:
            return list(self._decisions.get(submission_id, []))

    async def add_comment(self, comment: Comment) -> Comment:
        with self._lock:
            self._comments.setdefault(comment.submission_id, []).append(comment)
            return comment

    async def get_comments(self, submission_id: str) -> List[Comment]:
        with self._lock:
            return list(self._comments.get(submission_id, []))

    async def add_audit_event(self, submission_id: str, event: AuditEvent) -> AuditEvent:
        with self._lock:
            self._audit_events.setdefault(submission_id, []).append(event)
            return event

    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]:
        with self._lock:
            return list(self._audit_events.get(submission_id, []))

    async def save_rectifications(self, org_id: str, items: List[GuidelineRectification]) -> List[GuidelineRectification]:
        norm_org = (org_id or "inkloom").strip().lower()
        with self._lock:
            existing = self._rectifications.get(norm_org, [])
            # Preserve previously approved/dismissed resolutions; refresh pending ones
            resolved = [r for r in existing if r.status != "pending"]
            resolved_keys = {(r.issue_type, r.chunk_id) for r in resolved}
            merged = resolved + [it for it in items if (it.issue_type, it.chunk_id) not in resolved_keys]
            self._rectifications[norm_org] = merged
            return list(merged)

    async def list_rectifications(self, org_id: str) -> List[GuidelineRectification]:
        norm_org = (org_id or "inkloom").strip().lower()
        with self._lock:
            return list(self._rectifications.get(norm_org, []))

    async def get_rectification(self, org_id: str, rect_id: str) -> Optional[GuidelineRectification]:
        norm_org = (org_id or "inkloom").strip().lower()
        with self._lock:
            return next((r for r in self._rectifications.get(norm_org, []) if r.id == rect_id), None)

    async def update_rectification(self, item: GuidelineRectification) -> GuidelineRectification:
        norm_org = (item.org_id or "inkloom").strip().lower()
        with self._lock:
            arr = self._rectifications.setdefault(norm_org, [])
            for idx, existing in enumerate(arr):
                if existing.id == item.id:
                    arr[idx] = item
                    return item
            arr.append(item)
            return item


class SupabaseRepository(SubmissionRepository):
    """Supabase storage placeholder."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("fill in after Ken shares the schema")

    async def create_submission(self, submission: Submission) -> Submission: raise NotImplementedError
    async def get_submission(self, submission_id: str) -> Optional[Submission]: raise NotImplementedError
    async def list_submissions(self, status: Optional[str] = None, org_id: Optional[str] = None) -> List[Submission]: raise NotImplementedError
    async def update_submission(self, submission: Submission) -> Submission: raise NotImplementedError
    async def set_flags(self, submission_id: str, flags: List[Flag], version: Optional[int] = None) -> List[Flag]: raise NotImplementedError
    async def get_flags(self, submission_id: str, version: Optional[int] = None) -> List[Flag]: raise NotImplementedError
    async def get_all_flags(self, submission_id: Optional[str] = None, org_id: Optional[str] = None) -> List[Flag]: raise NotImplementedError
    async def update_flag(self, submission_id: str, flag: Flag) -> Flag: raise NotImplementedError
    async def get_versions(self, submission_id: str) -> List[int]: raise NotImplementedError
    async def save_version_snapshot(self, submission_id: str, snapshot: VersionSnapshot) -> VersionSnapshot: raise NotImplementedError
    async def get_version_snapshot(self, submission_id: str, version: int) -> Optional[VersionSnapshot]: raise NotImplementedError
    async def list_version_snapshots(self, submission_id: str) -> List[VersionSnapshot]: raise NotImplementedError
    async def add_decision(self, decision: Decision) -> Decision: raise NotImplementedError
    async def get_decisions(self, submission_id: str) -> List[Decision]: raise NotImplementedError
    async def add_comment(self, comment: Comment) -> Comment: raise NotImplementedError
    async def get_comments(self, submission_id: str) -> List[Comment]: raise NotImplementedError
    async def add_audit_event(self, submission_id: str, event: AuditEvent) -> AuditEvent: raise NotImplementedError
    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]: raise NotImplementedError


def get_repository(repo_backend: str = "memory") -> SubmissionRepository:
    """Instantiate storage repository based on configuration."""
    if repo_backend == "supabase":
        return SupabaseRepository()
    return InMemorySubmissionRepository()
