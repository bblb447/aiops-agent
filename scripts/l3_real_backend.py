"""L3 Real LLM + Real Backend 观测脚本（spec docs/design.md §46）。

用法（backend 生命周期手动，脚本不隐式管理）：
    PYTHONIOENCODING=utf-8 python tests/integration/backend.py up
    PYTHONIOENCODING=utf-8 python scripts/l3_real_backend.py [--expect ...] [scene...]
    python tests/integration/backend.py down

    --trace-out PATH：额外写结构化 JSON trace（默认不写）。
    exit code 追加：preflight(L3-1) 失败=4。

判定纯函数在本文件顶部（可被 tests/scripts/test_l3_gate.py 作 L0 单测）；
真实 LLM 的 run 层（Task 2）与报告/main（Task 3）在本函数后追加。
exit code：缺 .env LLM key=2；backend 不可达=3；默认只观测=0（除非未捕获异常/系统错误）；
--expect 显式不满足=1。
"""
import json
import os
import re
import sys
from pathlib import Path

# 本地后端直连：绕过 Windows 系统代理（Clash 注册表代理会劫持 127.0.0.1 → HTTP 502）。
# 必须在任何 httpx 请求发生前设置。
os.environ["NO_PROXY"] = ",".join(filter(None, [os.environ.get("NO_PROXY", ""), "127.0.0.1", "localhost"]))

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

CPU_FALSE_POSITIVE_MARKERS = ("cpu usage above", "cpu saturation", "high cpu",
                              "cpu 使用率", "cpu 高", "cpu 异常", "cpu 持续高", "cpu 占用过高")

# 局部否定守卫：marker 命中处紧邻前文（有限窗口内）出现否定词 → 该次命中不算虚构。
# 只查 marker 前一个局部窗口（非整句），避免"没有观察到 CPU 高负载，但后续 CPU 占用过高"
# 这种"先否定后肯定"的句子被整句放行。纯规则，无需 NLP/第二个 LLM judge。
CPU_NEGATION_WINDOW = 12
CPU_NEGATION_MARKERS = ("并未", "并没有", "没有", "不存在", "未出现", "未检测到",
                        "未", "无", "没", "not", "no", "never")


def _locally_negated(text: str, marker_start: int, marker_len: int) -> bool:
    pre = text[max(0, marker_start - CPU_NEGATION_WINDOW):marker_start]
    return any(n in pre for n in CPU_NEGATION_MARKERS)


def budget_compliance(read_total: int, budget: int) -> bool:
    return read_total <= budget


def a_no_false_positive_cpu(rca) -> bool:
    """A 负向判据：提交的 RCA（若有）不得虚构 CPU 异常证据。无 RCA 视为无虚构。

    对每条证据扫描所有 marker 的全部出现位置；仅当某次命中前方局部窗口无否定词时
    才判为虚构（真命中否定句如"并未出现 CPU 高负载"不误报）。"""
    if rca is None:
        return True
    for e in getattr(rca, "evidence", []) or []:
        text = f"{getattr(e, 'fact', '')} {getattr(e, 'source', '')}".lower()
        for m in CPU_FALSE_POSITIVE_MARKERS:
            start = 0
            while True:
                i = text.find(m, start)
                if i < 0:
                    break
                if not _locally_negated(text, i, len(m)):
                    return False
                start = i + len(m)
    return True


def scene_success(name: str, obs: dict) -> tuple[bool, str]:
    """按 §46.5 场景语义判单场景成功。obs 需含：read_tool_calls/budget/rca_valid/
    evidence_sources/status/submit_attempted/rca_source/rca/system_error。

    A（负向控制）= 预算内 + 无虚构 CPU 异常 + 不因系统错误失败 + 最终 INSUFFICIENT_EVIDENCE
      （V1 状态机预期终态；负向控制不允许臆造任何根因，故 ROOT_CAUSE_FOUND 即使无 CPU 声称也不通过）；
    B（正向多源）= 预算内 + 合法 RCA + ROOT_CAUSE_FOUND + evidence_sources == {prometheus, loki}；
    C（Hybrid 兜底）= 预算内 + submit_attempted 为 False + 合法 RCA + final_answer + ROOT_CAUSE_FOUND。
    INSUFFICIENT_EVIDENCE 显式通过仅适用于 A。
    """
    if name == "real_loki_contract":
        # #11 L3（spec §10）：走专用判据，绕开 A/B/C 共享的 system_error / budget 前置
        # —— 该场景二者均为 observation（spec §5.1），且 A/B/C 语义保持不变。
        return loki_contract_success(obs)
    if obs.get("system_error"):
        return False, "system_error"
    if not budget_compliance(obs.get("read_tool_calls", 0), obs.get("budget", 4)):
        return False, "budget exceeded"
    if name == "cpu_alert_negative_control":
        if not a_no_false_positive_cpu(obs.get("rca")):
            return False, "false positive cpu evidence"
        # V1.7（§47）：A 负向正确终态 = verdict NO_ANOMALY / status RESOLVED，而非硬塞 INSUFFICIENT_EVIDENCE。
        if obs.get("verdict") != "NO_ANOMALY":
            return False, f"expected verdict NO_ANOMALY; got {obs.get('verdict')}"
        return True, "negative control ok (no anomaly)"
    if name == "error_spike_multisource":
        if not (obs.get("rca_valid") and obs.get("status") == "ROOT_CAUSE_FOUND"
                and obs.get("evidence_sources") == {"prometheus", "loki"}):
            return False, f"need valid rca + ROOT_CAUSE_FOUND + sources {{prom,loki}}; got {obs.get('evidence_sources')}"
        return True, "multisource rca ok"
    if name == "hybrid_fallback_observation":
        if not (obs.get("submit_attempted") is False and obs.get("rca_valid")
                and obs.get("rca_source") == "final_answer"
                and obs.get("status") == "ROOT_CAUSE_FOUND"):
            return False, "need no-submit + valid rca + final_answer + ROOT_CAUSE_FOUND"
        return True, "fallback rca ok"
    return False, f"unknown scene {name}"


