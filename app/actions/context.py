from dataclasses import dataclass

CONTEXT_VERSION = "v1_decision_context@1"


def _val(x):
    return x.value if hasattr(x, "value") else x


@dataclass(frozen=True)
class ContextEvidence:
    source: str
    fact: str


@dataclass(frozen=True)
class V1DecisionContext:
    version: str
    incident_id: str
    status: str
    verdict: str | None
    confidence: float | None
    evidence: tuple[ContextEvidence, ...]
    failure_code: str | None


def build_context(inc) -> V1DecisionContext:
    rca = getattr(inc, "rca", None)
    evidence = tuple(
        ContextEvidence(source=_val(e.source), fact=e.fact)
        for e in (rca.evidence if rca else [])
    )
    return V1DecisionContext(
        version=CONTEXT_VERSION,
        incident_id=inc.incident_id,
        status=_val(inc.status),
        verdict=_val(getattr(inc, "verdict", None)),
        confidence=(rca.confidence if rca else None),
        evidence=evidence,
        failure_code=getattr(inc, "failure_code", None),
    )


def is_eligible(ctx: V1DecisionContext) -> bool:
    return ctx.verdict == "ROOT_CAUSE_FOUND"
