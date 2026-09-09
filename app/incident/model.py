from datetime import datetime, timezone
from enum import Enum
from typing import Literal
from pydantic import BaseModel, Field, ValidationError, field_validator, model_validator

from app.incident.codes import LOW_CONFIDENCE, MISSING_EVIDENCE

class IncidentSeverity(str, Enum):
    CRITICAL = "critical"
    MAJOR = "major"
    MINOR = "minor"


class IncidentStatus(str, Enum):
    NEW = "NEW"
    TRIAGING = "TRIAGING"
    INVESTIGATING = "INVESTIGATING"
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    INSUFFICIENT_EVIDENCE = "INSUFFICIENT_EVIDENCE"
    REMEDIATION = "REMEDIATION"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    EXECUTING = "EXECUTING"
    VERIFYING = "VERIFYING"
    RESOLVED = "RESOLVED"
    ESCALATED = "ESCALATED"
    REOPEN = "REOPEN"


class InvestigationVerdict(str, Enum):
    """调查对世界的判断（与 Incident.status 生命周期/处置正交，spec §4.1）。

    ESCALATED 是执行链处置，不是世界结论，因此不在此枚举内。
    """
    ROOT_CAUSE_FOUND = "ROOT_CAUSE_FOUND"
    NO_ANOMALY = "NO_ANOMALY"
    INCONCLUSIVE = "INCONCLUSIVE"

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()

class EvidenceItem(BaseModel):
    source: str
    fact: str

class RCAResult(BaseModel):
    """结构化调查结论记录（V1.7：概念从"根因分析"泛化为"调查结论"，代码名保留兼容）。

    verdict 是模型声明的世界判断；本模型只校验 verdict 与结构字段的一致性，
    不校验 verdict 与 evidence 事实语义的一致性（spec §4.3/§4.4 领域不变量）。
    """
    verdict: InvestigationVerdict | None = None          # NO_ANOMALY / INCONCLUSIVE 必须显式
    root_cause: str | None = None                        # 技术类型 str|None；业务必填由 verdict 条件约束
    confidence: float | None = Field(default=None, ge=0.0, le=1.0)
    evidence: list[EvidenceItem] = Field(min_length=1)
    hypotheses: list[str] = Field(default_factory=list)
    recommendations: list[str] = Field(default_factory=list)
    summary: str | None = None

    @field_validator("confidence", mode="before")
    @classmethod
    def _confidence_no_coercion(cls, v):
        # 与 submit 工具路径一致：只接受数值，字符串/布尔拒绝（P1 两通道校验统一）。
        # mode="before" 才能看到强转前的原始输入（否则 pydantic 已把 "0.8" 先转成 float）。
        # None 由 verdict 约束后续判断（INCONCLUSIVE 可省略，其余 verdict 必填）。
        if v is None:
            return v
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            raise ValueError("confidence 必须是数字，不接受字符串/布尔")
        return float(v)

    @model_validator(mode="after")
    def _verdict_consistency(self):
        # 归一：root_cause 空白串视同 None。
        rc = (self.root_cause or "").strip() or None
        self.root_cause = rc
        # 证据内容不得空（source/fact 去空后仍为空 → 拒绝，两通道统一）。
        for i, e in enumerate(self.evidence):
            if not (e.source or "").strip() or not (e.fact or "").strip():
                raise ValueError(f"[MISSING_EVIDENCE] evidence[{i}] 的 source 和 fact 不能为空")
        v = self.verdict
        if v is None:
            if rc is not None:
                # legacy 兼容：无 verdict + root_cause 非空 → ROOT_CAUSE_FOUND（历史成功提交皆如此）。
                self.verdict = InvestigationVerdict.ROOT_CAUSE_FOUND
                v = self.verdict
            else:
                # 结构上无法区分 NO_ANOMALY / INCONCLUSIVE → 拒绝。
                raise ValueError("[MISSING_EVIDENCE] verdict 缺失且 root_cause 为空，无法区分 NO_ANOMALY / INCONCLUSIVE")
        if v is InvestigationVerdict.ROOT_CAUSE_FOUND:
            if rc is None:
                raise ValueError("[MISSING_EVIDENCE] verdict=ROOT_CAUSE_FOUND 需要非空 root_cause")
            if self.confidence is None:
                raise ValueError("[LOW_CONFIDENCE] verdict=ROOT_CAUSE_FOUND 需要 confidence")
        elif v is InvestigationVerdict.NO_ANOMALY:
            if rc is not None:
                raise ValueError("[MISSING_EVIDENCE] verdict=NO_ANOMALY 时 root_cause 必须为空")
            if self.confidence is None:
                raise ValueError("[LOW_CONFIDENCE] verdict=NO_ANOMALY 需要 confidence")
        else:  # INCONCLUSIVE
            if rc is not None:
                raise ValueError("[MISSING_EVIDENCE] verdict=INCONCLUSIVE 时 root_cause 必须为空")
        return self

class Incident(BaseModel):
    incident_id: str
    title: str
    service: str
    severity: IncidentSeverity = IncidentSeverity.MAJOR
    status: IncidentStatus = IncidentStatus.NEW
    verdict: InvestigationVerdict | None = None
    start_time: str = Field(default_factory=_now)
    affected_assets: list[str] = Field(default_factory=list)
    alert_id: str | None = None
    source: str | None = None
    target: str | None = None
    labels: dict[str, str] = Field(default_factory=dict)
    annotations: dict[str, str] = Field(default_factory=dict)
    observed_value: float | None = None
    threshold: float | None = None
    symptoms: list[str] = Field(default_factory=list)
    hypotheses: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    root_cause: str | None = None
    rca: RCAResult | None = None
    rca_source: Literal["tool", "final_answer"] | None = None
    failure_code: str | None = None
    remediation: list[str] = Field(default_factory=list)
    verification: str | None = None
    timeline: list[dict] = Field(default_factory=list)


def rca_validation_code(exc: ValidationError) -> str:
    """把 RCAResult 构造的 ValidationError 映射为 failure_code（SubmitRCATool / final_parse 两通道共用）。

    交叉字段错误发生在 model_validator 层（无字段级 loc），按消息标签判断；
    字段级 confidence 违例（loc 含 confidence）恒为 LOW_CONFIDENCE。
    """
    for err in exc.errors():
        loc = err.get("loc", ())
        if "confidence" in loc:
            return LOW_CONFIDENCE
        if "[LOW_CONFIDENCE]" in err.get("msg", ""):
            return LOW_CONFIDENCE
    return MISSING_EVIDENCE
