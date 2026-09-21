"""绑定本次 Incident 的 RCA 提交工具（V1.5/V1.7，docs/design.md §41 + §47）。

SubmitRCATool 在 investigate() 内按 (svc, incident_id) 动态实例化，不属于全局只读工具
工厂 build_tools()。职责：只做校验 + 存 holder，**不写 Incident**；最终状态由
investigate() 作为单一事务边界统一落库。

V1.7：校验收敛到 RCAResult 的 model_validator（verdict-aware）。submit 工具与 final
<rca_result> 两通道共享同一 schema，杜绝"Tool 一套、Final 一套"。本工具不再手写逐字段
规则，只负责把失败 ValidationError 转成可读消息与 failure_code（rca_validation_code）。

关键规则：
- holder.rca_result 只被成功提交更新；失败提交永不覆盖已有成功结果。
- submit_rca_result 是业务结果提交；final_answer 仅是结束信号。
"""
from pydantic import ValidationError

from app.incident.model import RCAResult, rca_validation_code
from app.incident.service import IncidentService
from app.tools.base import ToolResult


class SubmitRCATool:
    exposed_methods = ["submit_rca_result"]

    def __init__(self, svc: IncidentService, incident_id: str) -> None:
        # 仅语义绑定（本工具属于哪个 Incident 的 Run）；本工具不写 Incident，
        # 持久化统一由 investigate() 在事务边界完成。
        self._svc = svc
        self._incident_id = incident_id
        self.submit_attempted = False
        self.rca_result: RCAResult | None = None
        self.validation_error: str | None = None
        self.last_validation_code: str | None = None

    def submit_rca_result(self, root_cause: str = "", confidence: float = None,
                          evidence: list = None, hypotheses: list = None,
                          recommendations: list = None, summary: str = None,
                          verdict: str = None) -> ToolResult:
        """提交本 Incident 的最终调查结论（首选提交通道），成功即代表结论已落锁。

        结论三选一（verdict，V1.7）：
          - ROOT_CAUSE_FOUND：找到根因，root_cause 必须非空；
          - NO_ANOMALY：告警被证伪 / 未发现对应异常，root_cause 必须省略
            （禁止填入 "metric_alert_false_positive" 之类伪根因），evidence 说明为何认为无异常；
          - INCONCLUSIVE：已调查但证据不足以定论，root_cause 必须省略，仍须保留至少 1 条 evidence；
            这是合法结论，不是失败。
        当证据足以判断根因时，优先调用本工具结束调查；本工具是首选，不要为了省事
        直接跳过。若模型无法调用本工具，才允许改在 final_answer 中输出 <rca_result>
        标签包裹的严格 JSON 作为兜底。

        参数:
          - verdict (string, 可选): 上述三值之一；省略且 root_cause 非空时按 ROOT_CAUSE_FOUND 兼容。
          - root_cause (string, 可选): 根因；仅 ROOT_CAUSE_FOUND 需要非空。
          - confidence (number, 可选): ROOT_CAUSE_FOUND/NO_ANOMALY 必填 0~1；INCONCLUSIVE 可选。
          - evidence (array): 至少 1 条；每条为对象 {"source": "数据源", "fact": "证据事实"}，
            source/fact 不能为空。source 表示「这条证据由哪个数据源提供」（不是哪次查询、
            不是工具名），取值必须是工具描述与本提示中列出的数据源之一。
          - hypotheses (array, 可选): 候选假设列表
          - recommendations (array, 可选): 处置建议列表
          - summary (string, 可选): 一句话总结

        校验失败会返回错误信息，你可修正后重试；成功后 Incident 终态由 verdict 决定
        （ROOT_CAUSE_FOUND / NO_ANOMALY→RESOLVED / INCONCLUSIVE→INSUFFICIENT_EVIDENCE）。
        """
        self.submit_attempted = True
        rc = str(root_cause or "").strip() or None
        v = (verdict or "").strip().upper() or None
        payload = {
            "verdict": v,
            "root_cause": rc,
            "confidence": confidence,
            "evidence": [dict(e) if isinstance(e, dict) else e for e in (evidence or [])],
            "hypotheses": [str(h) for h in (hypotheses or [])],
            "recommendations": [str(r) for r in (recommendations or [])],
            "summary": summary,
        }
        try:
            result = RCAResult(**payload)
        except ValidationError as exc:
            self.validation_error = self._fmt_error(exc)
            self.last_validation_code = rca_validation_code(exc)
            return ToolResult(success=False, tool="submit_rca_result", error=self.validation_error)
        self.rca_result = result
        self.validation_error = None
        self.last_validation_code = None
        return ToolResult(success=True, tool="submit_rca_result", data=result.model_dump())

    @staticmethod
    def _fmt_error(exc: ValidationError) -> str:
        parts = []
        for err in exc.errors():
            loc = ".".join(str(x) for x in err.get("loc", ()))
            msg = err.get("msg", "").replace("Value error, ", "").strip()
            parts.append(f"{loc}: {msg}" if loc else msg)
        return "RCA 校验失败: " + "; ".join(parts)
