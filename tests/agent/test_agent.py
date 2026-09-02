import json

from app.config import Settings
from app.incident.service import IncidentService
from app.incident.model import IncidentStatus as S
from app.agent.agent import investigate


def _rca_block(data) -> str:
    return ("调查完成：\n<rca_result>\n"
            + json.dumps(data, ensure_ascii=False)
            + "\n</rca_result>")


class _Run:
    """模拟 smolagents run(return_full_result=True) 的 RunResult 外形。"""
    def __init__(self, output, state="success"):
        self.output = output
        self.state = state


class _FakeAgent:
    def __init__(self, tools=None, max_steps=None):
        self._tools = tools or []
        self._max_steps = max_steps
        self.prompt = None
        self.state = "success"
        self.output = "根因: 最近发布导致版本回归，置信度 0.86"

    @property
    def tools(self):
        return self._tools

    @property
    def max_steps(self):
        return self._max_steps

    def _submit_adapter(self):
        return next((t for t in self._tools if getattr(t, "name", "") == "submit_rca_result"), None)

    def submit(self, valid=True):
        a = self._submit_adapter()
        if a is None:
            return
        if valid:
            a.forward(root_cause="版本回归", confidence=0.86,
                      evidence=[{"source": "prometheus", "fact": "CPU 95.2%"}])
        else:
            a.forward(root_cause="", confidence=0.86, evidence=[])

    def submit_conf(self, confidence):
        a = self._submit_adapter()
        if a is not None:
            a.forward(root_cause="x", confidence=confidence,
                      evidence=[{"source": "s", "fact": "f"}])

    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output=self.output, state=self.state)


class _NoSubmitAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output="", state="success")


class _SubmitAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        self.submit(valid=True)
        return _Run(output="调查完成", state="success")


class _InvalidSubmitAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        self.submit(valid=False)
        return _Run(output="尝试提交失败", state="success")


class _LowConfidenceAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        self.submit_conf(1.5)
        return _Run(output="低置信度", state="success")


class _MaxStepsAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output="到达最大步数", state="max_steps_error")


class _MaxStepsWithValidFinalAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output=_rca_block({
            "root_cause": "内存泄漏", "confidence": 0.7,
            "evidence": [{"source": "prometheus", "fact": "CPU 95.2%"}],
        }), state="max_steps_error")


class _FailingAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        raise RuntimeError("LLM 网络超时")


class _FinalJsonAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output=_rca_block({
            "root_cause": "内存泄漏", "confidence": 0.7,
            "evidence": [{"source": "prometheus", "fact": "CPU 95.2%"}],
        }), state="success")


class _MalformedFinalAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        return _Run(output=_rca_block({
            "root_cause": "x", "confidence": 0.8,
            "evidence": ["CPU 很高"],
        }), state="success")


class _ToolFailThenFinalOkAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        self.submit(valid=False)  # 工具校验失败
        return _Run(output=_rca_block({
            "root_cause": "内存泄漏", "confidence": 0.7,
            "evidence": [{"source": "prometheus", "fact": "CPU 95.2%"}],
        }), state="success")


class _ToolWinsOverFinalAgent(_FakeAgent):
    def run(self, prompt, return_full_result=True):
        self.prompt = prompt
        self.submit(valid=True)  # 工具成功
        return _Run(output=_rca_block({
            "root_cause": "final-json-结论", "confidence": 0.99,
            "evidence": [{"source": "x", "fact": "y"}],
        }), state="success")


def test_investigate_uses_prompt_template(monkeypatch, tmp_path):
    # prompt 模板文件被加载并填充 incident 数据（而非内联字符串）；
    # 本轮工具列表至少包含 submit_rca_result。
    tpl = tmp_path / "prompt.txt"
    tpl.write_text("模板: {title} / {service} / {severity} / {tool_names}", encoding="utf-8")
    monkeypatch.setattr("app.agent.agent.PROMPT_FILE", tpl)
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    cap = _FakeAgent()
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: cap)
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    assert cap.prompt == "模板: CPU 高 / order-service / critical / ['submit_rca_result']"


