# 基于 smolagents 的 AIOps Agent 系统设计文档

**文档版本：** V1.2（V1.5 结构化 RCA 已实现见第 41 章；V1.6 Investigation Convergence 实验定稿见第 42 章）
**项目名称：** AIOps Agent
**核心框架：** smolagents
**文档类型：** 系统设计文档
**模型服务：** 用户自行配置，系统通过统一模型接口调用

---

# 1. 项目概述

## 1.1 项目背景

传统运维系统通常由监控、日志、CMDB、链路追踪、自动化执行、工单等多个独立系统组成。

发生故障时，运维人员需要人工完成：

```text
发现告警
   ↓
确认影响范围
   ↓
查看监控
   ↓
查询日志
   ↓
查询主机
   ↓
查询网络
   ↓
查询最近变更
   ↓
结合经验判断根因
   ↓
制定处理方案
   ↓
执行操作
   ↓
验证恢复
```

这个过程存在以下问题：

* 运维信息分散；
* 告警与故障之间缺少上下文关联；
* 根因分析依赖个人经验；
* 故障处理耗时较长；
* 自动化脚本只能执行固定流程；
* 缺少完整的诊断和决策闭环。

因此，本项目设计一个基于 **smolagents** 的 AIOps Agent，通过 LLM 的推理能力与运维工具结合，实现从故障发现到故障恢复的智能闭环。

---

# 2. 项目目标

## 2.1 总体目标

构建一个具备以下能力的智能运维 Agent：

```text
告警接入
   ↓
故障理解
   ↓
上下文收集
   ↓
自动诊断
   ↓
根因分析
   ↓
修复方案生成
   ↓
风险评估
   ↓
人工审批 / 自动执行
   ↓
结果验证
   ↓
故障总结
```

## 2.2 第一阶段目标

第一阶段暂不强调自动修改生产环境，而重点实现：

1. 告警理解；
2. 监控指标查询；
3. 日志查询；
4. CMDB 查询；
5. 最近变更查询；
6. Runbook 检索；
7. 多步骤故障分析；
8. 根因分析；
9. 修复建议；
10. 完整诊断过程记录。

---

# 3. 系统设计原则

系统遵循以下设计原则。

### 3.1 模型与业务解耦

模型不写死在 Agent 中。

```text
                 ┌──────────────┐
                 │  AIOps Agent │
                 └──────┬───────┘
                        │
                Unified LLM Interface
                        │
                 ┌──────┴───────┐
                 │  LLM Provider │
                 └──────────────┘
```

用户只需要配置：

```text
API Endpoint
API Key
Model Name
```

Agent 本身不关注底层模型来自哪里。

---

### 3.2 Agent 与工具解耦

Agent 不直接操作基础设施，而是通过标准 Tool。

```text
Agent
  ↓
Tool
  ↓
Infrastructure
```

这样可以统一进行：

* 参数校验；
* 权限控制；
* 审计；
* 风险控制；
* 超时控制。

---

### 3.3 读写分离

查询类操作与修改类操作必须分开。

```text
Read Tools
    ↓
自动执行

Write Tools
    ↓
Risk Check
    ↓
Approval
    ↓
Execute
```

---

### 3.4 所有结论必须尽量有证据

Agent 输出不能简单说：

> “服务器 CPU 高是因为程序异常。”

而应该：

```text
结论：
order-service 可能存在版本回归。

证据：
1. CPU 从 40% 持续上升至 94%
2. Java 进程占用 78%
3. Full GC 明显增加
4. 异常时间与最近发布高度重合

置信度：
0.86
```

---

# 4. 总体架构

```text
                         ┌──────────────┐
                         │ 用户 / 告警  │
                         └───────┬──────┘
                                 │
                                 ▼
                         ┌──────────────┐
                         │  API Gateway │
                         └───────┬──────┘
                                 │
                                 ▼
                    ┌────────────────────────┐
                    │      AIOps Agent       │
                    │                        │
                    │      smolagents        │
                    │                        │
                    │  Planner / Reasoner    │
                    │  Tool Executor         │
                    │  Memory                │
                    └───────────┬────────────┘
                                │
             ┌──────────────────┼──────────────────┐
             │                  │                  │
             ▼                  ▼                  ▼
       Monitoring            Logging             CMDB
       Tool                  Tool                Tool
             │                  │                  │
             ▼                  ▼                  ▼
       Prometheus             Loki/ELK          CMDB
             │
             │
             ├───────────────┐
             ▼               ▼
        Network Tools     K8s Tools
             │               │
             ▼               ▼
         网络设备          Kubernetes

             Knowledge
                             │
                             ▼
                       RAG / Vector DB
                             │
                             ▼
                       Policy Engine
                             │
                    ┌────────┴────────┐
                    ▼                 ▼
                 Approval          Execution
                    │                 │
                    └────────┬────────┘
                             ▼
                       Action Gateway
```

---

# 5. 系统模块设计

系统划分为以下模块：

```text
AIOps System
│
├── API Gateway
│
├── Agent Core
│   ├── Planner
│   ├── Reasoner
│   ├── Tool Executor
│   └── Memory
│
├── Tool Layer
│   ├── Monitoring
│   ├── Logging
│   ├── CMDB
│   ├── Network
│   ├── Kubernetes
│   └── Action
│
├── Knowledge Layer
│   ├── Runbook
│   ├── Incident History
│   └── Technical Documents
│
├── Policy Layer
│   ├── Permission
│   ├── Risk
│   └── Approval
│
├── Execution Layer
│   ├── SSH
│   ├── Ansible
│   ├── Kubernetes
│   └── API
│
└── Observability
    ├── Logs
    ├── Metrics
    └── Audit
```

---

# 6. LLM 接入设计

这一部分**不指定模型厂商**。

系统设计统一模型抽象：

