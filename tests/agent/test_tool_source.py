"""F3：工具 source_type 声明与描述生成（spec §3.2 / §5.1）。"""
from app.agent.agent import adapt_tools
from app.agent.submit_tool import SubmitRCATool
from app.config import Settings
from app.incident.service import IncidentService
from app.incident.sources import EvidenceSource
from app.tools.factory import build_tools
from app.tools.monitoring import MonitoringTool

EXPECTED = {
    "MonitoringTool": EvidenceSource.PROMETHEUS,
    "LoggingTool": EvidenceSource.LOKI,
    "CMDBTool": EvidenceSource.CMDB,
    "KnowledgeTool": EvidenceSource.RUNBOOK,
    "KubernetesTool": EvidenceSource.KUBERNETES,
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
    assert "kubernetes" in adapters["list_pods"].description


def test_submit_tool_has_no_source_type_and_adapts_without_error():
    # SubmitRCATool 不是数据源：不声明 source_type，且经 adapt_tools 不抛异常。
    svc = IncidentService()
    inc = svc.create("CPU 高", "order-service")
    tool = SubmitRCATool(svc, inc.incident_id)
    assert getattr(tool, "source_type", None) is None
    adapters = adapt_tools([tool])
    assert [a.name for a in adapters] == ["submit_rca_result"]
    assert "SubmitRCATool" not in adapters[0].description


# --- Fix round 1：补两条覆盖缺口 -------------------------------------------------

class _CountingMonitoring(MonitoringTool):
    """L3 插桩子类形态（scripts/l3_real_backend.py 同名类的简化复刻）。

    build_tools() 只返回四个基类实例，故原
    test_adapter_description_never_leaks_python_class_name 从未把子类名送进断言；
    本测试补上——它正是本任务要修的 bug 形态。
    """


def test_l3_subclass_adapter_description_does_not_leak_class_name():
    # 走真实描述生成路径（adapt_tools → _ToolAdapter），不手搓 _ToolAdapter。
    adapters = adapt_tools([_CountingMonitoring(Settings())])
    assert {a.name for a in adapters} == {"query_metric", "query_metric_range", "query_workload"}
    for adapter in adapters:
        # 描述来自工具元数据/能力，而非任何具体 Python 类名。
        assert "_CountingMonitoring" not in adapter.description
        assert "MonitoringTool" not in adapter.description
        # 去类名不等于丢来源指引：prometheus 指引必须在。
        assert "prometheus" in adapter.description


class _DocStubTool:
    """本地桩：暴露的方法带真实 docstring，用于覆盖描述构造的 has-docstring 分支。

    四个真实工具方法当前都无 docstring，getdoc 恒 None，or 兜底是唯一被走到的分支。
    """

    source_type = EvidenceSource.CMDB
    exposed_methods = ["lookup"]

    def lookup(self, key: str) -> dict:
        """查询 CMDB 中的服务信息。"""
        return {}


def test_docstring_branch_keeps_docstring_and_still_carries_source_guidance():
    adapters = adapt_tools([_DocStubTool()])
    assert [a.name for a in adapters] == ["lookup"]
    description = adapters[0].description
    assert "查询 CMDB 中的服务信息。" in description
    assert "证据来源(source)：cmdb" in description
    assert "_DocStubTool" not in description


def test_evidence_source_vocabulary_includes_kubernetes():
    # spec §2.6：唯一受控 V1 additive 扩展——来源词表新增 kubernetes。
    assert EvidenceSource.KUBERNETES.value == "kubernetes"
    assert "kubernetes" in {s.value for s in EvidenceSource}