def evaluate_expect(expects: set[str], results: list[dict]) -> bool:
    """--expect 语义（§46.6 + #11 L3 spec §9）。

    results 每项含 name/success/rca_source/submit_attempted/budget_compliance/loki_contract_ok。
    real_loki_contract 是专项场景：既有的 rca/convergence/tool/fallback/all **一律不把它算进去**
    （避免新增场景悄悄改变既有门禁语义）；它只由 `loki_contract` 验证。
    """
    expects = set(expects)
    if not results or not expects:
        return False
    legacy = [r for r in results if r.get("name") != "real_loki_contract"]
    if "convergence" in expects or "all" in expects:
        if not all(r.get("budget_compliance") for r in legacy):
            return False
    if "rca" in expects or "all" in expects:
        if not all(r.get("success") for r in legacy):
            return False
    if "tool" in expects or "all" in expects:
        bc = [r for r in legacy
              if r.get("name") in ("error_spike_multisource", "hybrid_fallback_observation")]
        if not any(r.get("rca_source") == "tool" for r in bc):
            return False
    if "fallback" in expects or "all" in expects:
        c = [r for r in legacy if r.get("name") == "hybrid_fallback_observation"]
        if not (c and c[0].get("rca_source") == "final_answer"
                and c[0].get("submit_attempted") is False):
            return False
    if "loki_contract" in expects:
        lc = [r for r in results if r.get("name") == "real_loki_contract"]
        if not (lc and all(r.get("loki_contract_ok") for r in lc)):
            return False
    return True


# ===== #11 L3 Loki contract 判定（spec docs/superpowers/specs/2026-09-22-l3-loki-contract-design.md）=====

_LOKI_HTTP_RE = re.compile(r"HTTP (\d{3})")
_TOKEN_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*|\d+")


def _tokens(text: str) -> set[str]:
    """词元集合：英文/数字片段、小写化、丢弃单字符。仅供启发式相关性使用。"""
    return {t.lower() for t in _TOKEN_RE.findall(text or "") if len(t) >= 2}


def _source_value(item) -> str:
    """EvidenceItem.source 是 EvidenceSource 枚举成员；取 canonical value。"""
    s = getattr(item, "source", None)
    return getattr(s, "value", s)


def loki_preflight_ok(description: str, label_keys) -> tuple[bool, str]:
    """L3-1（preflight，确定性，不调模型）：model-visible description 必须暴露配置声明的
    label contract 与通用 LogQL 形态指引。失败即 fail-fast，不消耗 token（spec §5.2）。"""
    keys = list(label_keys or [])
    if not keys:
        return False, 'preflight: LOKI_LABEL_KEYS 未配置（L3 验证环境需声明 ["app"]）'
    for k in keys:
        if k not in description:
            return False, f"preflight: description 缺少 label key {k!r}"
    first = keys[0]
    if f'{{{first}="<value>"}}' not in description:
        return False, f'preflight: description 缺少推荐 selector 形态 {{{first}="<value>"}}'
    if "合法 LogQL" not in description:
        return False, "preflight: description 缺少 LogQL 形态指引"
    return True, "preflight ok"


def _successful_loki_calls(obs: dict) -> list[dict]:
    """Loki 观察集合的唯一事实源：仅成功（被 Loki 接受）的调用。
    gate 与 classifier 必须共用它，不得各自重新解释 obs['loki_calls']（spec §6）。"""
    return [c for c in (obs.get("loki_calls") or []) if c.get("success")]


def loki_contract_success(obs: dict) -> tuple[bool, str]:
    """#11 L3 gate（spec §5.2）：只判三条确定性事实。
    预算 / system_error / 模型结论 / 调用顺序 / 调用次数一律不参与 —— 它们是 observation（§5.1）。"""
    ok = _successful_loki_calls(obs)
    if not ok:
        return False, "L3-2: no successful search_logs call"
    if not any((c.get("result_count") or 0) > 0 for c in ok):
        return False, "L3-3: no non-empty real loki result"
    if "loki" not in (obs.get("evidence_sources") or set()):
        return False, "L3-4: no loki evidence in final RCA"
    return True, "loki contract ok"


def classify_loki_failure(obs: dict) -> str | None:
    """失败归类（spec §6，报告标签，非 gate）。

    **仅当 Loki contract invariant 未满足时返回 F1–F4**；若 contract 已满足，返回 `None`
    —— 即使此时超预算。budget / max_steps **不是 failure class**，由独立 observation 字段
    `budget_exhausted` 承载（用户 2026-09-22 冻结：F5 不是 Loki contract failure）。"""
    if not obs.get("preflight_ok", True):
        return "F1_contract_not_exposed"
    calls = obs.get("loki_calls") or []
    if not calls:
        return "F2_no_loki_call"
    ok = _successful_loki_calls(obs)
    if not ok:
        return "F2_invalid_logql_only"
    if not any((c.get("result_count") or 0) > 0 for c in ok):
        return "F3_valid_query_empty_result"
    if "loki" not in (obs.get("evidence_sources") or set()):
        return "F4_obtained_but_not_submitted"
    return None


def evidence_correlation(evidence, loki_logs, min_overlap: int = 1) -> list[dict]:
    """L3-4b 启发式（spec §5.2/§5.3）：fact 词元与本次真实 Loki 返回日志文本词元的交集。
    只输出 CORRELATED / UNCERTAIN —— **永不 FAIL、不影响 exit code**。
    CORRELATED 只表示"文本相关"，**不表示"已证明来自 Loki"**。"""
    log_tokens: set[str] = set()
    for line in loki_logs or []:
        log_tokens |= _tokens(line)
    out: list[dict] = []
    for i, e in enumerate(evidence or []):
        if _source_value(e) != "loki":
            continue
        overlap = sorted(_tokens(getattr(e, "fact", "")) & log_tokens)
        out.append({
            "evidence_index": i,
            "source": "loki",
            "status": "CORRELATED" if len(overlap) >= min_overlap else "UNCERTAIN",
            "overlap": overlap,
        })
    return out