```python
class LLMProvider:
    def chat(self, messages, **kwargs):
        pass

    def stream(self, messages, **kwargs):
        pass
```

Agent 只依赖：

```text
LLMProvider
```

不直接依赖：

```text
某具体厂商 SDK
```

推荐配置文件：

```yaml
llm:
  provider: custom
  base_url: ${LLM_BASE_URL}
  api_key: ${LLM_API_KEY}
  model: ${LLM_MODEL}
  temperature: 0.1
  timeout: 120
```

这样以后修改模型只需要修改配置。

---

# 7. Agent 核心设计

推荐使用：

```text
ToolCallingAgent
```

作为核心 Agent。

整体流程：

```text
User / Alert
     ↓
Task Parser
     ↓
Planner
     ↓
Tool Selection
     ↓
Tool Execution
     ↓
Result Analysis
     ↓
Hypothesis
     ↓
Verification
     ↓
Conclusion
```

Agent 不应该一次性调用大量工具。

应该采用：

```text
观察
→ 分析
→ 决定下一步
→ 调工具
→ 再分析
```

形成动态诊断流程。

---

# 8. Incident 对象设计

系统所有故障统一抽象为 Incident。

```json
{
  "incident_id": "INC-20260901-001",
  "title": "订单服务 CPU 高",
  "service": "order-service",
  "severity": "CRITICAL",
  "status": "INVESTIGATING",
  "start_time": "2026-09-01T10:30:00",
  "affected_assets": [],
  "symptoms": [],
  "hypotheses": [],
  "evidence": [],
  "root_cause": null,
  "remediation": [],
  "verification": null,
  "rca": null,
  "failure_code": null
}
```

Incident 是 Agent 整个运行周期的核心上下文。

> V1.5 起：结构化 RCA 存 `rca`（`RCAResult`，唯一权威来源），`root_cause` 作为兼容派生字段，
> `failure_code` 记录"为什么没有形成有效 RCA"的顶层原因。完整定义见 **第 41 章**。

---

# 9. Agent 状态机

```text
NEW
 │
 ▼
TRIAGING
 │
 ▼
INVESTIGATING
 │
 ├──────────────┐
 │              │
 ▼              ▼
ROOT_CAUSE   INSUFFICIENT
_FOUND       _EVIDENCE
 │              │
 ▼              ▼
REMEDIATION   ESCALATED
 │
 ▼
WAITING_APPROVAL
 │
 ▼
EXECUTING
 │
 ▼
VERIFYING
 │
 ├────成功────► RESOLVED
 │
 └────失败────► ESCALATED
```

这样可以防止 Agent 在长流程中丢失状态。

> V1.5 规则：`ROOT_CAUSE_FOUND` **必须**由 Agent 成功提交合法 `RCAResult`（调用 `submit_rca_result`）
> 才会成立；仅调用 `final_answer` 不算根因已定位。无有效提交 → `INSUFFICIENT_EVIDENCE`
> （带 `failure_code`）；LLM 异常 / 超步数 → `ESCALATED`。判定细节见 **第 41 章**。

---

# 10. Tool 体系设计

## 10.1 Monitoring Tool

```text
query_metric
query_metric_range
query_alert
query_host_metrics
```

示例：

```json
{
  "metric": "cpu_usage",
  "target": "server-01",
  "start": "10:00",
  "end": "10:30"
}
```

---

## 10.2 Log Tool

```text
search_logs
get_error_logs
get_logs_by_trace
correlate_logs
```

---

## 10.3 CMDB Tool

```text
get_host
get_service
get_application
get_dependency
get_owner
```

---

## 10.4 Change Tool

```text
get_recent_deployment
get_config_change
get_change_ticket
```

---

## 10.5 Network Tool

```text
ping
traceroute
get_interface_status
get_route_table
get_device_info
```

---

## 10.6 Kubernetes Tool

```text
get_pod
get_pod_logs
get_deployment
get_node
get_events
```

---

# 11. Tool 标准接口

所有 Tool 建议统一：

```text
Tool Request
    ↓
Parameter Validation
    ↓
Permission Check
    ↓
Target Validation
    ↓
Execution
    ↓
Result Normalization
    ↓
Audit Log
    ↓
Tool Response
```

Tool 返回统一结构：

```json
{
  "success": true,
  "tool": "query_metric",
  "timestamp": "2026-09-01T10:35:00Z",
  "data": {},
  "error": null
}
```

这样 Agent 不需要针对不同系统理解几十种不同返回格式。

---

# 12. Tool 分类

建议定义四级权限。

| 类型         | 示例        | Agent权限 |
| ---------- | --------- | ------- |
| READ       | 查指标、查日志   | 自动      |
| LOW_WRITE  | 重启 Pod    | 条件自动    |
| HIGH_WRITE | 服务重启、回滚   | 审批      |
| CRITICAL   | 删除、核心网络修改 | 禁止      |

---

# 13. 风险控制模块

所有 Write Tool 不允许 Agent 直接执行。

流程：

```text
Agent
 ↓
Action Proposal
 ↓
Risk Engine
 ↓
Policy Engine
 ↓
Approval
 ↓
Execution
```

Action Proposal：

```json
{
  "action": "restart_service",
  "target": "order-service",
  "reason": "服务实例异常",
  "risk_level": "MEDIUM"
}
```

---

# 14. 自动修复设计

自动修复分三类。

### A 类：完全自动

```text
查询
健康检查
Ping
日志查询
指标查询
```

### B 类：条件自动

```text
重启 Pod
清理缓存
扩容
```

条件包括：

```text
风险等级允许
目标环境允许
操作次数未超过阈值
存在对应 Runbook
```

### C 类：必须审批

```text
生产回滚
数据库修改
防火墙修改
核心交换机配置
删除资源
```

---

