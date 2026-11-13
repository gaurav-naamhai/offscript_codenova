"""Repository pattern for submissions, flags, decisions, comments, and audit events."""

from abc import ABC, abstractmethod
import threading
from typing import Dict, List, Optional

from app.models import AuditEvent, Comment, Decision, Flag, Submission

MAX_SUBMISSIONS = 40


class SubmissionRepository(ABC):
    """Abstract storage interface for brand compliance assets."""

    @abstractmethod
    async def create_submission(self, submission: Submission) -> Submission: ...
    @abstractmethod
    async def get_submission(self, submission_id: str) -> Optional[Submission]: ...
    @abstractmethod
    async def list_submissions(self, status: Optional[str] = None) -> List[Submission]: ...
    @abstractmethod
    async def update_submission(self, submission: Submission) -> Submission: ...
    @abstractmethod
    async def set_flags(self, submission_id: str, flags: List[Flag], version: Optional[int] = None) -> List[Flag]: ...
    @abstractmethod
    async def get_flags(self, submission_id: str, version: Optional[int] = None) -> List[Flag]: ...
    @abstractmethod
    async def get_all_flags(self, submission_id: Optional[str] = None) -> List[Flag]: ...
    @abstractmethod
    async def update_flag(self, submission_id: str, flag: Flag) -> Flag: ...
    @abstractmethod
    async def get_versions(self, submission_id: str) -> List[int]: ...
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


class InMemorySubmissionRepository(SubmissionRepository):
    """Thread-safe in-memory repository implementation with max submission capacity."""

    def __init__(self, max_submissions: int = MAX_SUBMISSIONS):
        self._lock = threading.Lock()
        self._max = max_submissions
        self._submissions: Dict[str, Submission] = {}
        self._flags: Dict[str, Dict[int, List[Flag]]] = {}
        self._decisions: Dict[str, List[Decision]] = {}
        self._comments: Dict[str, List[Comment]] = {}
        self._audit_events: Dict[str, List[AuditEvent]] = {}

    async def create_submission(self, submission: Submission) -> Submission:
        with self._lock:
            while len(self._submissions) >= self._max:
                oldest_id = min(self._submissions, key=lambda k: self._submissions[k].created_at)
                for d in (self._submissions, self._flags, self._decisions, self._comments, self._audit_events):
                    d.pop(oldest_id, None)

            self._submissions[submission.id] = submission
            self._flags[submission.id] = {submission.version: []}
            self._decisions[submission.id] = []
            self._comments[submission.id] = []
            self._audit_events[submission.id] = []
            return submission

    async def get_submission(self, submission_id: str) -> Optional[Submission]:
        with self._lock:
            return self._submissions.get(submission_id)

    async def list_submissions(self, status: Optional[str] = None) -> List[Submission]:
        with self._lock:
            items = list(reversed(list(self._submissions.values())))
            if status:
                items = [s for s in items if s.status == status]
            return sorted(items, key=lambda s: s.created_at, reverse=True)

    async def update_submission(self, submission: Submission) -> Submission:
        with self._lock:
            self._submissions[submission.id] = submission
            if submission.id in self._flags and submission.version not in self._flags[submission.id]:
                self._flags[submission.id][submission.version] = []
            return submission

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

    async def get_all_flags(self, submission_id: Optional[str] = None) -> List[Flag]:
        with self._lock:
            if submission_id:
                sub_flags = self._flags.get(submission_id, {})
                return [f for v in sub_flags.values() for f in v]
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
            if sub:
                versions.update(range(1, sub.version + 1))
            return sorted(versions) if versions else [1]

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


class SupabaseRepository(SubmissionRepository):
    """Supabase storage placeholder."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("fill in after Ken shares the schema")

    async def create_submission(self, submission: Submission) -> Submission: raise NotImplementedError
    async def get_submission(self, submission_id: str) -> Optional[Submission]: raise NotImplementedError
    async def list_submissions(self, status: Optional[str] = None) -> List[Submission]: raise NotImplementedError
    async def update_submission(self, submission: Submission) -> Submission: raise NotImplementedError
    async def set_flags(self, submission_id: str, flags: List[Flag], version: Optional[int] = None) -> List[Flag]: raise NotImplementedError
    async def get_flags(self, submission_id: str, version: Optional[int] = None) -> List[Flag]: raise NotImplementedError
    async def get_all_flags(self, submission_id: Optional[str] = None) -> List[Flag]: raise NotImplementedError
    async def update_flag(self, submission_id: str, flag: Flag) -> Flag: raise NotImplementedError
    async def get_versions(self, submission_id: str) -> List[int]: raise NotImplementedError
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
