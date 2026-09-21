from enum import Enum


class EvidenceSource(str, Enum):
    """Evidence provenance 的唯一合法来源词表（F3 spec §3.1）。

    来源 = "这条证据由哪个工具声明的数据源提供"。新增数据源在此加成员，
    工具以 `source_type = EvidenceSource.X` 引用（typo 在声明层即暴露）。
    """

    PROMETHEUS = "prometheus"
    LOKI = "loki"
    CMDB = "cmdb"
    RUNBOOK = "runbook"