# 15. 根因分析设计

RCA 不直接要求 LLM"一步猜答案"。

采用：

```text
Symptom
 ↓
Evidence Collection
 ↓
Candidate Root Causes
 ↓
Evidence Matching
 ↓
Hypothesis Verification
 ↓
Root Cause Ranking
```

例如：

```text
候选原因：

A. 流量增长
B. 程序异常
C. 数据库慢查询
D. 最近版本发布
```

Agent 分别收集证据，然后进行排序。

> **输出结构以第 41 章为准（V1.5 已定稿）**：RCA 结果用内联 `EvidenceItem`（source/fact），
> 暂不引入证据 ID 注册表；早期草稿的 `evidence_ids` 方案已被替换。

输出（定稿版）：

```json
{
  "root_cause": "deployment_regression",
  "confidence": 0.87,
  "evidence": [
    { "source": "prometheus", "fact": "CPU 从 42% 涨到 95%" },
    { "source": "loki",       "fact": "Full GC 显著增加" },
    { "source": "change",     "fact": "故障前刚发布 v2.3.1" }
  ],
  "hypotheses": ["deployment_regression", "traffic_spike"],
  "recommendations": ["回滚 v2.3.1"],
  "summary": "疑似最近发布引入回归"
}
```

---

# 16. Knowledge Base 设计

知识库主要用于：

```text
Runbook
故障案例
SOP
架构文档
部署文档
网络文档
历史工单
```

检索流程：

```text
Incident
    ↓
Query Rewrite
    ↓
Vector Search
    ↓
Metadata Filter
    ↓
Rerank
    ↓
Knowledge Context
    ↓
Agent
```

知识库不能直接替代实时监控数据。

需要区分：

```text
实时事实
+
历史知识
```

---

# 17. Memory 设计

Memory 分三层。

### Session Memory

保存当前任务上下文：

```text
当前告警
当前目标
当前步骤
当前 Tool Result
```

### Incident Memory

保存当前故障完整过程：

```text
Evidence
Hypothesis
Action
Result
```

### Long-term Memory

保存：

```text
历史故障
最佳实践
Runbook
已验证解决方案
```

---

# 18. 多 Agent 设计

第一版建议：

```text
               Master Agent
                    │
       ┌────────────┼────────────┐
       ▼            ▼            ▼
 Infra Agent    App Agent    Network Agent
```

### Master Agent

负责：

```text
任务拆分
调用专业 Agent
结果汇总
最终决策
```

### Infra Agent

负责：

```text
CPU
Memory
Disk
Process
Host
Kubernetes
```

### App Agent

负责：

```text
Application Logs
APM
Trace
Exception
Release
```

### Network Agent

负责：

```text
Ping
Route
Interface
Packet Loss
Latency
Network Device
```

---

# 19. 为什么采用分层 Agent

不建议：

```text
一个 Agent
+
100 个 Tool
```

因为 Tool 数量过多后容易出现：

* Tool 选择困难；
* Prompt 变长；
* 工具描述冲突；
* 权限边界不清晰。

推荐：

```text
Master Agent
     ↓
Domain Agent
     ↓
Domain Tool
```

形成三级结构。

---

# 20. AIOps 完整工作流

以 CPU 告警为例。

```text
Alert:
CPU > 90%
    ↓
创建 Incident
    ↓
Master Agent
    ↓
判断属于 Infra 问题
    ↓
Infra Agent
    ↓
查询 CPU
    ↓
查询 Memory
    ↓
查询 Process
    ↓
查询日志
    ↓
查询最近变更
    ↓
生成多个 Hypothesis
    ↓
验证 Hypothesis
    ↓
Root Cause
    ↓
查询 Runbook
    ↓
生成 Remediation
    ↓
Risk Evaluation
    ↓
Approval
    ↓
Execution
    ↓
Verification
    ↓
Resolved
```

---

# 21. API 设计

对外提供统一 API。

## 创建 Incident

```http
POST /api/v1/incidents
```

请求：

```json
{
  "title": "CPU usage high",
  "service": "order-service",
  "severity": "critical"
}
```

---

## 启动 Agent

```http
POST /api/v1/incidents/{incident_id}/investigate
```

---

## 获取 Agent 状态

```http
GET /api/v1/incidents/{incident_id}
```

---

## 获取执行过程

```http
GET /api/v1/incidents/{incident_id}/timeline
```

---

## 审批操作

```http
POST /api/v1/actions/{action_id}/approve
```

---

# 22. Agent Timeline

前端建议将 Agent 执行过程以时间线方式展示：

```text
10:30:01
收到 CPU 告警

10:30:03
查询过去 30 分钟 CPU

10:30:05
发现 CPU 持续上升

10:30:08
查询高 CPU 进程

10:30:11
发现 java 进程占用 76%

10:30:15
查询应用日志

10:30:20
发现 Full GC

10:30:22
查询最近部署

10:30:25
发现 5 分钟前发布新版本

10:30:30
形成根因假设
```

这也是 AIOps 系统非常重要的可审计能力。

---

# 23. 数据库设计

核心数据库：

```text
incident
incident_evidence
incident_hypothesis
incident_action
agent_run
tool_call
approval
knowledge_document
```

关系：

```text
Incident
  │
  ├── Evidence
  ├── Hypothesis
  ├── Action
  ├── Tool Call
  └── Agent Run
```

---

# 24. Agent Run 记录

每一次 Agent 执行都应该记录：

```json
{
  "run_id": "RUN-001",
  "incident_id": "INC-001",
  "step": 4,
  "tool": "search_logs",
  "input": {},
  "output": {},
  "duration_ms": 1200,
  "status": "SUCCESS"
}
```

这样可以追踪：

```text
Agent 做了什么
为什么调用这个工具
工具返回什么
最后得出了什么结论
```

