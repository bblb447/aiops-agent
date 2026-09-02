"""绑定本次 Incident 的 RCA 提交工具（V1.5，docs/design.md 第 41 章）。

SubmitRCATool 在 investigate() 内按 (svc, incident_id) 动态实例化，不属于全局只读工具
工厂 build_tools()。职责：只做校验 + 存 holder，**不写 Incident**；最终状态由
investigate() 作为单一事务边界统一落库。

关键规则：
- holder.rca_result 只被成功提交更新；失败提交永不覆盖已有成功结果。
- submit_rca_result 是业务结果提交；final_answer 仅是结束信号。
"""
from app.incident.codes import LOW_CONFIDENCE, MISSING_EVIDENCE
from app.incident.model import EvidenceItem, RCAResult
from app.incident.service import IncidentService
from app.tools.base import ToolResult


class SubmitRCATool:
    def __init__(self, svc: IncidentService, incident_id: str) -> None:
        self._svc = svc
        self._incident_id = incident_id
        self.submit_attempted = False
        self.rca_result: RCAResult | None = None
        self.validation_error: str | None = None
        self.last_validation_code: str | None = None

    def submit_rca_result(self, root_cause=None, confidence=None, evidence=None,
                          hypotheses=None, recommendations=None, summary=None) -> ToolResult:
        self.submit_attempted = True
        root_cause = str(root_cause or "").strip()
        evidence = evidence or []
        hypotheses = hypotheses or []
        recommendations = recommendations or []

        errors = []
        code = None
        if confidence is None or isinstance(confidence, bool) or not isinstance(confidence, (int, float)):
            errors.append("confidence 必须提供且为 0~1 的数字")
            code = LOW_CONFIDENCE
        elif not (0.0 <= confidence <= 1.0):
            errors.append(f"confidence 必须在 0~1 之间，收到 {confidence}")
            code = LOW_CONFIDENCE

        if not root_cause:
            errors.append("root_cause 不能为空")
        if not evidence:
            errors.append("evidence 至少需要 1 条")
        else:
            for i, item in enumerate(evidence):
                src = (item or {}).get("source")
                fact = (item or {}).get("fact")
                if not src or not str(src).strip() or not fact or not str(fact).strip():
                    errors.append(f"evidence[{i}] 的 source 和 fact 不能为空")

        if errors:
            self.validation_error = "; ".join(errors)
            self.last_validation_code = code or MISSING_EVIDENCE
            return ToolResult(success=False, tool="submit_rca_result", error=self.validation_error)

        result = RCAResult(
            root_cause=root_cause,
            confidence=float(confidence),
            evidence=[
                EvidenceItem(source=str(e["source"]).strip(), fact=str(e["fact"]).strip())
                for e in evidence
            ],
            hypotheses=[str(h) for h in hypotheses],
            recommendations=[str(r) for r in recommendations],
            summary=summary,
        )
        self.rca_result = result
        self.validation_error = None
        self.last_validation_code = None
        return ToolResult(success=True, tool="submit_rca_result", data=result.model_dump())
