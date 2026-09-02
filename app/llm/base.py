from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """messages: [{"role": ..., "content": ...}]，返回模型文本。"""

    @abstractmethod
    def make_agent_model(self):
        """返回 smolagents 可用的 Model 实例，供 Agent 工具调用闭环使用。"""