def merge_tool_calls(tool_order, loki_calls) -> list[dict]:
    """trace 组装（spec §7.2）：按调用顺序合并；最小插桩 —— 非 search_logs 工具只记名字，
    不把它做成通用 tracing framework（§8）。"""
    out: list[dict] = []
    queue = list(loki_calls or [])
    for name in tool_order or []:
        if name == "search_logs" and queue:
            rec = queue.pop(0)
            out.append({"tool": "search_logs", "query": rec.get("query"),
                        "success": rec.get("success"), "error": rec.get("error"),
                        "result_count": rec.get("result_count")})
        else:
            out.append({"tool": name})
    return out


def build_trace(scene: dict, model_name: str, obs: dict) -> dict:
    """结构化 trace（spec §7.2）。只输出观察数据；**不得写入任何凭据**（§7.3）。"""
    rca = obs.get("rca")
    evidence = [{"source": _source_value(e), "fact": getattr(e, "fact", "")}
                for e in (rca.evidence if rca else [])]
    return {
        "scene": scene["name"],
        "model": model_name,
        "tool_calls": merge_tool_calls(obs.get("tool_order"), obs.get("loki_calls")),
        "evidence": evidence,
        "loki": list(obs.get("loki_calls") or []),
        "evidence_correlation": list(obs.get("evidence_correlation") or []),
    }


def _loki_log_lines(data) -> list[str]:
    """从 /loki/api/v1/query_range 响应体提取**日志行**文本（仅 streams 类型）。

    matrix / vector 是 Loki 对 **metric LogQL** 的返回，不是日志；若计入，`result_count > 0`
    会让 L3-3「至少一次非空真实日志结果」被 metric 结果假满足（spec §7.3）。
    `resultType` 缺失时按旧行为处理，不强加假设。
    结构非法/为空一律返回 []，不抛异常。只取观察用文本，不保留整个 HTTP response（spec §7.3）。
    """
    try:
        payload = data["data"]
        result = payload["result"]
    except (TypeError, KeyError, IndexError):
        return []
    if isinstance(payload, dict):
        rt = payload.get("resultType")
        if rt is not None and rt != "streams":
            return []
    lines: list[str] = []
    for stream in result or []:
        if not isinstance(stream, dict):
            continue
        for entry in (stream.get("values") or []):
            if isinstance(entry, (list, tuple)) and len(entry) >= 2:
                lines.append(str(entry[1]))
    return lines


_LOG_TEXT_LIMIT = 20
_LOG_LINE_LIMIT = 500


def _record_loki_call(query: str, result) -> None:
    """把一次 search_logs 的观察值追加到 _LOKI_CALLS（spec §7.2/§7.3）。

    只读既有 ToolResult 的 success/error/data —— **不改变生产 ToolResult contract**（spec §8）。
    成功路径上生产 ToolResult 不携带状态码，故 status 记 None（不改生产契约，接受该观察缺口）。
    """
    entry = {"query": query, "success": bool(result.success), "error": result.error,
             "status": None, "result_count": 0, "logs": []}
    if result.success:
        lines = _loki_log_lines(getattr(result, "data", None))
        entry["result_count"] = len(lines)
        entry["logs"] = [ln[:_LOG_LINE_LIMIT] for ln in lines[:_LOG_TEXT_LIMIT]]
    else:
        m = _LOKI_HTTP_RE.search(result.error or "")
        if m:
            entry["status"] = int(m.group(1))
    _LOKI_CALLS.append(entry)


LOKI_SCENE = "real_loki_contract"


def select_scenarios(all_scenarios, scene_filters, expects) -> list[dict]:
    """场景选择（用户 2026-09-22 冻结语义）。

    A/B/C 始终是默认运行集；`real_loki_contract` **仅在显式选择时**进入 —— 位置参数精确
    命中其名字，或 `--expect loki_contract`（专项门禁：只跑该场景）。对 L 场景**只认精确名**
    （`--scene loki` 这类子串不得命中）；A/B/C 的既有子串过滤行为不变。
    最小改动，不做 CLI 重构。
    """
    lc = [s for s in all_scenarios if s["name"] == LOKI_SCENE]
    legacy = [s for s in all_scenarios if s["name"] != LOKI_SCENE]
    if "loki_contract" in set(expects):
        return list(lc)
    selected = [s for s in legacy
                if not scene_filters or any(f in s["name"] for f in scene_filters)]
    if LOKI_SCENE in scene_filters:
        selected = selected + lc
    return selected


import time  # noqa: E402

from app.agent import agent as _agent_mod  # noqa: E402
from app.agent.agent import investigate  # noqa: E402
from app.config import Settings  # noqa: E402
from app.incident.service import IncidentService  # noqa: E402
from app.llm.provider import LiteLLMProvider  # noqa: E402
from app.tools.cmdb import CMDBTool  # noqa: E402
from app.tools.knowledge import KnowledgeTool  # noqa: E402
from app.tools.logging import LoggingTool  # noqa: E402
from app.tools.monitoring import MonitoringTool  # noqa: E402

# 真实后端地址（backend.py up 后可用；scripts 不隐式管理生命周期）。
PROM_URL = "http://127.0.0.1:9090"
LOKI_URL = "http://127.0.0.1:3100"
CMDB_URL = "http://127.0.0.1:8081"

