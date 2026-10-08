"""Job state machine (plan 6.1)."""

from __future__ import annotations

from enum import Enum


class JobState(str, Enum):
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    OUTPUT_READY = "OUTPUT_READY"
    QA_PASS = "QA_PASS"
    COMMITTED = "COMMITTED"
    RETRYABLE = "RETRYABLE"
    QUARANTINED = "QUARANTINED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    BLOCKED = "BLOCKED"


TRANSITIONS: dict[JobState, set[JobState]] = {
    JobState.PENDING: {JobState.RUNNING, JobState.BLOCKED, JobState.CANCELLED, JobState.FAILED},
    JobState.RUNNING: {JobState.OUTPUT_READY, JobState.RETRYABLE, JobState.FAILED, JobState.CANCELLED},
    JobState.OUTPUT_READY: {JobState.QA_PASS, JobState.QUARANTINED, JobState.RETRYABLE, JobState.FAILED},
    JobState.QA_PASS: {JobState.COMMITTED, JobState.QUARANTINED},
    JobState.RETRYABLE: {JobState.PENDING, JobState.FAILED},
    JobState.BLOCKED: {JobState.PENDING, JobState.FAILED, JobState.CANCELLED},
    JobState.QUARANTINED: {JobState.PENDING, JobState.FAILED},
    JobState.COMMITTED: set(),
    JobState.FAILED: set(),
    JobState.CANCELLED: set(),
}

TERMINAL = {JobState.COMMITTED, JobState.FAILED, JobState.CANCELLED}


class InvalidTransition(RuntimeError):
    pass


def can_transition(src: JobState | str, dst: JobState | str) -> bool:
    src = JobState(src)
    dst = JobState(dst)
    return dst in TRANSITIONS[src]


def require_transition(src: JobState | str, dst: JobState | str) -> None:
    if not can_transition(src, dst):
        raise InvalidTransition(f"illegal job transition {src} -> {dst}")
