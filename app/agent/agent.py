"""smolagents Agent 核心：investigate 流程与 Tool 适配。

smolagents 的 ``ToolCallingAgent`` 要求 ``tools`` 是 ``smolagents.tools.Tool``
（或 ``BaseTool``）的实例（``MultiStepAgent._setup_tools`` 中有断言）。Task 4
产出的 Tool（``MonitoringTool`` 等）是普通 class 实例，直接传入会触发
``AssertionError: All elements must be instance of BaseTool (or a subclass)``。
因此这里提供一个适配层：``adapt_tools`` 把普通 Tool 实例的每个公开方法包装成
一个 smolagents ``Tool`` 子类（``_ToolAdapter``），让 ``build_agent`` 能真正
接受 Task 4 的工具。
"""
import inspect
import json
from pathlib import Path

from smolagents import ToolCallingAgent
from smolagents.tools import Tool as SmolTool

from app.agent.final_parse import extract_rca_result
from app.agent.submit_tool import SubmitRCATool
from app.config import Settings
from app.incident.codes import (
    LLM_ERROR, MAX_STEPS, MISSING_EVIDENCE, NO_SUBMISSION,
)
from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S
from app.incident.state import transition
from app.llm.base import LLMProvider
from app.llm.provider import LiteLLMProvider

# prompts/ 位于项目根目录（本文件在 app/agent/ 下，向上三级）。
PROMPT_FILE = Path(__file__).resolve().parent.parent.parent / "prompts" / "diagnose.txt"

_DEFAULT_PROMPT = (
    "你是 AIOps 诊断 Agent。请调查以下故障并给出带证据的根因结论。\n"
    "故障: {title}，服务: {service}，级别: {severity}。\n"
    "告警上下文: {context}\n"
    "可用工具: {tool_names}\n"
    "调查预算: 你最多只能调用 {max_read_tools} 次只读工具（query_metric/query_metric_range/"
    "search_runbook 等，不含 submit_rca_result 与 final_answer）。\n"
    "收敛判据: 先用只读工具收集证据，一旦已有至少 2 条独立证据、且来自至少 2 个不同来源，"
    "就必须停止继续调查并立即收尾提交 RCA；不要为了找更多证据而查满预算。\n"
    "收尾二选一：①首选调用 submit_rca_result 提交结构化 RCA；"
    "②兜底调用 final_answer 时把严格 JSON 放进 <rca_result>...</rca_result> 标签。"
    "JSON 字段：root_cause 为字符串；confidence 为 0 到 1 之间的数字；evidence 为数组且至少 1 条，"
    "每条必须是含 source（字符串，数据源）与 fact（字符串，证据事实）两个字段的对象；"
    "hypotheses 与 recommendations 为字符串数组；summary 可选。"
    "注意：evidence 不要用纯字符串数组；hypotheses 不要用对象数组。"
)


def _build_context(inc) -> str:
    parts = []
    if inc.alert_id:
        parts.append(f"alert_id={inc.alert_id}")
    if inc.source:
        parts.append(f"source={inc.source}")
    if inc.target:
        parts.append(f"target={inc.target}")
    if inc.observed_value is not None:
        parts.append(f"observed_value={inc.observed_value}")
    if inc.threshold is not None:
        parts.append(f"threshold={inc.threshold}")
    if inc.affected_assets:
        parts.append(f"affected_assets={','.join(inc.affected_assets)}")
    if inc.labels:
        parts.append(f"labels={inc.labels}")
    if inc.annotations:
        parts.append(f"annotations={inc.annotations}")
    if inc.start_time:
        parts.append(f"start_time={inc.start_time}")
    return "; ".join(parts)


def _load_prompt_template() -> str:
    try:
        return PROMPT_FILE.read_text(encoding="utf-8")
    except OSError:
        return _DEFAULT_PROMPT


class _ToolAdapter(SmolTool):
    """把普通 Tool 实例的单个公开方法包装成 smolagents.Tool。"""

    # 跳过 forward 签名与 inputs 的强校验，参数校验交给运行时 validate_tool_arguments
    skip_forward_signature_validation = True

    def __init__(self, target, method):
        self._target = target
        self._method = method
        self.name = method.__name__
        self.description = (
            inspect.getdoc(method)
            or f"调用 {type(target).__name__}.{self.name} 收集证据"
        )
        self.inputs = self._build_inputs(method)
        self.output_type = "string"
        self.is_initialized = False
        super().__init__()

    @staticmethod
    def _build_inputs(method):
        inputs = {}
        for name, param in inspect.signature(method).parameters.items():
            if name == "self":
                continue
            nullable = param.default is not inspect.Parameter.empty
            inputs[name] = {
                "type": _map_type(param.annotation, param.default),
                "description": f"参数 {name}",
                "nullable": nullable,
            }
        return inputs

    def forward(self, **kwargs):
        result = self._method(**kwargs)
        if isinstance(result, dict):
            return json.dumps(result, ensure_ascii=False, default=str)
        if hasattr(result, "to_dict"):
            return json.dumps(result.to_dict(), ensure_ascii=False, default=str)
        return str(result)


def _map_type(annotation, default):
    if annotation is not inspect.Parameter.empty:
        name = getattr(annotation, "__name__", str(annotation))
    else:
        name = getattr(type(default), "__name__", "str") if default is not inspect.Parameter.empty else "str"
    return {
        "str": "string",
        "int": "integer",
        "float": "number",
        "bool": "boolean",
        "list": "array",
        "dict": "object",
    }.get(name, "any")


