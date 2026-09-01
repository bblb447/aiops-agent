from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    def chat(self, messages: list[dict]) -> str:
        """messages: [{"role": ..., "content": ...}]，返回模型文本。"""
