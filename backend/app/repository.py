"""Repository pattern for submissions, flags, decisions, comments, and audit events."""

import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Optional

from app.models import AuditEvent, Comment, Decision, Flag, Submission


class SubmissionRepository(ABC):
    """Abstract storage interface for brand compliance assets."""

    @abstractmethod
    async def create_submission(self, submission: Submission) -> Submission:
        pass

    @abstractmethod
    async def get_submission(self, submission_id: str) -> Optional[Submission]:
        pass

    @abstractmethod
    async def list_submissions(
        self, status: Optional[str] = None
    ) -> List[Submission]:
        pass

    @abstractmethod
    async def update_submission(self, submission: Submission) -> Submission:
        pass

    @abstractmethod
    async def set_flags(
        self,
        submission_id: str,
        flags: List[Flag],
        version: Optional[int] = None,
    ) -> List[Flag]:
        pass

    @abstractmethod
    async def get_flags(
        self, submission_id: str, version: Optional[int] = None
    ) -> List[Flag]:
        pass

    @abstractmethod
    async def get_all_flags(
        self, submission_id: Optional[str] = None
    ) -> List[Flag]:
        pass

    @abstractmethod
    async def update_flag(self, submission_id: str, flag: Flag) -> Flag:
        pass

    @abstractmethod
    async def get_versions(self, submission_id: str) -> List[int]:
        pass

    @abstractmethod
    async def add_decision(self, decision: Decision) -> Decision:
        pass

    @abstractmethod
    async def get_decisions(self, submission_id: str) -> List[Decision]:
        pass

    @abstractmethod
    async def add_comment(self, comment: Comment) -> Comment:
        pass

    @abstractmethod
    async def get_comments(self, submission_id: str) -> List[Comment]:
        pass

    @abstractmethod
    async def add_audit_event(
        self, submission_id: str, event: AuditEvent
    ) -> AuditEvent:
        pass

    @abstractmethod
    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]:
        pass


class InMemorySubmissionRepository(SubmissionRepository):
    """Thread-safe in-memory repository implementation storing flags per version."""

    def __init__(self):
        self._lock = threading.Lock()
        self._submissions: Dict[str, Submission] = {}
        # Stores flags indexed by submission_id -> version -> List[Flag]
        self._flags: Dict[str, Dict[int, List[Flag]]] = {}
        self._decisions: Dict[str, List[Decision]] = {}
        self._comments: Dict[str, List[Comment]] = {}
        self._audit_events: Dict[str, List[AuditEvent]] = {}

    async def create_submission(self, submission: Submission) -> Submission:
        with self._lock:
            self._submissions[submission.id] = submission
            self._flags[submission.id] = {submission.version: []}
            self._decisions[submission.id] = []
            self._comments[submission.id] = []
            self._audit_events[submission.id] = []
            return submission

    async def get_submission(self, submission_id: str) -> Optional[Submission]:
        with self._lock:
            return self._submissions.get(submission_id)

    async def list_submissions(
        self, status: Optional[str] = None
    ) -> List[Submission]:
        with self._lock:
            items = list(self._submissions.values())
            if status:
                items = [s for s in items if s.status == status]
            # Newest first
            return sorted(items, key=lambda s: s.created_at, reverse=True)

    async def update_submission(self, submission: Submission) -> Submission:
        with self._lock:
            self._submissions[submission.id] = submission
            if submission.id in self._flags:
                if submission.version not in self._flags[submission.id]:
                    self._flags[submission.id][submission.version] = []
            return submission

    async def set_flags(
        self,
        submission_id: str,
        flags: List[Flag],
        version: Optional[int] = None,
    ) -> List[Flag]:
        with self._lock:
            if submission_id not in self._flags:
                self._flags[submission_id] = {}

            if version is None:
                if flags and hasattr(flags[0], "version"):
                    v = flags[0].version
                else:
                    sub = self._submissions.get(submission_id)
                    v = sub.version if sub else 1
            else:
                v = version

            self._flags[submission_id][v] = list(flags)
            return list(flags)

    async def get_flags(
        self, submission_id: str, version: Optional[int] = None
    ) -> List[Flag]:
        with self._lock:
            sub_flags = self._flags.get(submission_id, {})
            if version is not None:
                return list(sub_flags.get(version, []))
            sub = self._submissions.get(submission_id)
            if sub and sub.version in sub_flags:
                return list(sub_flags.get(sub.version, []))
            if sub_flags:
                latest_v = max(sub_flags.keys())
                return list(sub_flags[latest_v])
            return []

    async def get_all_flags(
        self, submission_id: Optional[str] = None
    ) -> List[Flag]:
        with self._lock:
            if submission_id:
                sub_flags = self._flags.get(submission_id, {})
                res = []
                for v_flags in sub_flags.values():
                    res.extend(v_flags)
                return res

            all_flags = []
            for sub_flags in self._flags.values():
                for v_flags in sub_flags.values():
                    all_flags.extend(v_flags)
            return all_flags

    async def update_flag(self, submission_id: str, flag: Flag) -> Flag:
        with self._lock:
            sub_flags = self._flags.get(submission_id, {})
            # Search in flag's version or across versions
            for v, flags_list in sub_flags.items():
                for idx, existing in enumerate(flags_list):
                    if existing.id == flag.id:
                        flags_list[idx] = flag
                        return flag
            return flag

    async def get_versions(self, submission_id: str) -> List[int]:
        with self._lock:
            sub = self._submissions.get(submission_id)
            sub_flags = self._flags.get(submission_id, {})
            versions = set(sub_flags.keys())
            if sub:
                versions.add(sub.version)
                for v in range(1, sub.version + 1):
                    versions.add(v)
            return sorted(list(versions)) if versions else [1]

    async def add_decision(self, decision: Decision) -> Decision:
        with self._lock:
            if decision.submission_id not in self._decisions:
                self._decisions[decision.submission_id] = []
            self._decisions[decision.submission_id].append(decision)
            return decision

    async def get_decisions(self, submission_id: str) -> List[Decision]:
        with self._lock:
            return list(self._decisions.get(submission_id, []))

    async def add_comment(self, comment: Comment) -> Comment:
        with self._lock:
            if comment.submission_id not in self._comments:
                self._comments[comment.submission_id] = []
            self._comments[comment.submission_id].append(comment)
            return comment

    async def get_comments(self, submission_id: str) -> List[Comment]:
        with self._lock:
            return list(self._comments.get(submission_id, []))

    async def add_audit_event(
        self, submission_id: str, event: AuditEvent
    ) -> AuditEvent:
        with self._lock:
            if submission_id not in self._audit_events:
                self._audit_events[submission_id] = []
            self._audit_events[submission_id].append(event)
            return event

    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]:
        with self._lock:
            return list(self._audit_events.get(submission_id, []))