---

# 25. 安全设计

AIOps Agent 最大风险不是"答错"，而是：

> **执行了错误的运维操作。**

因此必须建立：

```text
身份认证
 +
RBAC
 +
Tool Permission
 +
Target Permission
 +
Risk Control
 +
Approval
 +
Audit
```

---

# 26. 权限模型

建议：

```text
Admin
Ops
Developer
Viewer
Agent
```

Agent 本身也是一种特殊身份。

例如：

```text
Agent:
READ Monitoring       ✅
READ Logs             ✅
READ CMDB             ✅
Restart Pod           ✅
Production Rollback   ❌
Delete Database       ❌
Network Config        ❌
```

---

# 27. 审计设计

所有敏感操作必须记录：

```text
Who
What
When
Where
Why
Result
```

例如：

```text
Actor:
AIOps-Agent

Action:
restart_pod

Target:
order-service/pod-123

Reason:
CrashLoopBackOff

Approval:
approved by user

Result:
SUCCESS
```

---

# 28. 失败处理

Agent 可能遇到：

```text
Tool Timeout
Tool Error
LLM Error
Network Error
Permission Error
Invalid Result
```

处理机制：

```text
Retry
 ↓
Fallback Tool
 ↓
Reduce Scope
 ↓
Escalate
```

例如 Prometheus 查询失败：

```text
Prometheus
   ↓失败
Node Exporter
   ↓失败
CMDB
   ↓
无法获取实时指标
   ↓
ESCALATE
```

Agent 不允许根据缺失数据自行编造结果。

> V1.5 起，失败顶层归因统一落 `Incident.failure_code`（六码词表 + 状态映射见 **第 41 章**）。
> 注意：工具失败走 `ToolResult(success=False)` 返回给 Agent 继续调查（**不**直接 ESCALATED），
> 只有 LLM 层异常 / 超步数才转 ESCALATED。

---

# 29. Agent 最大步数

需要限制：

```text
max_steps
```

避免出现：

```text
Tool
 ↓
Tool
 ↓
Tool
 ↓
Tool
 ↓
无限循环
```

同时增加：

```text
Tool Timeout
Action Timeout
Incident Timeout
```

---

# 30. 防止 Agent 循环

例如：

```text
restart Pod
 ↓
仍然异常
 ↓
restart Pod
 ↓
仍然异常
 ↓
restart Pod
```

应该设置：

```text
同类操作最大次数 = N
```

超过后：

```text
ESCALATE
```

而不是继续重试。

---

# 31. 观测体系

Agent 自身也要被监控。

建议采集：

```text
Agent Latency
Tool Latency
Tool Failure
LLM Request
LLM Error
Token Usage
Incident Duration
Action Count
```

整体：

```text
Agent
 ↓
OpenTelemetry
 ↓
Prometheus / Logs
 ↓
Grafana
```

---

# 32. 测试设计

测试分为四层。

### 单元测试

测试：

```text
Tool
Policy
Risk Engine
Parser
Data Model
```

### 集成测试

测试：

```text
Agent + Tool
Agent + Monitoring
Agent + Logs
```

### 场景测试

模拟：

```text
CPU 高
内存高
磁盘满
Pod CrashLoop
接口 Down
网络延迟
服务不可用
数据库慢
```

### 安全测试

重点测试：

```text
越权操作
危险参数
错误目标
重复执行
Prompt Injection
恶意日志
```

---

# 33. MVP 实现范围

第一版建议只做：

```text
smolagents
+
LLM Provider
+
FastAPI
+
Prometheus
+
Loki
+
CMDB
+
RAG
```

实现：

```text
告警
 ↓
Agent
 ↓
查询指标
 ↓
查询日志
 ↓
查询变更
 ↓
RCA
 ↓
修复建议
```

**暂时不执行生产环境写操作。**

---

# 34. V2 实现范围

增加：

```text
Kubernetes
Network
Action Gateway
Approval
Audit
```

形成：

```text
Detect
→ Diagnose
→ Recommend
→ Approve
→ Execute
→ Verify
```

---

# 35. V3 实现范围

进一步增加：

```text
Multi-Agent
MCP
Auto Remediation
Incident Learning
Predictive AIOps
```

形成：

```text
             AIOps Platform
                    │
        ┌───────────┴───────────┐
        ▼                       ▼
   Reactive AIOps          Predictive AIOps
        │                       │
 Detect / Diagnose          Anomaly
 Remediate                  Prediction
        │                       │
        └──────────┬────────────┘
                   ▼
              Self-Healing
```

---

# 36. 推荐项目目录

```text
aiops-agent/
│
├── app/
│   ├── main.py
│   ├── config.py
│   │
│   ├── agent/
│   │   ├── master.py
│   │   ├── infra.py
│   │   ├── application.py
│   │   └── network.py
│   │
│   ├── tools/
│   │   ├── monitoring.py
│   │   ├── logging.py
│   │   ├── cmdb.py
│   │   ├── network.py
│   │   ├── kubernetes.py
│   │   └── actions.py
│   │
│   ├── llm/
│   │   ├── base.py
│   │   └── provider.py
│   │
│   ├── knowledge/
│   │   ├── retriever.py
│   │   └── embeddings.py
│   │
│   ├── policy/
│   │   ├── permission.py
│   │   └── risk.py
│   │
│   ├── incident/
│   │   ├── model.py
│   │   ├── state.py
│   │   └── service.py
│   │
│   └── api/
│       ├── incidents.py
│       ├── actions.py
│       └── approval.py
│
├── tests/
├── prompts/
├── docker/
├── requirements.txt
└── README.md
```

---

# 37. 项目核心调用关系

最核心的调用链设计为：