SCENARIOS = [
    dict(
        name="cpu_alert_negative_control", kind="A",
        title="order-service CPU 使用率高",
        service="order-service", severity="critical",
        observed_value=95.0, threshold=80.0, target="server-01",
        tools=("monitoring", "knowledge"),
    ),
    dict(
        name="error_spike_multisource", kind="B",
        title="order-service 错误率上升（HTTP 500）",
        service="order-service", severity="major",
        observed_value=None, threshold=None, target=None,
        tools=("monitoring", "logging", "knowledge"),
    ),
    dict(
        name="hybrid_fallback_observation", kind="C",
        title="order-service 服务异常",
        service="order-service", severity="critical",
        observed_value=None, threshold=None, target=None,
        tools=("monitoring", "logging"),
    ),
    dict(
        name="real_loki_contract", kind="L",
        title="order-service 服务异常（真实日志契约验证）",
        service="order-service", severity="critical",
        observed_value=None, threshold=None, target=None,
        tools=("monitoring", "logging", "knowledge"),
    ),
]

# ===== Evaluation / Regression：L3 Declarative Baseline =====
# spec: docs/superpowers/specs/2026-10-02-evaluation-regression-design.md
# baseline 的唯一权威是 committed JSON；此处只加载 / 校验 / 解释，不内嵌第二份常量。

BASELINE_PATH = ROOT / "tests" / "baselines" / "l3_declarative_baseline.json"
BASELINE_MATRIX = "l3-4-scenarios"
BASELINE_SCHEMA_VERSION = 1
KNOWN_SCENES = tuple(s["name"] for s in SCENARIOS)
KNOWN_KINDS = ("A", "B", "C", "L")
EXIT_BASELINE_CONFIG_ERROR = 5


class BaselineConfigError(Exception):
    """baseline 文件 / schema 配置错误（绝不降级为 UNOBSERVED）。"""


def _op_equals(actual, expected):
    return actual == expected


def _op_in(actual, expected):
    return actual in expected


def _op_contains(actual, expected):
    return set(expected) <= set(actual or [])


def _op_equals_set(actual, expected):
    return set(actual or []) == set(expected)


def _op_exists(actual, expected):
    return actual is not None


def _op_max(actual, expected):
    return actual is not None and actual <= expected


def _op_min(actual, expected):
    return actual is not None and actual >= expected


OPS = {
    "equals": _op_equals,
    "in": _op_in,
    "contains": _op_contains,
    "equals_set": _op_equals_set,
    "exists": _op_exists,
    "max": _op_max,
    "min": _op_min,
}


def _check_no_false_positive_cpu(obs):
    ok = a_no_false_positive_cpu(obs.get("rca"))
    return ok, "" if ok else "false positive cpu evidence"


def _check_loki_contract(obs):
    return loki_contract_success(obs)


# 有限 registry：JSON 只能引用这里显式注册的名字。
CHECKS = {
    "a_no_false_positive_cpu": _check_no_false_positive_cpu,
    "loki_contract_success": _check_loki_contract,
}

# requires → 该 runtime artifact 是否可得；不可得则该 check 为 UNOBSERVED（不调用 check）。
REQUIRES = {
    "rca": lambda obs: obs.get("rca") is not None,
    "obs": lambda obs: True,
}


def load_baseline(path=None) -> dict:
    p = Path(path) if path is not None else BASELINE_PATH
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        # JSONDecodeError 是 ValueError 子类（非 OSError），须单独成句。
        raise BaselineConfigError(f"baseline 非合法 JSON：{p}：{e}") from e
    except (OSError, UnicodeDecodeError) as e:
        # OSError 覆盖 FileNotFoundError/IsADirectoryError/PermissionError（路径不存在、
        # 误指目录、无权限）；UnicodeDecodeError 覆盖非 UTF-8 内容（如中文 Windows 主机
        # 上的 GBK 文件）。spec §8：无法加载 JSON 一律属配置错误 → exit 5，绝不泄漏原始
        # traceback。两类都归一到同一 BaselineConfigError 路径。
        raise BaselineConfigError(
            f"baseline 无法读取：{p}：{type(e).__name__}: {e}") from e


def _validate_id(item, ids, label, name, errors):
    i = item.get("id")
    if not isinstance(i, str) or not i:
        errors.append(f"{name}: {label}[].id 必须是非空字符串")
        return
    if i in ids:
        errors.append(f"{name}: 重复 id {i!r}")
    else:
        ids.add(i)


def validate_baseline(data, known_scenes=KNOWN_SCENES) -> list:
    """返回错误字符串列表；空列表 = 合法。未知 op/fn/requires/场景一律属配置错误。"""
    errors: list = []
    if not isinstance(data, dict):
        return ["baseline 顶层必须是对象"]
    if data.get("schema_version") != BASELINE_SCHEMA_VERSION:
        errors.append(f"schema_version 必须为 {BASELINE_SCHEMA_VERSION}")
    if data.get("matrix") != BASELINE_MATRIX:
        errors.append(f"matrix 必须为 {BASELINE_MATRIX!r}")
    scenarios = data.get("scenarios")
    if not isinstance(scenarios, dict):
        errors.append("scenarios 必须是对象")
        return errors
    known = set(known_scenes)
    for name, scene in scenarios.items():
        if name not in known:
            errors.append(f"未知场景：{name!r}")
            continue
        if not isinstance(scene, dict):
            errors.append(f"{name}: 场景必须是对象")
            continue
        if scene.get("kind") not in KNOWN_KINDS:
            errors.append(f"{name}: kind 必须属于 {KNOWN_KINDS}")
        for key in ("fields", "checks", "observation_only"):
            if not isinstance(scene.get(key), list):
                errors.append(f"{name}: {key} 必须是数组")
        ids: set = set()
        for f in scene.get("fields") or []:
            if not isinstance(f, dict):
                errors.append(f"{name}: fields 项必须是对象")
                continue
            _validate_id(f, ids, "fields", name, errors)
            if not isinstance(f.get("field"), str):
                errors.append(f"{name}: fields[].field 必须是字符串")
            if f.get("op") not in OPS:
                errors.append(f"{name}: 未知 op {f.get('op')!r}")
            if "value" not in f:
                errors.append(f"{name}: fields[{f.get('id')!r}] 缺少 value")
        for c in scene.get("checks") or []:
            if not isinstance(c, dict):
                errors.append(f"{name}: checks 项必须是对象")
                continue
            _validate_id(c, ids, "checks", name, errors)
            if c.get("fn") not in CHECKS:
                errors.append(f"{name}: 未注册 fn {c.get('fn')!r}")
            if c.get("requires") not in REQUIRES:
                errors.append(f"{name}: 未知 requires {c.get('requires')!r}")
            if "expect" not in c:
                errors.append(f"{name}: checks[{c.get('id')!r}] 缺少 expect")
        for o in scene.get("observation_only") or []:
            if not isinstance(o, str):
                errors.append(f"{name}: observation_only 项必须是字符串")
    return errors