def test_investigate_prompt_falls_back_when_template_missing(monkeypatch, tmp_path):
    monkeypatch.setattr("app.agent.agent.PROMPT_FILE", tmp_path / "nonexistent.txt")
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    cap = _FakeAgent()
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: cap)
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    assert "AIOps 诊断 Agent" in cap.prompt
    assert "CPU 高" in cap.prompt


def test_investigate_prompt_includes_alert_context(monkeypatch):
    # 告警上下文（alert_id/target/observed_value/threshold）必须注入 prompt。
    svc = IncidentService()
    inc = svc.create(
        "CPU 高", "order-service", "critical",
        alert_id="alert-001", source="prometheus", target="server-01",
        observed_value=95.2, threshold=80,
    )
    cap = _FakeAgent()
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: cap)
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    assert "alert-001" in cap.prompt
    assert "server-01" in cap.prompt
    assert "95.2" in cap.prompt
    assert "80" in cap.prompt


def test_investigate_no_submission_is_insufficient(monkeypatch):
    # 只调 final_answer / 没提交 submit_rca_result → 不得 ROOT_CAUSE_FOUND。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _NoSubmitAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.INSUFFICIENT_EVIDENCE
    assert got.failure_code == "NO_SUBMISSION"
    assert got.rca is None


def test_investigate_submit_success_is_root_cause_found(monkeypatch):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _SubmitAgent(t, s.agent_max_steps))
    out = investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca is not None
    assert got.rca.root_cause == "版本回归"
    assert got.rca.confidence == 0.86
    assert got.rca_source == "tool"
    # root_cause 由 rca 派生同步。
    assert got.root_cause == "版本回归"
    assert out == "调查完成"


def test_investigate_invalid_submission_is_missing_evidence(monkeypatch):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _InvalidSubmitAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.INSUFFICIENT_EVIDENCE
    assert got.failure_code == "MISSING_EVIDENCE"
    assert got.rca is None


def test_investigate_low_confidence_is_insufficient(monkeypatch):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _LowConfidenceAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.INSUFFICIENT_EVIDENCE
    assert got.failure_code == "LOW_CONFIDENCE"


def test_investigate_max_steps_is_escalated(monkeypatch):
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _MaxStepsAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ESCALATED
    assert got.failure_code == "MAX_STEPS"


def test_investigate_max_steps_with_valid_final_json_is_root_cause(monkeypatch):
    # 超步数但 final 文本含合法 <rca_result> → 仍接受为 RCA（有效结果优先于失败状态）。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _MaxStepsWithValidFinalAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.rca_source == "final_answer"
    assert got.rca.root_cause == "内存泄漏"


def test_investigate_final_json_fallback(monkeypatch):
    # 未调用 submit 工具，但 final 文本含合法 <rca_result> → 兜底成立。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _FinalJsonAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.failure_code is None
    assert got.rca_source == "final_answer"
    assert got.rca.root_cause == "内存泄漏"
    assert got.root_cause == "内存泄漏"


def test_investigate_tool_fail_then_final_json_ok(monkeypatch):
    # Case C：工具提交失败不阻断 final JSON 兜底。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _ToolFailThenFinalOkAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.rca_source == "final_answer"


def test_investigate_tool_wins_over_final_json(monkeypatch):
    # Case D：工具成功 → 工具结果锁定，final JSON 忽略。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _ToolWinsOverFinalAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ROOT_CAUSE_FOUND
    assert got.rca_source == "tool"
    assert got.rca.root_cause == "版本回归"


def test_investigate_final_json_malformed_is_missing_evidence(monkeypatch):
    # final 有区块但 evidence 是字符串数组 → schema 拒绝 → MISSING_EVIDENCE。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _MalformedFinalAgent(t, s.agent_max_steps))
    investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.INSUFFICIENT_EVIDENCE
    assert got.failure_code == "MISSING_EVIDENCE"
    assert got.rca is None


def test_investigate_escalates_on_llm_failure(monkeypatch):
    svc = IncidentService()
    inc = svc.create("连接超时", "payment-service", "critical")
    monkeypatch.setattr("app.agent.agent.build_agent", lambda s, t: _FailingAgent(t, s.agent_max_steps))
    import pytest
    with pytest.raises(RuntimeError):
        investigate(Settings(llm_api_key="sk-test"), svc, inc.incident_id, tools=[])
    got = svc.get(inc.incident_id)
    assert got.status == S.ESCALATED
    assert got.failure_code == "LLM_ERROR"
    assert any("调查失败" in t.get("event", "") for t in got.timeline)
    assert got.root_cause is None


