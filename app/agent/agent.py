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

from smolagents import ToolCallingAgent, LiteLLMModel
from smolagents.tools import Tool as SmolTool

from app.config import Settings
from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S
from app.incident.state import transition


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


def build_agent(settings: Settings, tools: list) -> ToolCallingAgent:
    model = LiteLLMModel(
        model_id=f"openai/{settings.llm_model}",
        api_base=settings.llm_base_url,
        api_key=settings.llm_api_key,
        # DeepSeek 思考模式不接受 tool_choice="required"（会抛 BadRequestError），
        # 显式设为 "auto" 以兼容。
        tool_choice="auto",
        temperature=0.1,
    )
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
    prompt = (
        f"你是 AIOps 诊断 Agent。请调查以下故障并给出带证据的根因结论。\n"
        f"故障: {inc.title}，服务: {inc.service}，级别: {inc.severity}。\n"
        f"可用只读工具: {tool_names}\n"
        f"步骤: 先查监控和日志收集证据，再给出结论与置信度。"
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