# 派生 observation：不在 obs 中直接存在、需由既有纯函数导出的字段。
DERIVED_OBS = {
    "loki_failure_class": classify_loki_failure,
}


def _observation_value(obs, key):
    if key in obs:
        v = obs[key]
    else:
        fn = DERIVED_OBS.get(key)
        v = fn(obs) if fn is not None else None
    if isinstance(v, (set, frozenset)):
        return sorted(v)
    return v


def _eval_field(item, obs):
    """字段约束求值 → (result, detail)。字段不存在 → UNOBSERVED；存在但 null 且要具体值 → FAIL。"""
    field = item["field"]
    if field not in obs:
        return "UNOBSERVED", f"字段 {field} 不在 observation 中"
    actual = obs[field]
    if actual is None and item["op"] != "exists":
        return "FAIL", f"{field}=null 不满足 {item['op']} {item.get('value')!r}"
    ok = OPS[item["op"]](actual, item.get("value"))
    return ("PASS" if ok else "FAIL"), f"{field}={actual!r} {item['op']} {item.get('value')!r}"


def compare_run(baseline, obs_by_scene) -> dict:
    """对 declarative baseline 做三态比较。coverage 与三态是两个独立维度。"""
    scenes = baseline.get("scenarios") or {}
    out: list = []
    for name, scene in scenes.items():
        obs = obs_by_scene.get(name)
        entry = {"name": name, "kind": scene.get("kind"), "coverage": "covered",
                 "constraints": [], "observations": {}}
        for f in scene.get("fields") or []:
            if obs is None:
                entry["constraints"].append(
                    {"id": f["id"], "result": "UNOBSERVED", "detail": "本轮未运行"})
            else:
                result, detail = _eval_field(f, obs)
                entry["constraints"].append({"id": f["id"], "result": result, "detail": detail})
        for c in scene.get("checks") or []:
            if obs is None:
                entry["constraints"].append(
                    {"id": c["id"], "result": "UNOBSERVED", "detail": "本轮未运行"})
                continue
            if not REQUIRES[c["requires"]](obs):
                entry["constraints"].append(
                    {"id": c["id"], "result": "UNOBSERVED",
                     "detail": f"缺少 {c['requires']}"})
                continue
            ok, reason = CHECKS[c["fn"]](obs)
            entry["constraints"].append({
                "id": c["id"], "result": "PASS" if ok == c["expect"] else "FAIL",
                "detail": reason or ""})
        if obs is not None:
            entry["observations"] = {
                k: _observation_value(obs, k) for k in (scene.get("observation_only") or [])}
        out.append(entry)
    for name, obs in obs_by_scene.items():
        if name not in scenes:
            out.append({"name": name, "kind": obs.get("kind"), "coverage": "not covered",
                        "constraints": [], "observations": {}})
    return {"scenarios": out}


def compare_exit_code(report, strict=False) -> int:
    """0 = 无 FAIL（且非 strict-UNOBSERVED）；1 = 有 FAIL 或 strict 下有 UNOBSERVED。"""
    results = [c["result"] for s in report.get("scenarios", [])
               for c in s.get("constraints", [])]
    if any(r == "FAIL" for r in results):
        return 1
    if strict and any(r == "UNOBSERVED" for r in results):
        return 1
    return 0


def format_baseline_report(report, obs_by_scene=None) -> str:
    """baseline 与 scene_success 并列展示；不生成 overall。"""
    obs_by_scene = obs_by_scene or {}
    lines = [
        "==== Evaluation baseline（declarative）====",
        # baseline_validation 恒为 PASS（spec §9 ①）：配置错误（文件不可读 / 非 UTF-8 /
        # 非法 JSON / schema 不合法）都在 main() 中于任何报告打印之前以 exit 5 返回，故
        # 报告能存在 ⇒ 校验必已通过。这是**状态头**而非可区分的检查项，不得当作行为证据。
        "baseline_validation: PASS",
    ]
    for s in report.get("scenarios", []):
        lines.append(f"scene {s['name']} [{s.get('kind')}]  coverage: {s['coverage']}")
        if s["coverage"] == "covered":
            obs = obs_by_scene.get(s["name"])
            if obs is None:
                lines.append("  scene_success: UNOBSERVED (no runtime observation)")
            else:
                # 仅调用既有纯函数，不改其语义。
                ok, _reason = scene_success(s["name"], obs)
                lines.append(f"  scene_success: {'PASS' if ok else 'FAIL'}")
        for c in s.get("constraints", []):
            tail = f"  ({c['detail']})" if c.get("detail") else ""
            lines.append(f"  {c['id']}: {c['result']}{tail}")
        for k, v in (s.get("observations") or {}).items():
            lines.append(f"  observation {k} = {v!r}")
    return "\n".join(lines)


SNAPSHOT_FIELDS = (
    "read_tool_calls", "budget", "total_steps", "duration", "rca_source",
    "submit_attempted", "submit_last_validation_code", "status", "verdict",
    "failure_code", "evidence_count", "evidence_sources",
    "budget_compliance", "budget_exhausted",
)