class SupabaseRepository(SubmissionRepository):
    """Supabase storage implementation."""

    def __init__(self, *args, **kwargs):
        raise NotImplementedError("fill in after Ken shares the schema")

    async def create_submission(self, submission: Submission) -> Submission:
        raise NotImplementedError

    async def get_submission(self, submission_id: str) -> Optional[Submission]:
        raise NotImplementedError

    async def list_submissions(
        self, status: Optional[str] = None
    ) -> List[Submission]:
        raise NotImplementedError

    async def update_submission(self, submission: Submission) -> Submission:
        raise NotImplementedError

    async def set_flags(
        self,
        submission_id: str,
        flags: List[Flag],
        version: Optional[int] = None,
    ) -> List[Flag]:
        raise NotImplementedError

    async def get_flags(
        self, submission_id: str, version: Optional[int] = None
    ) -> List[Flag]:
        raise NotImplementedError

    async def get_all_flags(
        self, submission_id: Optional[str] = None
    ) -> List[Flag]:
        raise NotImplementedError

    async def update_flag(self, submission_id: str, flag: Flag) -> Flag:
        raise NotImplementedError

    async def get_versions(self, submission_id: str) -> List[int]:
        raise NotImplementedError

    async def add_decision(self, decision: Decision) -> Decision:
        raise NotImplementedError

    async def get_decisions(self, submission_id: str) -> List[Decision]:
        raise NotImplementedError

    async def add_comment(self, comment: Comment) -> Comment:
        raise NotImplementedError

    async def get_comments(self, submission_id: str) -> List[Comment]:
        raise NotImplementedError

    async def add_audit_event(
        self, submission_id: str, event: AuditEvent
    ) -> AuditEvent:
        raise NotImplementedError

    async def get_audit_events(self, submission_id: str) -> List[AuditEvent]:
        raise NotImplementedError


def get_repository(repo_backend: str = "memory") -> SubmissionRepository:
    """Instantiate storage repository based on configuration."""
    if repo_backend == "supabase":
        return SupabaseRepository()
    return InMemorySubmissionRepository()
