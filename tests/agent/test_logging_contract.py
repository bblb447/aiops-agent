"""#11：LogQL / label 契约经 tool description 暴露给模型（spec §6 / §7）。"""
from app.agent.agent import adapt_tools
from app.config import Settings
from app.tools.logging import LoggingTool


def _description(settings: Settings) -> str:
    """走真实适配链路（adapt_tools → _ToolAdapter），不手搓适配器。"""
    adapters = {a.name: a for a in adapt_tools([LoggingTool(settings)])}
    return adapters["search_logs"].description


# --- 恒定段：与配置无关，恒呈现 ---


def test_constant_section_present_when_unconfigured():
    # 显式传 [] 而非依赖本机 .env 未配置 —— 用例必须确定性
    d = _description(Settings(loki_label_keys=[]))
    assert "合法 LogQL" in d
    assert "{<label-key>=\"<value>\"}" in d
    assert "|= \"<text>\"" in d
    assert "纯文本" in d
    # 400 契约也在契约文案里告知模型（spec §7 恒定段最后一句）
    assert "HTTP 状态码" in d


# --- 配置段：仅在有配置时附加 ---


def test_deployment_section_present_when_configured():
    d = _description(Settings(loki_label_keys=["app"]))
    assert "本部署可用的 Loki stream label key" in d
    assert "app" in d
    assert '{app="<value>"}' in d


def test_deployment_section_joins_multiple_keys():
    d = _description(Settings(loki_label_keys=["app", "service_name"]))
    assert "app / service_name" in d


# --- 核心回归钉子：绝不内置 app ---


def test_unconfigured_description_never_mentions_app():
    # spec §7 / §11：空配置时不得出现任何 deployment label 假设。
    # fixture 的 app 只是测试环境事实，不得泄漏成产品默认。
    d = _description(Settings(loki_label_keys=[]))
    assert "app" not in d
    assert "本部署" not in d


def test_unconfigured_extra_description_has_no_app():
    # 同一钉子下沉到 Tool 自身（不依赖适配器行为）
    tool = LoggingTool(Settings(loki_label_keys=[]))
    assert "app" not in tool.extra_description
    assert "本部署" not in tool.extra_description