def build_snapshot(results) -> list:
    """脱敏 runtime snapshot：仅白名单标量/结构字段；loki_calls 仅留 success/status/result_count。"""
    out: list = []
    for obs in results:
        snap = {"name": obs.get("name"), "kind": obs.get("kind")}
        for k in SNAPSHOT_FIELDS:
            v = obs.get(k)
            snap[k] = sorted(v) if isinstance(v, (set, frozenset)) else v
        snap["loki_calls"] = [
            {"success": c.get("success"), "status": c.get("status"),
             "result_count": c.get("result_count")}
            for c in (obs.get("loki_calls") or [])
        ]
        out.append(snap)
    return out


# 脚本层插桩（权威）：_READ_ORDER 只含只读工具调用（预算计数基础）；
# _FULL_ORDER 含只读 + submit（供 tool_order 展示整段轨迹）。
_READ_ORDER: list[str] = []
_FULL_ORDER: list[str] = []


def _bump_read(name: str) -> None:
    _READ_ORDER.append(name)
    _FULL_ORDER.append(name)


class _CountingMonitoring(MonitoringTool):
    """只读计数子类：调用真实 MonitoringTool 并记录到顺序表（不 mock、不改返回值）。"""

    def query_metric(self, metric: str, target: str = ""):
        _bump_read("query_metric")
        return super().query_metric(metric, target)

    def query_workload(self, service: str):
        _bump_read("query_workload")
        return super().query_workload(service)

    def query_metric_range(self, metric: str, target: str = "",
                           start=None, end=None, step: str = "60s"):
        _bump_read("query_metric_range")
        return super().query_metric_range(metric, target, start, end, step)


_LOKI_CALLS: list[dict] = []


class _CountingLogging(LoggingTool):
    def search_logs(self, query: str, limit: int = 50, start=None, end=None):
        _bump_read("search_logs")
        result = super().search_logs(query, limit, start, end)
        _record_loki_call(query, result)
        return result


class _CountingKnowledge(KnowledgeTool):
    def search_runbook(self, keyword: str):
        _bump_read("search_runbook")
        return super().search_runbook(keyword)


class _CountingCMDB(CMDBTool):
    """只读计数子类：调用真实 CMDBTool 并记录到顺序表（不 mock、不改返回值）。"""

    def get_service(self, service: str):
        _bump_read("get_service")
        return super().get_service(service)


def make_tools(settings: Settings, scenario: dict) -> list:
    tools = []
    for name in scenario["tools"]:
        tools.append({
            "monitoring": _CountingMonitoring,
            "logging": _CountingLogging,
            "knowledge": _CountingKnowledge,
            "cmdb": _CountingCMDB,
        }[name](settings))
    return tools


class _LoggingModel:
    """包真实模型做纯步数计数：generate 每次都转发给真实模型，不改行为。"""

    def __init__(self, inner):
        self._inner = inner
        self.calls = []

    def __getattr__(self, name):
        return getattr(self._inner, name)

    def generate(self, messages, **kwargs):
        self.calls.append(messages)
        return self._inner.generate(messages, **kwargs)