```text
                   ┌───────────┐
                   │  FastAPI  │
                   └─────┬─────┘
                         │
                         ▼
                  ┌──────────────┐
                  │    Agent     │
                  │ smolagents   │
                  └──────┬───────┘
                         │
              ┌──────────┼──────────┐
              ▼          ▼          ▼
             LLM       Tools      Memory
              │          │
              │          ├── Monitoring
              │          ├── Logs
              │          ├── CMDB
              │          ├── Network
              │          └── K8s
              │
              ▼
         Reason / Plan
              │
              ▼
          Conclusion
              │
              ▼
        Policy / Risk
              │
              ▼
        Action / Approval
```

---

# 38. 最终设计定位

这个项目不是：

```text
聊天机器人
```

也不是：

```text
LLM + SSH
```

而是：

```text
              AIOps Agent
                   │
    ┌──────────────┼───────────────┐
    ▼              ▼               ▼
 Intelligence    Knowledge       Automation
    │              │               │
   LLM            RAG             Tools
    │              │               │
    └──────────────┼───────────────┘
                   │
                 Policy
                   │
                Security
                   │
                 Audit
```

最终形成：

> **以 smolagents 为 Agent 编排核心，以监控、日志、CMDB、网络、Kubernetes 等工具为执行基础，以知识库为运维知识来源，以策略与审批机制保证安全，实现故障发现、诊断、根因分析、处置和验证的 AIOps 智能运维系统。**

### 38.1 与平台类产品（如 Keep）的定位区隔（定稿）

项目定位为 **Evidence-driven AIOps Diagnostic Agent（Agent-first）**，而不是"小型告警管理平台（Platform-first）"：

| | Keep（keephq/keep） | 本项目 |
|---|---|---|
| 定位 | 完整 AIOps / 告警治理平台 | Agent-native Incident Investigation / RCA 引擎 |
| 核心抽象 | Provider / Workflow / Alert / Incident | Agent / Tool / Evidence / Hypothesis / RCA |
| 告警治理（去重/关联/富化） | 强 | 不做，让给平台层 |
| 差异化点 | 平台广度 | 证据→假设→验证→RCA 的闭环深度 |

**不追赶** Keep 的功能数量（Provider 生态、Workflow、UI、Dashboard）。
**聚焦** Agent 诊断能力，并把 RCA 输出**结构化、机器可读**（见第 41 章）。

**演进关系**：未来本项目可作为 Keep 等平台通过 HTTP Provider 调用的**独立 RCA 子系统**——
平台负责告警接入/治理/Incident 编排，本项目负责 Incident Investigation / Evidence / RCA，结果回写平台。

---

## 39. 重点设计建议

如果这是准备做成**毕业设计、课程项目或者实际项目**，技术亮点建议集中在五个地方：

```text
① Agent 动态诊断流程
      ↓
② 多源运维数据关联
      ↓
③ Evidence-based RCA
      ↓
④ Risk-aware Auto Remediation
      ↓
⑤ Incident 闭环与经验沉淀
```

模型 API 单独作为可插拔模块，模型地址、API Key、模型名都由配置决定，设计文档不绑定任何具体厂商。

---

# 40. RAG 知识检索（已实现）

在第 16 章知识库检索流程基础上，MVP 落地最小可用语义检索：

```text
Query → Embed → Vector Search(top-k) → Agent
```

暂未实现 Query Rewrite / Metadata Filter / Rerank（V2 补）。

## 组件

```text
app/knowledge/
├── chunker.py     markdown 按标题切块，超长硬切到 500 字符
├── embeddings.py  fastembed 封装，BAAI/bge-small-zh-v1.5（512 维，中文优化，懒加载）
└── retriever.py   chromadb 持久化（cosine 距离），index(upsert) + search(top-k)
```

## 数据流与降级

```text
search_runbook(query)
   ├─ RAG 可用：读 runbooks/*.md → 切块 → 嵌入 → 写 chromadb → 语义 top-k
   └─ 任一步失败（依赖缺失/模型不可达/网络异常）→ 降级关键词子串搜索，不 raise
```

配置：`rag_enabled`（默认开）、`rag_top_k`（默认 3），可在 `.env` 调整。

## 关键实现点

- chromadb 拒绝 numpy 类型：fastembed 输出 float32，须 `v.tolist()` 转 Python float。
- fastembed 用 loguru 打日志；境内 HF 源不可达时回退 GCS 缓存并记一条 ERROR，
  用 `logger.disable("fastembed")` 压掉预期噪音。
- 模型下载：`HF_ENDPOINT=https://hf-mirror.com` + `HF_HUB_DISABLE_XET=1`
  （新版 huggingface_hub 默认 Xet 协议在境内连不通）；模型缓存本地后离线可用。
- chromadb 持久化在 `.data/chroma`（gitignore），进程内复用索引。

## 测试

单元测试不下载模型：chunker 切块边界、retriever 用 fake 向量验证 top-k 排序/空库/嵌入失败、
KnowledgeTool 验证 RAG 失败降级关键词。真实模型检索用冒烟脚本单独验证（不跑在 CI）。

---

# 41. 结构化 RCA 设计（V1.5，已定稿）

> 定位结论（与 Keep / keephq/keep 对比后）：本项目不是"小型 Keep/告警平台"，而是
> **Evidence-driven AIOps Diagnostic Agent**，未来可作为独立 RCA 子系统被 Keep 等平台
> 通过 HTTP Provider 调用。因此 RCA 输出必须**机器可读**，不能只是一段自然语言总结。

V1.5 核心改动：把 `root_cause`（字符串）升级为结构化 `RCAResult`
（含 confidence / evidence / hypotheses）。RCA 结果经**两条通道**到达：首选 `submit_rca_result` 工具，
兜底为 `final_answer` 中 `<rca_result>` JSON；`investigate()` 统一校验、落库并决定最终状态。

