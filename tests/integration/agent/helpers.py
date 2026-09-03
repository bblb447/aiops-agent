"""L2 确定性 Agent 辅助：脚本化模型 + 消息轨迹提取（spec §45.4）。

模型不推理——按 plan 依序产出工具调用；测试对象是工具链/状态机/收尾。
"""
import json

from smolagents.models import ChatMessage, MessageRole, Model


class ScriptedDiagnosisModel(Model):
    """按计划依次产出工具调用 JSON，并记录每轮对话快照到 self.calls。"""

    def __init__(self, plan):
        super().__init__(model_id="scripted-l2")
        self.plan = list(plan)
        self.calls = []

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        if self.plan:
            tc = self.plan.pop(0)
        else:
            tc = {"name": "final_answer", "arguments": {"answer": "兜底结论"}}
        return ChatMessage(
            role=MessageRole.ASSISTANT,
            content=json.dumps({"name": tc["name"], "arguments": tc["arguments"]}, ensure_ascii=False),
        )


def _as_text(content) -> str:
    """smolagents 消息 content 可能是 str 或 content-block list，统一展平成文本。"""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(b.get("text", "") for b in content
                       if isinstance(b, dict) and b.get("type") == "text")
    if isinstance(content, dict):
        return content.get("text", "") or ""
    return str(content)


def assistant_tool_calls(model) -> list[str]:
    """有序工具调用轨迹：每次 generate 的最新 ASSISTANT 消息 json.name。"""
    names = []
    for msgs in model.calls:
        for m in reversed(msgs):
            if m.role == MessageRole.ASSISTANT:
                try:
                    names.append(json.loads(_as_text(m.content))["name"])
                except (TypeError, ValueError, KeyError):
                    pass
                break
    return names


def tool_response_text(model, at: int) -> str:
    """第 at 轮（1-index，第 1 个工具结果在 at=1）的全部 TOOL_RESPONSE 文本。"""
    parts = []
    for m in model.calls[at]:
        if m.role == MessageRole.TOOL_RESPONSE:
            parts.append(_as_text(m.content))
    return "\n".join(parts)