def _run_scenario(scenario: dict) -> dict:
    _READ_ORDER.clear()
    _FULL_ORDER.clear()
    _LOKI_CALLS.clear()

    settings = Settings()  # 读 .env；仅 URL/rag 覆写，llm_* 与 agent_* 保持 .env/env 值
    settings.prometheus_url = PROM_URL
    settings.loki_url = LOKI_URL
    settings.cmdb_url = CMDB_URL
    settings.rag_enabled = False
    settings.agent_max_steps = int(os.environ.get("L3_MAX_STEPS", "10"))
    budget = settings.agent_max_read_tools

    holder: dict = {}
    _orig_make = LiteLLMProvider.make_agent_model

    def _wrap_model(self):
        holder["model"] = _LoggingModel(_orig_make(self))
        return holder["model"]

    _orig_submit = _agent_mod.SubmitRCATool

    class _RecordingSubmit(_orig_submit):
        """记录型 SubmitRCATool 子类：investigate 内部以本类实例化（agent.py 模块全局引用被
        临时替换），实例被捕获进 holder 供事后读 submit_attempted/校验码；不 mock、不改语义。"""

        def __init__(self, svc, incident_id):
            super().__init__(svc, incident_id)
            holder["submit_tool"] = self

        def submit_rca_result(self, root_cause: str = "", confidence=None,
                              evidence=None, hypotheses=None, recommendations=None,
                              summary=None, verdict=None):
            # 签名必须与产品 SubmitRCATool.submit_rca_result 完全一致：adapt_tools 用
            # inspect.signature 建工具 inputs schema，宽签名 (*args/**kwargs) 会被封包成
            # {'args','kwargs'} 两入参 → 调用必 TypeError，且发生在产品方法体执行前，
            # 使 submit_attempted 失真、全场景被迫走 final 兜底（首跑已实证）。
            _FULL_ORDER.append("submit_rca_result")
            return super().submit_rca_result(
                root_cause=root_cause, confidence=confidence, evidence=evidence,
                hypotheses=hypotheses, recommendations=recommendations, summary=summary,
                verdict=verdict)

    svc = IncidentService()
    inc = svc.create(
        scenario["title"], scenario["service"], scenario["severity"],
        source="prometheus", alert_id="alert-l3", target=scenario.get("target"),
        observed_value=scenario.get("observed_value"),
        threshold=scenario.get("threshold"),
    )

    t0 = time.time()
    system_error = None
    try:
        LiteLLMProvider.make_agent_model = _wrap_model
        _agent_mod.SubmitRCATool = _RecordingSubmit
        investigate(settings, svc, inc.incident_id, tools=make_tools(settings, scenario))
    except Exception as e:  # noqa: BLE001 - 真实 LLM/网络异常记为观测；investigate 已把最终状态落库
        system_error = f"{type(e).__name__}: {e}"
    finally:
        LiteLLMProvider.make_agent_model = _orig_make
        _agent_mod.SubmitRCATool = _orig_submit

    got = None
    try:
        got = svc.get(inc.incident_id)  # 无论 investigate 正常/异常，都读最终落库状态
    except Exception as e:  # noqa: BLE001
        system_error = system_error or f"{type(e).__name__}: {e}"

    read_total = len(_READ_ORDER)
    sub = holder.get("submit_tool")
    model = holder.get("model")
    obs = {
        "name": scenario["name"], "kind": scenario["kind"], "title": scenario["title"],
        "duration": round(time.time() - t0, 1),
        "read_tool_calls": read_total,
        "budget": budget,
        "budget_compliance": budget_compliance(read_total, budget),
        "tool_order": list(_FULL_ORDER),
        "system_error": system_error,
        # submit_attempted 走权威 holder（investigate 事务内同一 SubmitRCATool 实例），
        # 不做任何消息内容/字符串搜索。
        "submit_attempted": bool(sub and sub.submit_attempted),
        "submit_last_validation_code": sub.last_validation_code if sub else None,
        # total_steps 以 len(model.calls) 观测：当前 smolagents ToolCallingAgent 每个 agent 步执行一次
        # 模型 generate，二者等价；此为版本相关不变量，升级 smolagents 改变内部执行模型后需复核。
        "total_steps": len(model.calls) if model else 0,
    }
    if got is not None:
        obs.update({
            "rca_valid": got.rca is not None,
            "rca_source": got.rca_source,
            "status": got.status.value if getattr(got.status, "value", None) else got.status,
            "verdict": got.verdict.value if getattr(got.verdict, "value", None) else None,
            "failure_code": got.failure_code,
            "root_cause": got.rca.root_cause if got.rca else None,
            "evidence_count": len(got.rca.evidence) if got.rca else 0,
            # F3 收尾：source 已是 EvidenceSource 枚举成员，此处落 canonical value（str），
            # 否则报告与失败信息会渲染成 <EvidenceSource.LOKI: 'loki'>。
            "evidence_sources": {e.source.value for e in got.rca.evidence} if got.rca else set(),
            "rca": got.rca,
        })
        obs["loki_calls"] = list(_LOKI_CALLS)
        _logs = [ln for c in _LOKI_CALLS for ln in (c.get("logs") or [])]
        obs["evidence_correlation"] = evidence_correlation(
            got.rca.evidence if got.rca else [], _logs)
    else:
        obs.update({"rca_valid": False, "rca_source": None, "status": None,
                    "verdict": None, "failure_code": None, "root_cause": None,
                    "evidence_count": 0, "evidence_sources": set(), "rca": None,
                    "loki_calls": list(_LOKI_CALLS), "evidence_correlation": [],
                    })
    # budget 不是 Loki contract failure（spec §6 冻结：F5 已废除）：作为独立 observation 字段呈现。
    obs["budget_exhausted"] = not obs.get("budget_compliance", True)
    return obs


import argparse  # noqa: E402

import httpx  # noqa: E402


def _fmt(obs: dict, model_name: str) -> str:
    read = obs.get("read_tool_calls", 0)
    budget = obs.get("budget", 4)
    lines = [
        f"Scenario: {obs['name']}  [{obs['kind']}]",
        f"title: {obs.get('title', '')}",
        f"Model: {model_name} | duration: {obs['duration']}s",
        f"read_tool_calls: {read} | max_read_tools: {budget} | "
        f"budget_compliance: {'PASS' if budget_compliance(read, budget) else 'FAIL'} | "
        f"total_steps: {obs.get('total_steps', 0)}",
        "tool_order:",
    ]
    order = obs.get("tool_order") or []
    lines += [f"  {t}" for t in order] if order else ["  -"]
    if obs.get("system_error"):
        lines.append(f"system_error: {obs['system_error']}")
    ok, reason = scene_success(obs["name"], obs)
    lines.append(f"scene_success: {'PASS' if ok else 'FAIL'} ({reason})")
    lines.append(f"submit_attempted: {obs.get('submit_attempted')} | rca_source: {obs.get('rca_source')} | "
                 f"rca_valid: {obs.get('rca_valid')} | verdict: {obs.get('verdict')} | "
                 f"status: {obs.get('status')} | failure_code: {obs.get('failure_code')}")
    if obs.get("kind") == "A":
        fp = a_no_false_positive_cpu(obs.get("rca"))
        lines.append(f"false_positive_cpu_evidence: {'NOT_FOUND' if fp else 'FOUND'}")
    for c in obs.get("loki_calls") or []:
        lines.append(f"loki_call: status={c.get('status')} success={c.get('success')} "
                     f"result_count={c.get('result_count')} query={c.get('query')!r}"
                     + (f" error={c.get('error')!r}" if c.get("error") else ""))
    if obs.get("name") == "real_loki_contract":
        corr = obs.get("evidence_correlation") or []
        lines.append("evidence_correlation: " + (
            ", ".join(f"{c['evidence_index']}:{c['status']}" for c in corr) or "-"))
        _fail = classify_loki_failure(obs)
        lines.append(f"loki_failure_class: {_fail if _fail else 'none'}")
        lines.append(f"budget_exhausted: {obs.get('budget_exhausted', False)}")
    if obs.get("evidence_count"):
        lines.append(f"evidence: {obs['evidence_count']} -> {sorted(obs.get('evidence_sources') or [])}")
    if obs.get("root_cause"):
        lines.append(f"root_cause: {obs['root_cause'][:140]}")
    return "\n".join(lines)


