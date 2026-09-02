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

from app.config import Settings
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
    "可用只读工具: {tool_names}\n"
    "步骤: 先查监控和日志收集证据，再给出结论与置信度。"
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

    smol_tools = adapt_tools(tools)
    agent = build_agent(settings, smol_tools)
    tool_names = [t.name for t in smol_tools]
    prompt = _load_prompt_template().format(
        title=inc.title,
        service=inc.service,
        severity=inc.severity.value,
        tool_names=tool_names,
        context=_build_context(inc),
    )
    try:
        conclusion = agent.run(prompt)
    except Exception as e:
        # LLM 调用失败（网络/鉴权/服务端错误）：记录 timeline 并把 incident
        # 从 INVESTIGATING 转 ESCALATED，随后 re-raise 让 API 层能看到失败。
        summary = f"{type(e).__name__}: {e}"
        svc.add_timeline(incident_id, {"event": f"调查失败: {summary}"})
        inc.status = transition(inc.status, S.ESCALATED)
        svc.update(inc)
        raise

    svc.add_timeline(incident_id, {"event": f"Agent 结论: {conclusion}"})
    inc.root_cause = conclusion
    if str(conclusion or "").strip():
        inc.status = transition(inc.status, S.ROOT_CAUSE_FOUND)
    else:
        inc.status = transition(inc.status, S.INSUFFICIENT_EVIDENCE)
    svc.update(inc)
    return conclusion
