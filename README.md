# AIOps Agent

基于 **smolagents** 的智能运维（AIOps）诊断 Agent：从告警触发到根因结论的只读闭环。Agent 动态调用监控、日志、CMDB、Runbook 工具收集证据，给出 Evidence-based 根因分析。

> **MVP 定位**：只读诊断闭环，不执行生产写操作。V2 增加 K8s/网络/审批/审计，V3 增加多 Agent/MCP/自愈（详见 [docs/design.md](docs/design.md)）。

## 功能

- **告警 → Incident → 动态诊断 → 根因结论**：FastAPI 接收告警建单，smolagents `ToolCallingAgent` 驱动多步工具调用完成调查。
- **多源运维数据关联**：Prometheus 指标、Loki 日志、CMDB 服务信息、Runbook 知识。
- **RAG 语义检索**：Runbook 按标题切块，`bge-small-zh` 嵌入 + chromadb 向量检索，返回 top-k 相关排查步骤；依赖/模型不可用时自动降级关键词搜索。
- **Incident 状态机**：NEW → TRIAGING → INVESTIGATING → … → RESOLVED / ESCALATED / REOPEN，非法转移抛错，全表参数化测试覆盖。
- **模型可插拔**：LLM Provider 抽象，仅需配置 Endpoint / Key / Model，不绑定厂商。

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | smolagents `ToolCallingAgent` |
| LLM | DeepSeek（OpenAI 兼容），LiteLLM 接入 |
| API | FastAPI + uvicorn |
| 语义检索 | fastembed（`BAAI/bge-small-zh-v1.5`）+ chromadb |
| 数据源 | Prometheus / Loki / CMDB / runbooks |

## 快速开始

前置：Python 3.12。

```bash
# 1. 安装依赖（境内建议加 -i https://pypi.tuna.tsinghua.edu.cn/simple）
pip install -r requirements.txt

# 2. 配置环境变量（首次模型下载设 HF_ENDPOINT=https://hf-mirror.com 可加速）
cp .env.example .env
#    编辑 .env 填入 LLM API Key、Prometheus/Loki/CMDB 地址

# 3. 启动服务
uvicorn app.main:app --reload

# 4. 创建 Incident 并触发调查
curl -X POST localhost:8000/api/v1/incidents \
  -H 'Content-Type: application/json' \
  -d '{"title": "order-service CPU 持续高", "service": "order-service", "severity": "critical", \
       "source": "prometheus", "alert_id": "alert-001", "target": "server-01", \
       "labels": {"instance": "server-01"}, "annotations": {"summary": "CPU high"}, \
       "observed_value": 95.2, "threshold": 80, "affected_assets": ["server-01"]}'
# 得到 incident_id 后：
curl -X POST localhost:8000/api/v1/incidents/{incident_id}/investigate
```

运行测试（需使用项目 venv 解释器，勿用全局 Python）：

```bash
python -m pytest   # 201 passed
```

## 配置（.env）

| 变量 | 说明 | 默认 |
|---|---|---|
| `llm_base_url` / `llm_api_key` / `llm_model` | LLM 接入 | DeepSeek |
| `prometheus_url` / `loki_url` / `cmdb_url` | 数据源地址 | 空（未配置工具返回结构化失败，不阻断诊断） |
| `rag_enabled` / `rag_top_k` | RAG 开关 / 检索条数 | `true` / `3` |
| `agent_max_steps` | Agent 最大步数 | `10` |

## 目录结构

```text
app/
├── agent/       smolagents Agent、Tool 适配层、诊断流程
├── api/         FastAPI 路由（incidents）
├── incident/    Incident 模型、状态机、服务（内存存储）
├── knowledge/   RAG：chunker 切块 / fastembed 嵌入 / chromadb 检索
├── llm/         LLM Provider 抽象（LiteLLM 实现）
├── tools/       只读工具（监控/日志/CMDB/Runbook）
├── config.py    pydantic-settings 配置
└── main.py      应用入口
prompts/         Agent 诊断 prompt 模板
runbooks/        Runbook 知识（RAG 数据源）
tests/           pytest 全量测试
docs/design.md   完整设计文档（39+1 章）
```

## License

[MIT](LICENSE)