def _summary(results: list[dict], model_name: str) -> str:
    n = max(len(results), 1)
    tool_hits = sum(1 for o in results if o.get("rca_source") == "tool")
    final_hits = sum(1 for o in results if o.get("rca_source") == "final_answer")
    all_reads = [o.get("read_tool_calls", 0) for o in results]
    valid = sum(1 for o in results if o.get("rca_valid"))
    bc_ok = sum(1 for o in results if o.get("budget_compliance"))
    return "\n".join([
        "==== 汇总 ====",
        f"model: {model_name}",
        f"tool_path_rate: {tool_hits}/{len(results)}  final_fallback_rate: {final_hits}/{len(results)}",
        f"avg_read_calls: {sum(all_reads) / n:.1f}  max_read_calls: {max(all_reads) if all_reads else 0}",
        f"rca_valid_rate: {valid}/{len(results)}  budget_compliance_rate: {bc_ok}/{len(results)}",
    ])


def main(argv=None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    parser = argparse.ArgumentParser(prog="l3_real_backend")
    parser.add_argument("--expect", action="append", default=[],
                        choices=["rca", "convergence", "tool", "fallback", "all", "loki_contract"],
                        help="可选门禁（默认只观测不失败）")
    parser.add_argument("--compare", action="store_true",
                        help="对 declarative baseline 做三态对照（默认 tests/baselines/l3_declarative_baseline.json）")
    parser.add_argument("--baseline", default=None, metavar="PATH",
                        help="覆盖 baseline 文件路径（仅与 --compare 合用）")
    parser.add_argument("--baseline-out", default=None, metavar="PATH",
                        help="写脱敏 runtime snapshot（不写则跳过）")
    parser.add_argument("--strict", action="store_true",
                        help="让 UNOBSERVED 也导致非零退出（仅与 --compare 合用）")
    parser.add_argument("--trace-out", default=None, metavar="PATH",
                        help="额外写结构化 JSON trace 到 PATH（默认不写，spec §7.1）")
    parser.add_argument("scene", nargs="*", help="场景名子串过滤（如 cpu / error / hybrid）")
    args = parser.parse_args(argv)

    baseline = None
    if args.compare:
        try:
            baseline = load_baseline(args.baseline)
        except BaselineConfigError as e:
            print(str(e))
            return EXIT_BASELINE_CONFIG_ERROR
        _errors = validate_baseline(baseline)
        if _errors:
            for e in _errors:
                print(f"baseline error: {e}")
            return EXIT_BASELINE_CONFIG_ERROR

    settings = Settings()
    if not settings.llm_api_key:
        print("缺少 LLM API Key：请先配置 .env 的 llm_api_key / llm_base_url / llm_model")
        return 2

    # 不隐式管理 backend：探测真实后端可达性，给出友好提示。
    try:
        httpx.get(f"{PROM_URL}/-/ready", timeout=3).raise_for_status()
    except httpx.HTTPError:
        print(f"后端未就绪：请先运行 python tests/integration/backend.py up（需 {PROM_URL} 可达）")
        return 3

    selected = select_scenarios(SCENARIOS, args.scene, args.expect)

    # L3-1 preflight（spec §5.2）：确定性、不调模型；失败即退出，绝不消耗 token。
    preflight_ok = None
    if any(s["name"] == "real_loki_contract" for s in selected):
        from app.agent.agent import adapt_tools
        _adapters = {a.name: a for a in adapt_tools([LoggingTool(settings)])}
        preflight_ok, _pf_reason = loki_preflight_ok(
            _adapters["search_logs"].description, settings.loki_label_keys)
        print(f"preflight(L3-1): {'PASS' if preflight_ok else 'FAIL'} —— {_pf_reason}\n")
        if not preflight_ok:
            return 4

    print("\n==== L3 Real LLM + Real Backend 观测 ====")
    print(f"model={settings.llm_model}  预算(read)={settings.agent_max_read_tools}  "
          f"max_steps={settings.agent_max_steps}  场景数={len(selected)}\n")

    results = []
    for s in selected:
        print(f"--- [{s['kind']}] {s['name']} | {s['title']} | tools={s['tools']} ---")
        obs = _run_scenario(s)
        obs["preflight_ok"] = preflight_ok if s["name"] == "real_loki_contract" else True
        print(_fmt(obs, settings.llm_model))
        print()
        results.append(obs)

    if args.trace_out:
        payload = [build_trace(s, settings.llm_model, o)
                   for s, o in zip(selected, results)]
        _path = Path(args.trace_out)
        _path.parent.mkdir(parents=True, exist_ok=True)
        _path.write_text(json.dumps(payload[0] if len(payload) == 1 else payload,
                                    ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"trace written: {_path}\n")

    if args.baseline_out:
        _snap = build_snapshot(results)
        _sp = Path(args.baseline_out)
        _sp.parent.mkdir(parents=True, exist_ok=True)
        _sp.write_text(json.dumps(_snap, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"snapshot written: {_sp}\n")

    print(_summary(results, settings.llm_model))
    for obs in results:
        ok, _reason = scene_success(obs["name"], obs)
        print(f"  {obs['name']:<32} scene_success={'PASS' if ok else 'FAIL'} "
              f"verdict={obs.get('verdict') or '-'} rca_source={obs.get('rca_source') or '-'} "
              f"status={obs.get('status')}")

    expects = set(args.expect)
    rc = 0
    if expects:
        proj = [{
            "name": o["name"],
            "success": scene_success(o["name"], o)[0],
            "rca_source": o.get("rca_source"),
            "submit_attempted": o.get("submit_attempted"),
            "budget_compliance": o.get("budget_compliance"),
            "loki_contract_ok": loki_contract_success(o)[0],
        } for o in results]
        passed = evaluate_expect(expects, proj)
        print(f"--expect {sorted(expects)} -> {'PASS' if passed else 'FAIL'}")
        if not passed:
            rc = 1
    if args.compare:
        obs_by_scene = {o["name"]: o for o in results}
        rep = compare_run(baseline, obs_by_scene)
        print(format_baseline_report(rep, obs_by_scene))
        rc = max(rc, compare_exit_code(rep, args.strict))
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
