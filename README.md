# AIOps Agent

基于 **smolagents** 的 **Evidence-driven AIOps Diagnostic Agent**：从告警触发到根因结论的只读闭环。Agent 动态调用监控、日志、CMDB、Runbook 工具收集证据，给出带证据、带置信度的根因分析。

> **定位**：Agent-first 的故障诊断/RCA 引擎，不是告警管理平台（告警治理交给平台层，本项目可作其独立 RCA 子系统）。当前为只读诊断闭环，不执行生产写操作。V1.5 结构化 RCA / V1.6 调查收敛 / V1.7 调查结果语义已实现（详见 [docs/design.md](docs/design.md) 第 41-42 / 47 章）。

## 功能

- **告警 → Incident → 动态诊断 → 根因结论**：FastAPI 接收告警建单，smolagents `ToolCallingAgent` 驱动多步工具调用完成调查。
- **多源运维数据关联**：Prometheus 指标、Loki 日志、CMDB 服务信息、Runbook 知识。
- **RAG 语义检索**：Runbook 按标题切块，`bge-small-zh` 嵌入 + chromadb 向量检索，返回 top-k 相关排查步骤；依赖/模型不可用时自动降级关键词搜索。
- **Incident 状态机**：NEW → TRIAGING → INVESTIGATING → … → RESOLVED / ESCALATED / REOPEN，非法转移抛错，全表参数化测试覆盖。
- **模型可插拔**：LLM Provider 抽象（`make_agent_model` 产出 Agent 模型），仅需配置 Endpoint / Key / Model，不绑定厂商。
- **告警上下文入 Incident**：创建时携带 `source/alert_id/target/labels/annotations/observed_value/threshold/affected_assets`，注入诊断 prompt，RCA 有真实故障数据可用。
- **时间序列查询**：`query_metric_range`（Prometheus range query）+ `search_logs` 可指定时间窗，支撑时间关联分析。
- **服务负载展示（workload）**：`GET /api/v1/workload/{service}` + Agent 工具 `query_workload` 复用同一 `WorkloadService`，返回服务 QPS/错误率/CPU/内存汇总（Prometheus）。
- **结构化 RCA（V1.5）**：`RCAResult`（`verdict / root_cause / confidence / evidence[] / hypotheses[]`）写入 `Incident.rca`，`rca_source` 记录来源。混合收尾：首选 `submit_rca_result` 工具，兜底为 `final_answer` 中 `<rca_result>` 标签的严格 JSON，两条通道共用同一 schema 校验（`rca_source` = tool / final_answer）。无有效 RCA 不得 `ROOT_CAUSE_FOUND`；失败归因 `failure_code`（六码：NO_SUBMISSION / MISSING_EVIDENCE / LOW_CONFIDENCE / LLM_ERROR / TOOL_ERROR / MAX_STEPS）。真实模型冒烟验证见 `scripts/smoke_real_llm.py`。
- **调查结果语义（V1.7）**：`status`（生命周期/处置）与 `verdict`（对世界的判断）拆成两轴。`verdict ∈ {ROOT_CAUSE_FOUND, NO_ANOMALY, INCONCLUSIVE}`（不含 ESCALATED）：找到根因→ROOT_CAUSE_FOUND；告警被证伪/无异常→NO_ANOMALY 直关 `RESOLVED`；证据不足可显式提交 INCONCLUSIVE（查过但不足以定论，属合法结论）。`root_cause`/`confidence` 业务必填由 verdict 条件约束，legacy（无 verdict + root_cause 非空）自动按 ROOT_CAUSE_FOUND 兼容。Tool/Final 双通道共享 RCAResult 中央校验。
- **证据来源归属（F3）**：`EvidenceItem.source` 受域契约 `EvidenceSource` 约束（`prometheus` / `loki` / `cmdb` / `runbook`），大小写与首尾空白自动归一，语义变体（如 `query_workload`、`Prometheus Server`）被拒并返回可读错误。合法值集合**唯一来源**于 `app/incident/sources.py`，工具以 `source_type` 声明归属，agent prompt 与工具描述中的允许值均由该枚举派生。**Provenance 强度为 B（词表合规），不是 C（调用级真归属）**：本阶段只保证提交的 `source` 落在词表内，不证明某条 evidence 真的来自某次特定工具调用；`call_id` 真归属见 design.md §48.2 Future Evolution。`failure_code` 六码不变。L3 真实 DeepSeek source 正向合规复验已于 2026-09-21 通过（B/C 场景，24/24 canonical）；非法 source 的拒绝路径由 L0 覆盖，未在真实模型下演示。

## 技术栈

| 层 | 技术 |
|---|---|
| Agent 编排 | smolagents `ToolCallingAgent` |
| LLM | OpenAI 兼容 + LiteLLM Provider（可插拔；默认/已验证：DeepSeek） |
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
python -m pytest   # 328 passed
```

L1 真实后端集成测试（需先运行 `tests/integration/scripts/setup_integration.ps1` 下载二进制）：

```bash
python -m pytest -m integration tests/integration/ --ignore=tests/integration/agent   # 14 passed
```

L2 真实后端 + Scripted Agent（本地/手工；Agent 层 import smolagents，不进 L1 CI）：

```bash
python -m pytest -m integration tests/integration/agent/   # 3 passed
```

L3 真实 DeepSeek + 真实后端观测脚本（`scripts/l3_real_backend.py`；非 CI gate，需 `.env` 的 LLM key）：
对 A/B/C 三场景跑真实模型 observation，验证真实后端观测链路并采集真实模型行为 baseline；
默认只观测不失败，`--expect` 提供可选门禁；backend 生命周期由 `tests/integration/backend.py` 手工管理。

```bash
PYTHONIOENCODING=utf-8; python tests/integration/backend.py up
PYTHONIOENCODING=utf-8; python scripts/l3_real_backend.py                # 默认只观测（A/B/C）
PYTHONIOENCODING=utf-8; python scripts/l3_real_backend.py --expect convergence
python tests/integration/backend.py down
```

真实 L3 已验证“告警被证伪”可经 `verdict=NO_ANOMALY / status=RESOLVED` 正确表达（V1.7 §47）；证据来源归属（`source` 字段模型乱填）已在代码契约层收敛于 F3 Provenance（见 `docs/design.md` §48.2）；收敛稳定性（预算偶超）仍为后续收敛 / Hard Budget 待议项，详见 `docs/design.md` §46（L3）。

详见 `tests/integration/README.md` 与 `docs/design.md` §44（L1）/§45（L2）/§46（L3）。

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
├── workload/    Workload 模型与 Prometheus 服务（API + 工具共用）
├── tools/       只读工具（监控/日志/CMDB/Runbook）
├── config.py    pydantic-settings 配置
└── main.py      应用入口
prompts/         Agent 诊断 prompt 模板
runbooks/        Runbook 知识（RAG 数据源）
tests/           pytest 全量测试
docs/design.md   完整设计文档（48 章，V1.5 结构化 RCA / V1.6 收敛 / 1.3 Workload / V1.7 调查结果语义 §47 / V1 收口与 V2 路线图 §48）
```

## License

[MIT](LICENSE)