> **真实模型验证（2026-09-02 冒烟）**：deepseek-v4-flash 在此 harness 下能正常调用查询类工具，
> 但**不可靠调用带复杂嵌套参数的终态工具**（submit_rca_result），且易过度调查直到超步数；
> 它倾向用 final 文本"写"出结构化结果（且 evidence 常写成字符串数组、不合 schema）。
> 因此定稿为混合收尾：不依赖模型工具行为，兜底通道 + 同一 schema 校验是鲁棒性的关键。

## 41.1 数据模型

```python
class EvidenceItem(BaseModel):
    source: str   # 证据来源，如 prometheus / loki / cmdb / runbook
    fact: str     # 证据事实描述

class RCAResult(BaseModel):
    root_cause: str                                      # 必填，根因结论
    confidence: float = Field(ge=0.0, le=1.0)            # 必填，0~1
    evidence: list[EvidenceItem] = Field(min_length=1)   # 必填，至少 1 条
    hypotheses: list[str] = Field(default_factory=list)  # 可选
    recommendations: list[str] = Field(default_factory=list)  # 可选
    summary: str | None = None                           # 可选，展示用
```

`Incident` 新增字段，`root_cause` 保留作兼容：

```python
rca: RCAResult | None = None        # 唯一权威来源（authoritative）
rca_source: Literal["tool", "final_answer"] | None = None  # 结果来源通道
root_cause: str | None = None       # legacy：写入时从 rca.root_cause 派生
failure_code: str | None = None     # 最终未形成有效 RCA 时的顶层失败原因
```

原则：`rca` 是唯一真实数据源，`root_cause` 是派生兼容字段，两者永不存不同内容。
`rca_source` 用于统计两条通道的实际命中率（决定未来是否值得重做工具路线）。

## 41.2 failure_code 词表（本轮锁定六码）

| code | 含义 | 对应状态 |
|---|---|---|
| `NO_SUBMISSION` | Agent 从未调用 submit_rca_result | INSUFFICIENT_EVIDENCE |
| `MISSING_EVIDENCE` | RCA 缺少有效结论或必要证据（v1 同时涵盖结构性违例，暂不引入 INVALID_RCA） | INSUFFICIENT_EVIDENCE |
| `LOW_CONFIDENCE` | confidence 缺失/非数字/越界，无法作为合法置信度 | INSUFFICIENT_EVIDENCE |
| `LLM_ERROR` | LLM 调用异常 | ESCALATED |
| `TOOL_ERROR` | Tool 执行出现真实系统异常（v1 保留，不主动触发） | ESCALATED |
| `MAX_STEPS` | Agent 达到最大步数仍未完成 | ESCALATED |

语义澄清：

- `LOW_CONFIDENCE` 表示 confidence **无法作为合法可信度使用**，不是"系统认定置信度太低"。
  V1 **不设业务阈值**——`confidence=0.2` 是合法模型判断，直接 ROOT_CAUSE_FOUND；
  未来若需"低置信度不算定案"，再加 `rca.min_confidence` 配置。
- `MISSING_EVIDENCE` 在 v1 覆盖所有非 confidence 类结构违例（root_cause 空 / evidence 空 /
  item 缺 source/fact），不引入第七个码。

## 41.3 SubmitRCATool（绑定本次 Run 的工具）

不属于只读工具工厂 `build_tools()`；在 `investigate()` 内按 `(svc, incident_id)` 动态实例化，
生命周期与一次调查严格一致。**工具不写 Incident**，只做校验 + 存 holder + 返回结果给 Agent。

```python
class SubmitRCATool:
    submit_attempted: bool = False           # 是否调用过 submit_rca_result
    rca_result: RCAResult | None = None      # 最近一次成功校验的 RCA（成功即锁存）
    validation_error: str | None = None      # 最近一次校验失败的具体错误
    last_validation_code: str | None = None  # 最近一次失败类别：LOW_CONFIDENCE / MISSING_EVIDENCE
```

校验规则（失败返回 ToolResult(success=False) 供 Agent 重试，不 raise）：

| 情形 | 结果 |
|---|---|
| 结构合法 | rca_result 锁存，attempted=True，返回成功 |
| confidence 缺失/非数字/越界 | last_validation_code=LOW_CONFIDENCE，返回失败 |
| root_cause 空 / evidence 空 / item 缺字段 | last_validation_code=MISSING_EVIDENCE，返回失败 |

关键规则：

> **`rca_result` 只被成功提交更新；失败提交永不覆盖已有成功结果。**

多次提交时，最后一次**成功**提交为准；成功后若再失败，只更新 validation_error / code，不清空已锁存的 rca_result。

## 41.4 混合收尾：两条 RCA 结果通道

`submit_rca_result` 是**首选**结构化提交通道；`final_answer` 除了结束信号，还是**结构化提交兜底通道**：

```text
submit_rca_result（工具）
    = 首选结构化提交通道

final_answer + <rca_result> JSON
    = 人类可读收尾 + 兜底结构化通道
```

兜底只在 `final_answer` 文本的 `<rca_result>...</rca_result>` 标签内提取 JSON（不猜自然语言里的任意 JSON），
并经与工具**同一套** `RCAResult` schema 校验。兜底不降低标准，只是改变输入通道。

```text
RCA precedence:
1. 有效的 submit_rca_result（工具）   → rca_source="tool"
2. 有效的 final_answer <rca_result>   → rca_source="final_answer"
3. failure_code
```

任何有效 RCAResult 产生后即锁定，后续文本/错误不覆盖不降级；`final_answer` 中无合法 RCA JSON ≠ 失败，
只有两条通道都没有有效 RCAResult 时才进入 failure state。

## 41.5 investigate() 流程（单一事务边界）

