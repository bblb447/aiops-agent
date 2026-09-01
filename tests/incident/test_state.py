import pytest
from app.incident.state import transition, InvalidTransitionError
from app.incident.model import IncidentStatus as S

def test_legal_transitions():
    assert transition(S.NEW, S.TRIAGING) == S.TRIAGING
    assert transition(S.TRIAGING, S.INVESTIGATING) == S.INVESTIGATING
    assert transition(S.INVESTIGATING, S.ROOT_CAUSE_FOUND) == S.ROOT_CAUSE_FOUND
    assert transition(S.INVESTIGATING, S.INSUFFICIENT_EVIDENCE) == S.INSUFFICIENT_EVIDENCE
    assert transition(S.INVESTIGATING, S.ESCALATED) == S.ESCALATED

def test_illegal_transition_raises():
    with pytest.raises(InvalidTransitionError):
        transition(S.NEW, S.RESOLVED)
