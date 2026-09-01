import pytest

from app.incident.state import _ALLOWED, transition, InvalidTransitionError
from app.incident.model import IncidentStatus as S


@pytest.mark.parametrize(
    ("src", "tgt"),
    [(src, tgt) for src in S for tgt in S],
)
def test_transition_full_table(src, tgt):
    allowed = src in _ALLOWED and tgt in _ALLOWED[src]
    if allowed:
        assert transition(src, tgt) == tgt
    else:
        with pytest.raises(InvalidTransitionError):
            transition(src, tgt)


def test_transition_non_member_state_raises():
    with pytest.raises(InvalidTransitionError):
        transition("NOT_A_STATE", S.NEW)


def test_transition_non_member_target_raises():
    with pytest.raises(InvalidTransitionError):
        transition(S.NEW, "NOT_A_STATE")
