# 基于 smolagents 的 AIOps Agent 系统设计文档

**文档版本：** V1.0
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
  "verification": null
}
```

Incident 是 Agent 整个运行周期的核心上下文。

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

输出：

```json
{
  "root_cause": "deployment_regression",
  "confidence": 0.87,
  "evidence_ids": [
    "E001",
    "E004",
    "E006"
  ]
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
