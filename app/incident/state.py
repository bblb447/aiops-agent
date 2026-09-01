class InvalidTransitionError(Exception):
    pass

from app.incident.model import IncidentStatus as S

_ALLOWED: dict[S, set[S]] = {
    S.NEW: {S.TRIAGING},
    S.TRIAGING: {S.INVESTIGATING},
    S.INVESTIGATING: {S.ROOT_CAUSE_FOUND, S.INSUFFICIENT_EVIDENCE, S.ESCALATED},
    S.ROOT_CAUSE_FOUND: {S.REMEDIATION, S.RESOLVED},
    S.REMEDIATION: {S.WAITING_APPROVAL, S.EXECUTING},
    S.WAITING_APPROVAL: {S.EXECUTING, S.ESCALATED},
    S.EXECUTING: {S.VERIFYING, S.ESCALATED},
    S.VERIFYING: {S.RESOLVED, S.ESCALATED},
    S.INSUFFICIENT_EVIDENCE: {S.ESCALATED},
    S.ESCALATED: set(),
    S.RESOLVED: set(),
}

def transition(state: S, target: S) -> S:
    if state not in _ALLOWED:
        raise InvalidTransitionError(f"非法状态转移: {state} -> {target}")
    if target not in _ALLOWED[state]:
        raise InvalidTransitionError(f"非法状态转移: {state} -> {target}")
    return target
