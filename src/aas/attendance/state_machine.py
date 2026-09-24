# -*- coding: utf-8 -*-
"""
state_machine.py — Attendance session state machine for Single Shot AAS v2.5.

Implements the persistent state transitions defined in §13 of the technical paper:
    SESSION_CREATED → IMAGE_RECEIVED → QUALITY_CHECK → RECOGNITION →
    HUMAN_REVIEW → FINALIZED → LOCAL_COMMITTED → SYNC_PENDING → SYNCHRONIZED

Illegal state transitions are rejected with AttendanceStateError.
"""

from __future__ import annotations

from enum import Enum, auto
from typing import Set


class SessionState(str, Enum):
    """All valid states for an attendance session lifecycle."""
    # Happy path
    SESSION_CREATED   = "SESSION_CREATED"
    IMAGE_RECEIVED    = "IMAGE_RECEIVED"
    QUALITY_CHECK     = "QUALITY_CHECK"
    RECOGNITION       = "RECOGNITION"
    HUMAN_REVIEW      = "HUMAN_REVIEW"
    FINALIZED         = "FINALIZED"
    LOCAL_COMMITTED   = "LOCAL_COMMITTED"
    SYNC_PENDING      = "SYNC_PENDING"
    SYNCHRONIZED      = "SYNCHRONIZED"

    # Failure / recovery
    FAILED            = "FAILED"
    CANCELLED         = "CANCELLED"
    SYNC_FAILED       = "SYNC_FAILED"
    RETRY_WAIT        = "RETRY_WAIT"
    INTERRUPTED       = "INTERRUPTED"


# Legal transitions: state → set of states that can follow it
_TRANSITIONS: dict[SessionState, Set[SessionState]] = {
    SessionState.SESSION_CREATED: {
        SessionState.IMAGE_RECEIVED,
        SessionState.CANCELLED,
        SessionState.FAILED,
    },
    SessionState.IMAGE_RECEIVED: {
        SessionState.QUALITY_CHECK,
        SessionState.FAILED,
        SessionState.CANCELLED,
    },
    SessionState.QUALITY_CHECK: {
        SessionState.RECOGNITION,
        SessionState.FAILED,          # quality gate rejected
        SessionState.CANCELLED,
    },
    SessionState.RECOGNITION: {
        SessionState.HUMAN_REVIEW,
        SessionState.FAILED,
        SessionState.INTERRUPTED,    # recognition crash / job failure
        SessionState.CANCELLED,
    },
    SessionState.HUMAN_REVIEW: {
        SessionState.FINALIZED,
        SessionState.CANCELLED,
        SessionState.FAILED,
    },
    SessionState.FINALIZED: {
        SessionState.LOCAL_COMMITTED,
        SessionState.FAILED,          # transaction rollback
    },
    SessionState.LOCAL_COMMITTED: {
        SessionState.SYNC_PENDING,
    },
    SessionState.SYNC_PENDING: {
        SessionState.SYNCHRONIZED,
        SessionState.SYNC_FAILED,
        SessionState.RETRY_WAIT,
    },
    SessionState.RETRY_WAIT: {
        SessionState.SYNC_PENDING,    # back to attempting sync
        SessionState.SYNC_FAILED,
    },
    SessionState.SYNCHRONIZED: set(),   # terminal success
    SessionState.FAILED:       set(),   # terminal failure
    SessionState.CANCELLED:    set(),   # terminal cancelled
    SessionState.SYNC_FAILED:  set(),   # terminal sync failure
    SessionState.INTERRUPTED: {
        SessionState.RECOGNITION,       # permit retry
        SessionState.FAILED,
    },
}

# States that are considered terminal (no further transitions allowed by default)
TERMINAL_STATES: frozenset[SessionState] = frozenset({
    SessionState.SYNCHRONIZED,
    SessionState.FAILED,
    SessionState.CANCELLED,
    SessionState.SYNC_FAILED,
})

# States in which the local attendance record already exists
LOCALLY_COMMITTED_STATES: frozenset[SessionState] = frozenset({
    SessionState.LOCAL_COMMITTED,
    SessionState.SYNC_PENDING,
    SessionState.RETRY_WAIT,
    SessionState.SYNCHRONIZED,
    SessionState.SYNC_FAILED,
})


class AttendanceStateError(Exception):
    """Raised when an illegal state transition is attempted."""

    def __init__(self, from_state: SessionState, to_state: SessionState) -> None:
        self.from_state = from_state
        self.to_state = to_state
        super().__init__(
            f"Illegal attendance session transition: {from_state.value} → {to_state.value}"
        )


def validate_transition(from_state: SessionState, to_state: SessionState) -> None:
    """Assert that *from_state* → *to_state* is a legal transition.

    Args:
        from_state: Current session state.
        to_state:   Desired next state.

    Raises:
        AttendanceStateError: If the transition is illegal.
    """
    allowed = _TRANSITIONS.get(from_state, set())
    if to_state not in allowed:
        raise AttendanceStateError(from_state, to_state)


def is_terminal(state: SessionState) -> bool:
    """Return True if *state* admits no further transitions."""
    return state in TERMINAL_STATES


def is_locally_committed(state: SessionState) -> bool:
    """Return True if the session has successfully committed to local SQLite."""
    return state in LOCALLY_COMMITTED_STATES


def allowed_next_states(state: SessionState) -> Set[SessionState]:
    """Return the set of states reachable from *state*."""
    return _TRANSITIONS.get(state, set())
