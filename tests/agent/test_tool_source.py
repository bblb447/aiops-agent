"""F3：工具 source_type 声明与描述生成（spec §3.2 / §5.1）。"""
from app.agent.agent import adapt_tools
from app.agent.submit_tool import SubmitRCATool
from app.config import Settings
from app.incident.service import IncidentService
from app.incident.sources import EvidenceSource
from app.tools.factory import build_tools

EXPECTED = {
    "MonitoringTool": EvidenceSource.PROMETHEUS,
    "LoggingTool": EvidenceSource.LOKI,
    "CMDBTool": EvidenceSource.CMDB,
    "KnowledgeTool": EvidenceSource.RUNBOOK,
}

PYTHON_CLASS_NAMES = ["MonitoringTool", "LoggingTool", "CMDBTool", "KnowledgeTool",
                      "SubmitRCATool", "_CountingMonitoring", "_CountingLogging",
                      "_CountingKnowledge"]


def test_read_tools_declare_expected_source_type():
    for tool in build_tools(Settings()):
        assert getattr(tool, "source_type", None) is EXPECTED[type(tool).__name__]


def test_declared_source_types_subset_of_vocabulary():
    # §6 单一事实源：工具声明不得引用词表之外的来源（typo 在此暴露）。
    declared = {t.source_type for t in build_tools(Settings())}
    assert declared <= set(EvidenceSource)


def test_adapter_description_never_leaks_python_class_name():
    for adapter in adapt_tools(build_tools(Settings())):
        for cls_name in PYTHON_CLASS_NAMES:
            assert cls_name not in adapter.description


def test_adapter_description_carries_source_guidance():
    adapters = {a.name: a for a in adapt_tools(build_tools(Settings()))}
    assert "prometheus" in adapters["query_metric"].description
    assert "loki" in adapters["search_logs"].description
    assert "cmdb" in adapters["get_service"].description
    assert "runbook" in adapters["search_runbook"].description


def test_submit_tool_has_no_source_type_and_adapts_without_error():
    # SubmitRCATool 不是数据源：不声明 source_type，且经 adapt_tools 不抛异常。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    tool = SubmitRCATool(svc, inc.incident_id)
    assert getattr(tool, "source_type", None) is None
    adapters = adapt_tools([tool])
    assert [a.name for a in adapters] == ["submit_rca_result"]
    assert "SubmitRCATool" not in adapters[0].description