```text
investigate()
 ├─ 状态机推进到 INVESTIGATING
 ├─ 创建 SubmitRCATool(svc, incident_id)，加入本轮工具列表
 ├─ adapt_tools → build_agent → agent.run(prompt, return_full_result=True)
 ├─ 通道1：工具提交（submit_tool.rca_result）
 ├─ 通道2：final 文本 <rca_result>（仅 run 正常结束/超步数时有文本）
 └─ 一次性写 Incident：rca / rca_source / root_cause / status / failure_code
```

最终状态判定优先级：

```text
submit_tool.rca_result 有效（通道1）
   → ROOT_CAUSE_FOUND / rca_source="tool" / failure_code=None
     （工具成功即锁定，final JSON / 后续错误不覆盖）

否则 final <rca_result> 解析有效（通道2，run 未抛异常）
   → ROOT_CAUSE_FOUND / rca_source="final_answer" / failure_code=None
     （工具失败不阻断兜底）

否则 agent.run 抛异常
   → ESCALATED / LLM_ERROR

否则无有效 RCA 且 RunResult.state == "max_steps_error"
   → ESCALATED / MAX_STEPS

否则（正常结束，两通道皆无效）：
   final 区块存在但非法        → INSUFFICIENT_EVIDENCE / final_code（LOW_CONFIDENCE 或 MISSING_EVIDENCE）
   工具调用过但校验失败        → INSUFFICIENT_EVIDENCE / last_validation_code 或 MISSING_EVIDENCE
   两者都未尝试               → INSUFFICIENT_EVIDENCE / NO_SUBMISSION
```

`ToolResult(success=False)` 是**正常工具返回**（Agent 看到"监控查询失败"可换证据继续调查），不触发 ESCALATED 分支。

## 41.6 investigate() 返回值

保持兼容：返回 `final_answer` 文本（给 API/前端展示），结构化结果一律从 `incident.rca` 读取。
API 层 `{"conclusion": ..., "incident": ...}` 结构不变。

## 41.7 锁定的设计决策清单

1. LOW_CONFIDENCE：V1 只做 schema 校验，不设业务置信度阈值。
2. 结构性违例统一归 MISSING_EVIDENCE，不新增 INVALID_RCA。
3. SubmitRCATool 不写 Incident；investigate() 作为事务边界统一落 Incident。
4. investigate() 返回 conclusion 文本；结构化从 incident.rca 读。
5. rca_result 锁存：成功提交后不被后续失败覆盖；最后一次成功提交为准。
6. **混合收尾**：RCA 优先级 tool > final_answer `<rca_result>` > failure_code；两条通道共用同一 schema 校验；
   工具成功即锁定，final JSON 不覆盖；工具失败不阻断 final 兜底；无任何有效 RCAResult 才进 failure state。
7. TOOL_ERROR 作为状态机契约保留，V1 不主动制造（工具失败走 ToolResult(success=False)）。
8. `Incident.evidence`（legacy list[str]，调查过程原始证据摘要）本轮保留不动；
   `RCAResult.evidence`（结构化、支撑 RCA 结论的证据）职责不同。
9. `Incident.rca_source` 记录结果来源通道，用于统计工具/兜底真实命中率。

**V1.6 待做（不在本轮）**：
- 调查收敛机制（Evidence/Investigation Budget、Convergence Criteria）——真实模型冒烟暴露
  "只要还有没查过的指标就继续查、直到 max_steps"的过度调查问题。
- **confidence 校验一致性（V1.6 P1，已修）**：两条通道对 confidence 的校验曾不一致——工具路径拒绝
  字符串/布尔（`"0.8"`、`True`），final 路径经 Pydantic v2 lax 把 `"0.8"` coerce 成 0.8、`True` coerce 成 1.0。
  已统一：RCAResult.confidence 加 `mode="before"` field_validator 只接受 int/float、拒绝字符串/布尔，
  两通道同一 schema 语义；真实冒烟复验 PASS（模型实际输出数值型 confidence，无回归）。
- **Tool Adapter 暴露白名单（V1.6 P2，已修）**：各工具类声明 `exposed_methods = [...]`，
  `_wrap_plain_tool` 优先按白名单包装（未声明的普通对象才回退 dir() 扫描兼容）。
  工具类后续加的 `refresh_cache()` 等辅助方法不再自动暴露给 Agent；有回归测试守护。

## 41.8 对应实现位置（已实现，提交 06c3379 / 15b01d4 后续）

```text
app/incident/model.py       EvidenceItem / RCAResult；Incident 增 rca / rca_source / failure_code
app/agent/submit_tool.py    SubmitRCATool（绑定 svc+incident_id，holder，工具通道）
app/agent/final_parse.py    extract_rca_result()：<rca_result> 区块提取 + RCAResult schema 校验（兜底通道）
app/agent/agent.py          investigate() 混合收尾：工具/兜底两通道 + RunResult 解码 + 统一落 Incident
prompts/diagnose.txt        指导两种收尾方式与严格 JSON 格式
scripts/smoke_real_llm.py   真实 LLM 冒烟验收（手工运行，不入 CI）
scripts/experiment_convergence.py   V1.6 收敛 A/B 实验（Baseline vs Convergence，真实 LLM）
tests/...                   rca 模型 / submit 工具 / final 解析 / investigate 状态机 / E2E 场景
```

---

# 42. Investigation Convergence（V1.6，实验定稿）

> 本章为**有真实模型实验依据**的设计：先跑 A/B 收敛实验（`scripts/experiment_convergence.py`），
> 据实定稿，不是先拍脑袋。

## 42.1 问题定义

V1.5 真实冒烟暴露：deepseek-v4-flash 在 ToolCallingAgent 里**过度调查、不收敛**——
"只要还有一个没查过的指标就继续查"，一直查到 `max_steps`，不主动收尾。