def test_adapter_forward_dispatches_to_tool(monkeypatch):
    # 覆盖适配器最高风险代码路径：_ToolAdapter.forward 动态派发 -> ToolResult
    # to_dict -> JSON 序列化，以及输入 schema 映射（metric/target）。
    import json
    import httpx
    from app.agent.agent import adapt_tools
    from app.tools.monitoring import MonitoringTool

    s = Settings(prometheus_url="http://127.0.0.1:9")
    tool = MonitoringTool(s)

    def fake_get(url, params=None, timeout=None):
        return httpx.Response(200, request=httpx.Request("GET", str(url)),
                              json={"status": "success", "data": {"result": [{"value": [0, "94.5"]}]}})
    monkeypatch.setattr(httpx, "get", fake_get)

    adapters = adapt_tools([tool])
    adapter = next(a for a in adapters if a.name == "query_metric")
    # 输入 schema 映射：metric/target 必须出现在 smolagents 的 inputs 里。
    assert {"metric", "target"} <= set(adapter.inputs)
    out = adapter.forward(metric="cpu_usage", target="srv")
    # 返回的是合法 JSON，且能解析出 Prometheus 的 data.data.result。
    parsed = json.loads(out)
    assert parsed["success"] is True
    assert parsed["tool"] == "query_metric"
    assert parsed["data"]["data"]["result"][0]["value"][1] == "94.5"


def test_build_agent_accepts_task4_tools():
    from smolagents import ToolCallingAgent
    from app.agent.agent import build_agent
    from app.tools.monitoring import MonitoringTool
    from app.tools.logging import LoggingTool
    from app.tools.cmdb import CMDBTool
    from app.tools.knowledge import KnowledgeTool
    s = Settings(llm_api_key="sk-test", llm_base_url="http://127.0.0.1:9999", llm_model="test-model")
    tools = [MonitoringTool(s), LoggingTool(s), CMDBTool(s), KnowledgeTool(s)]
    agent = build_agent(s, tools)
    assert isinstance(agent, ToolCallingAgent)
    assert {"query_metric", "search_logs", "get_service", "search_runbook"} <= set(agent.tools)
    assert agent.max_steps == s.agent_max_steps


def test_build_agent_accepts_empty_tools():
    from smolagents import ToolCallingAgent
    from app.agent.agent import build_agent
    s = Settings(llm_api_key="sk-test")
    agent = build_agent(s, [])
    assert isinstance(agent, ToolCallingAgent)
    assert agent.max_steps == s.agent_max_steps
    assert "final_answer" in agent.tools


def test_build_agent_tool_choice_auto():
    # DeepSeek 思考模式不接受 tool_choice="required"（BadRequestError），
    # 构造出的 LiteLLMModel 必须显式用 "auto"。
    from smolagents import LiteLLMModel
    from app.agent.agent import build_agent
    s = Settings(llm_api_key="sk-test")
    agent = build_agent(s, [])
    assert isinstance(agent.model, LiteLLMModel)
    assert agent.model.kwargs.get("tool_choice") == "auto"


def test_build_agent_uses_injected_provider():
    # Agent 的模型必须经由 LLM Provider 产出（模型可插拔），而非 agent 内部
    # 直接 new 模型；注入的 provider.make_agent_model 结果要被 agent 使用。
    from smolagents import LiteLLMModel
    from app.agent.agent import build_agent

    class _FakeProvider:
        def __init__(self):
            self.calls = 0

        def make_agent_model(self):
            self.calls += 1
            return LiteLLMModel(model_id="openai/provided-model", api_key="x", tool_choice="auto")

        def chat(self, messages):
            return "x"

    s = Settings(llm_api_key="sk-test")
    p = _FakeProvider()
    agent = build_agent(s, [], provider=p)
    assert p.calls == 1
    assert isinstance(agent.model, LiteLLMModel)
    assert agent.model.model_id == "openai/provided-model"