def adapt_tools(tools: list) -> list:
    """把 Task 4 的普通 Tool 实例适配成 smolagents.Tool；已是 smolagents.Tool 的原样返回。"""
    adapted = []
    for tool in tools:
        if isinstance(tool, SmolTool):
            adapted.append(tool)
        else:
            adapted.extend(_wrap_plain_tool(tool))
    return adapted


def _wrap_plain_tool(tool) -> list:
    methods = []
    for name in dir(tool):
        if name.startswith("_"):
            continue
        attr = getattr(tool, name)
        if callable(attr) and getattr(attr, "__self__", None) is tool:
            methods.append(attr)
    if not methods:
        # 没有公开方法时仍包一个，避免 build_agent 在空 tools 外再出问题
        return [_ToolAdapter(tool, _noop)]
    return [_ToolAdapter(tool, m) for m in methods]


def _noop() -> str:
    return "该工具未暴露任何可调用方法"


def build_agent(settings: Settings, tools: list,
                provider: LLMProvider | None = None) -> ToolCallingAgent:
    # 模型由 LLM Provider 产出（可插拔）；Agent 不再直接 new 模型。
    provider = provider or LiteLLMProvider(settings)
    model = provider.make_agent_model()
    return ToolCallingAgent(tools=adapt_tools(tools), model=model, max_steps=settings.agent_max_steps)


def investigate(settings: Settings, svc: IncidentService,
                incident_id: str, tools: list) -> str:
    inc = svc.get(incident_id)
    svc.add_timeline(incident_id, {"event": "开始调查"})
    inc.status = transition(inc.status, S.TRIAGING); svc.update(inc)
    svc.add_timeline(incident_id, {"event": "分诊"})
    inc.status = transition(inc.status, S.INVESTIGATING); svc.update(inc)

    # 绑定本次 Incident 的 RCA 提交工具：只校验 + 存 holder，不写 Incident；
    # 最终状态由本函数作为单一事务边界统一落库（docs/design.md 第 41 章）。
    submit_tool = SubmitRCATool(svc, incident_id)
    smol_tools = adapt_tools([*tools, submit_tool])
    agent = build_agent(settings, smol_tools)
    tool_names = [t.name for t in smol_tools]
    prompt = _load_prompt_template().format(
        title=inc.title,
        service=inc.service,
        severity=inc.severity.value,
        tool_names=tool_names,
        context=_build_context(inc),
        max_read_tools=settings.agent_max_read_tools,
    )

    conclusion: str | None = None
    run_error: BaseException | None = None
    max_steps_hit = False
    try:
        run_result = agent.run(prompt, return_full_result=True)
    except Exception as e:  # noqa: BLE001 - LLM/框架异常统一归到失败路径
        run_error = e
    else:
        output = getattr(run_result, "output", run_result)
        conclusion = output if isinstance(output, str) else str(output)
        max_steps_hit = getattr(run_result, "state", None) == "max_steps_error"

    # 混合收尾（docs/design.md 第 41 章）：RCA 优先级
    #   1) submit_rca_result（工具，首选） > 2) final_answer 的 <rca_result> JSON（兜底） > 3) failure_code
    # 成功产生有效 RCAResult 即锁定；后续文本/错误不降级。

    # 通道 1：工具提交。
    if submit_tool.rca_result is not None:
        _commit_rca(inc, submit_tool.rca_result, "tool")
        if run_error is not None:
            conclusion = f"调查完成（RCA 已锁定，run 中断: {type(run_error).__name__}）"
        svc.add_timeline(incident_id, {"event": f"Agent 结论: {conclusion}"})
        svc.update(inc)
        return conclusion or submit_tool.rca_result.root_cause

    # 通道 2：final 文本兜底（仅 run 正常结束/超步数时有文本；异常则无可解析内容）。
    final_rca = None
    final_code = None
    if run_error is None:
        final_rca, final_code = extract_rca_result(conclusion)
    if final_rca is not None:
        _commit_rca(inc, final_rca, "final_answer")
        svc.add_timeline(incident_id, {"event": f"Agent 结论: {conclusion}"})
        svc.update(inc)
        return conclusion or final_rca.root_cause

    # 两条通道都无有效 RCA → failure state。
    if run_error is not None:
        summary = f"{type(run_error).__name__}: {run_error}"
        svc.add_timeline(incident_id, {"event": f"调查失败: {summary}"})
        inc.failure_code = LLM_ERROR
        inc.status = transition(inc.status, S.ESCALATED)
        svc.update(inc)
        raise run_error

    if max_steps_hit:
        inc.failure_code = MAX_STEPS
        inc.status = transition(inc.status, S.ESCALATED)
    else:
        # 归因：final 区块尝试但非法 > 工具尝试但失败 > 从未提交。
        if final_code is not None:
            code = final_code
        elif submit_tool.submit_attempted:
            code = submit_tool.last_validation_code or MISSING_EVIDENCE
        else:
            code = NO_SUBMISSION
        inc.failure_code = code
        inc.status = transition(inc.status, S.INSUFFICIENT_EVIDENCE)
    svc.add_timeline(incident_id, {"event": f"Agent 结论: {conclusion}"})
    svc.update(inc)
    return conclusion or ""


def _commit_rca(inc, rca, source: str) -> None:
    """单一事务边界：把有效 RCA 落到 Incident（状态机需在调用方已处于 INVESTIGATING）。"""
    inc.rca = rca
    inc.rca_source = source
    inc.root_cause = rca.root_cause
    inc.failure_code = None
    inc.status = transition(inc.status, S.ROOT_CAUSE_FOUND)