```text
CPU 高 → 查 CPU → 查 QPS → 查 error → 查 load → 查 GC → 查 thread → … → MAX_STEPS
```

基线（A/B 实验 Baseline 组，2026-09-02，真实 DeepSeek）：

```text
read_calls=8   generate=9   submit 未调   rca=无   status=ESCALATED/MAX_STEPS
```

## 42.2 实验结论（决定性）

只改 Prompt（不动状态机/不做强制注入/不改工具集），加入两样东西：

```text
调查预算    ：最多 4 次只读工具调用
收敛判据    ：已有 ≥2 条独立证据且来自 ≥2 个来源 → 立即收尾提交 RCA
```

Convergence 组结果：

```text
read_calls=2   generate=5   submit 工具调用成功   rca_source=tool
rca=有效       status=ROOT_CAUSE_FOUND
```

**结论：纯 Prompt 层的预算 + 收敛判据足以让模型在预算内收敛并形成合法 RCA**
（该固定场景下）。**不需要强制收尾注入，也不需要工具集裁剪。**
收敛路径上模型甚至成功调用了 `submit_rca_result`（工具通道命中）。

## 42.3 收敛判据（Convergence Criteria）

语义层规则（当前由 Prompt 表述）：

> 已有 ≥2 条**独立**证据、且来自 ≥2 个**不同来源**时，必须停止调查并收尾。

- "独立"：证据来自不同的工具调用/观察，不是同一指标的不同说法。
- "来源"：prometheus / loki / cmdb / runbook / 变更 等不同数据域。

后续若需硬约束（模型纪律不足时），可把判据移到代码层：记录证据后由 investigate 判定。

## 42.4 调查预算（Investigation Budget）

- 只读工具调用上限 `max_read_tools`：实验值 4。
- `max_steps`（模型层总步数上限）保留作为兜底安全网，不替代只读预算。
- 已落地（提交 1a088a4）：写入诊断 prompt（"你最多只能调用 N 次只读工具"），
  Settings 增 `agent_max_read_tools`（默认 4，env `AGENT_MAX_READ_TOOLS`）+ prompt 变量注入。

> **软预算澄清**：V1.6 当前实现为 **Prompt-level（软预算）**——由模型自主遵守，
> 代码层**没有**独立的只读调用计数器，也不在超预算时阻止工具执行；`agent.run()` 仍只受
> `agent_max_steps` 总步数限制。准确表述是"系统要求 Agent 最多调用 N 次只读工具并在固定场景
> 验证模型遵守"，**不是**"系统保证最多只能调用 N 次"。未来若模型纪律在多场景被证伪，
> 再研究 Code-enforced Read Budget（工具中间件/计数器限流），不提前硬限流。

实验原则：**一次只改一个变量**。预算/判据若分阶段，先只加一个再观察，
避免"到底是哪个因素让模型收敛"不可归因。

## 42.5 Tool / Final 收尾策略

沿用第 41 章混合收尾（submit 工具首选 + final `<rca_result>` 兜底），
收敛 prompt 同时提醒两条通道。V1.6 不改变收尾机制本身。

## 42.6 失败路径

```text
预算内收敛 + 有效 RCA  → ROOT_CAUSE_FOUND
预算内收敛但无有效 RCA → INSUFFICIENT_EVIDENCE（归因同 §41.5）
预算用尽仍未收敛       → ESCALATED / MAX_STEPS（或按 §41 归因）
```

注意：模型"查满 max_steps 仍不提交"是比"最后 JSON 写坏"更上层的失败原因，
超步数保持 ESCALATED/MAX_STEPS 语义（V1.5 已定，不改）。

## 42.7 可观测指标

每次冒烟/实验记录：

```text
step/generate 次数    read_tool_calls    unique_tools
submit_tool_called    rca_source         rca_valid
status                failure_code
```

`scripts/experiment_convergence.py` 为 A/B 实验 harness；验收优先级：
预算内收敛 > RCA 合法 > tool/final 路径。

## 42.8 后续强制收尾方案（如需要）

当前单场景实验证明 Prompt 收敛足够，**暂不设计强制注入**。
若后续更复杂/更长尾场景下模型仍不收敛，再研究：

```text
smolagents mid-run 注入 / step hook（需核实版本能力）
  ↓
Budget + Convergence + Forced Stop 实验 2
  ↓
据实把强制收尾补进 V1.6
```

## 42.9 V1.6 落地项 / 后续验证项

**已落地（提交 1a088a4）**
1. `prompts/diagnose.txt` + 默认 prompt 加入调查预算 + 收敛判据（生产 prompt 固化）。
2. Settings 增 `agent_max_read_tools`（默认 4，env `AGENT_MAX_READ_TOOLS`），prompt 变量注入。
   （真实冒烟复验 PASS：模型按预期 tool 通道提交，无过度调查；全量 236 passed）

**后续验证 / 待办**
3. 扩场景复验（`scripts/experiment_convergence.py`，真实 LLM，工具层计数）**已做**：
   - `multi_source_mem_gc`（监控+日志双来源）：generate=3，read_calls=2（query_metric+search_logs），
     rca_source=tool，ROOT_CAUSE_FOUND
   - `release_regression`（监控+日志+runbook，发布回归）：generate=4，read_calls=3，
     rca_source=tool，ROOT_CAUSE_FOUND
   结论：收敛 prompt 在多来源/日志场景泛化成立，预算内收敛且走工具通道。
   剩余：接入真实 Prometheus/Loki/CMDB/变更工具后再复验（当前为 fixture）。
4. P1：Tool/Final confidence 严格校验统一 —— **已做**（RCAResult confidence `mode="before"` validator，
   见 §41.7；真实冒烟无回归）。
5. P2：Tool Adapter 显式 `exposed_methods` —— **已做**（各工具类白名单 + 适配器优先白名单，见 §41.7）。
