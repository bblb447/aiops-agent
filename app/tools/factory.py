from app.config import Settings
from app.tools.cmdb import CMDBTool
from app.tools.knowledge import KnowledgeTool
from app.tools.logging import LoggingTool
from app.tools.monitoring import MonitoringTool


def build_tools(settings: Settings) -> list:
    """按配置实例化全部只读工具，供 Agent 动态诊断使用。"""
    return [
        MonitoringTool(settings),
        LoggingTool(settings),
        CMDBTool(settings),
        KnowledgeTool(settings),
    ]
