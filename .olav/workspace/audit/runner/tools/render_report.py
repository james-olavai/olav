"""render_report.py — Phase 2+3: Deterministic LLM Rendering Pipeline.

OLAV Audit subsystem, v4.0 architecture.

Contract:
  Phase 2 — For each Job in the segmented JSON:
    - count == 0 → write placeholder (no LLM call)
    - count  > 0 → assemble prompt from system_envelope + section_prompt + findings
                   → LLMFactory.get_chat_model(agent_id="auditor").invoke()
                   → append_to_file()

  Phase 3 — Read entire written report from disk
    → correlation_pass.md + full_report → LLM.invoke()
    → prepend_to_file() (summary goes to top)

Returns: report_path (str) — absolute path of the final Markdown report.

Design requirements:
  - LLM init ONCE via LLMFactory.get_chat_model(agent_id="auditor")
  - Prompts loaded from prompts_dir (decoupled from profile)
  - Pure Python for-loop — NO LangChain Agent / ReAct loop
  - Empty section writes placeholder WITHOUT calling LLM
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.tools import StructuredTool

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def _default_audit_reports_dir() -> str:
    try:
        from olav.core.config import get_paths_config
        return get_paths_config().audit_reports_dir
    except Exception:
        return "exports/audit_reports"


def render_report(
    json_path: str,
    profile_path: str,
    output_dir: str | None = None,
    prompts_dir: str = ".olav/workspace/audit/runner/prompts",
) -> str:
    """Execute Phase 2+3 of the Audit rendering pipeline.

    Args:
        json_path:    Path to the segmented JSON produced by map_engine.
        profile_path: Path to the Profile .md file (YAML frontmatter + body).
        output_dir:   Directory for the final Markdown report.
                      Defaults to config value (exports/audit_reports).
        prompts_dir:  Directory containing system_envelope.md and
                      correlation_pass.md.

    Returns:
        Absolute path of the final Markdown report file.
    """
    from olav.core.llm import LLMFactory  # imported here so tests can patch cleanly

    # Resolve and sanitize paths — LLM sometimes adds leading '/' making them absolute
    def _sanitize(p: str) -> str:
        return p.lstrip("/") if p and p.startswith("/") and not Path(p).exists() else p

    resolved_output_dir = _sanitize(output_dir) if output_dir is not None else _default_audit_reports_dir()
    profile_path = _sanitize(profile_path)
    # Normalize hyphen ↔ underscore so "bgp-health" resolves to "bgp_health.md"
    _pp = Path(profile_path)
    if not _pp.exists():
        _alt = _pp.parent / _pp.name.replace("-", "_")
        if _alt.exists():
            profile_path = str(_alt)
            _pp = _alt
        else:
            _alt2 = _pp.parent / _pp.name.replace("_", "-")
            if _alt2.exists():
                profile_path = str(_alt2)
                _pp = _alt2

    # 1. Init LLM once via config-driven factory
    llm = LLMFactory.get_chat_model(agent_id="auditor")

    # 2. Load shared format contract (applies to ALL sections)
    prompts_path = Path(prompts_dir)
    system_envelope = _load_text(prompts_path / "system_envelope.md", fallback="")

    # 3. Load segmented JSON and Profile
    audit_json = json.loads(Path(json_path).read_text())
    # Reuse map_engine's path sanitisation to handle the same LLM
    # hallucinations (leading slash / missing .olav prefix / bare names)
    try:
        from .map_engine import _sanitize_path  # type: ignore[import-not-found]
        profile_path_resolved = _sanitize_path(profile_path)
    except Exception:
        # Workspace import path varies between dev tree and installed copy;
        # fall back to direct file resolution if relative import fails.
        import importlib.util as _ilu
        _here = Path(__file__).parent
        _spec = _ilu.spec_from_file_location("_map_engine", _here / "map_engine.py")
        if _spec and _spec.loader:
            _me = _ilu.module_from_spec(_spec)
            _spec.loader.exec_module(_me)
            profile_path_resolved = _me._sanitize_path(profile_path)
        else:
            profile_path_resolved = profile_path
    profile_cfg = _parse_profile_md(Path(profile_path_resolved))

    # Detect report language once — drives ALL LLM calls and placeholders
    lang = _detect_report_language(profile_cfg)

    # 4. Prepare output file
    out_dir = Path(resolved_output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = datetime.now(tz=UTC).strftime("%Y%m%dT%H%M%SZ")
    report_path = out_dir / f"{audit_json['profile']}_{audit_json['generated_at'][:10]}_{ts}.md"

    # 5. Phase 2 — per-Job section rendering, appended to file
    for job_name, job_data in audit_json["jobs"].items():
        section_prompt = _get_section_prompt(profile_cfg, job_name)

        findings_list = job_data.get("findings", [])
        # Detect anomaly-engine insufficient_data sentinel
        is_sentinel = (
            len(findings_list) == 1
            and isinstance(findings_list[0], dict)
            and findings_list[0].get("_warning") == "insufficient_data"
        )

        if job_data["count"] == 0:
            # No LLM call — write localized placeholder directly
            placeholder = _empty_section(job_name, lang)
            _append_to_file(report_path, placeholder)
        elif is_sentinel:
            s = findings_list[0]
            if lang == "zh":
                note = (
                    f"## {job_name}\n\n"
                    f"> **数据不足，无法进行统计分析。**  \n"
                    f"> 最少需要 {s.get('min_samples_required', '?')} 个样本。  \n"
                    f"> {s.get('recommendation', '')}  \n\n"
                    f"*样本积累完成后，异常检测将自动启用。*\n\n---\n"
                )
            else:
                note = (
                    f"## {job_name}\n\n"
                    f"> **Insufficient data for statistical analysis.**  \n"
                    f"> Minimum samples required: {s.get('min_samples_required', '?')}.  \n"
                    f"> {s.get('recommendation', '')}  \n\n"
                    f"*No anomaly findings rendered — accumulate more snapshots before this check becomes meaningful.*\n\n---\n"
                )
            _append_to_file(report_path, note)
        else:
            prompt = _assemble_prompt(system_envelope, section_prompt, findings_list, lang)
            section_content = llm.invoke(prompt).content
            _append_to_file(report_path, section_content)

    # 6. Phase 3 — Global Correlation Pass
    corr_template = _load_text(prompts_path / "correlation_pass.md", fallback=_DEFAULT_CORR_TEMPLATE)
    full_report = report_path.read_text() if report_path.exists() else ""

    # Inject explicit language directive for the correlation pass
    lang_directive = (
        "**LANGUAGE OVERRIDE**: You MUST write the entire Executive Summary in "
        + ("Chinese (Simplified). 所有文字内容必须为中文，技术术语 BGP/OSPF/CPU/STP 保持英文。"
           if lang == "zh" else "English. All text must be in English.")
    )

    # Append incident clusters if engine produced any — gives LLM the full
    # topology root-cause context for cross-section chain reasoning.
    clusters = audit_json.get("incident_clusters", [])
    cluster_context = ""
    if clusters:
        cluster_context = (
            "\n\n---\n\n**Incident Clusters (topology root-cause engine output):**\n```json\n"
            + json.dumps(clusters, ensure_ascii=False, indent=2, default=str)
            + "\n```"
        )

    summary_prompt = lang_directive + "\n\n" + corr_template + "\n\n---\n\n" + full_report + cluster_context
    summary = llm.invoke(summary_prompt).content
    _prepend_to_file(report_path, summary + "\n\n")

    # 7. Phase 4 — Closed-Loop Post-Check Playbook (deterministic, no LLM call)
    playbook = _generate_postcheck_playbook(audit_json, lang=lang)
    _append_to_file(report_path, playbook)

    # 8. ARCH-11 Phase 2 — citation linter. Only runs when the profile
    # declared ``emit_sources: true`` (otherwise every section would flag).
    if audit_json.get("emit_sources") or profile_cfg.get("emit_sources"):
        try:
            from render_report_linter import (
                format_audit_block,
                lint_report_file,
            )
            non_empty = {
                name for name, data in audit_json["jobs"].items()
                if data.get("count", 0) > 0
            }
            violations = lint_report_file(report_path, non_empty_sections=non_empty)
            _append_to_file(report_path, format_audit_block(violations))
            if violations:
                logger.warning(
                    "render_report: %d citation violation(s): %s",
                    len(violations),
                    [v.section for v in violations],
                )
        except Exception as lint_err:
            logger.debug("citation linter skipped: %s", lint_err)

    logger.info("render_report: final report at %s", report_path)

    # Extract Executive Summary for immediate display (avoids LLM max_tokens truncation)
    executive_summary = ""
    try:
        report_text = report_path.read_text(encoding="utf-8")
        import re as _re
        _match = _re.search(
            r'##\s*(?:Executive\s+Summary|Summary|Overview)\s*\n(.*?)(?=\n##|\n---|\Z)',
            report_text, _re.DOTALL | _re.IGNORECASE,
        )
        if _match:
            executive_summary = _match.group(1).strip()
    except Exception:
        pass

    return (
        f"Report saved: {report_path}\n\n"
        f"## Executive Summary\n\n{executive_summary}"
        if executive_summary
        else str(report_path)
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _generate_postcheck_playbook(audit_json: dict, lang: str = "zh") -> str:
    """Phase 4: Generate a deterministic closed-loop Post-Check Playbook.

    No LLM call — builds `olav -a ops` prompts directly from structured data:
      1. Incident Clusters  → topology simulation prompts (highest priority)
      2. High-severity job findings → device-level verification prompts
      3. Fallback catch-all for devices seen in any finding

    The operator copies each prompt into their terminal to invoke the Ops Agent
    for post-fix verification and networkx topology simulation.
    """
    if lang == "zh":
        header_desc = (
            "> 以下是基于本次審计结果生成的排错建议。将对应命令复制到终端执行，"
            "Ops Agent 将使用 networkx 拓扑模拟和 SSH 验证帮助你定位并确认修复效果。\n"
        )
    else:
        header_desc = (
            "> The following prompts are generated from this audit's findings. "
            "Copy each command into your terminal to invoke the Ops Agent, which will use "
            "networkx topology simulation and SSH to help verify root cause and confirm fixes.\n"
        )
    lines: list[str] = [
        "\n\n---\n",
        "## 🔁 Post-Check Playbook\n",
        header_desc,
    ]

    clusters: list[dict] = audit_json.get("incident_clusters", [])
    jobs: dict[str, dict] = audit_json.get("jobs", {})
    prompt_index = 1
    seen_devices: set[str] = set()

    # ── Priority 1: Incident clusters ──────────────────────────────────────
    if clusters:
        lines.append(
            "\n### Priority 1 \u2014 " +
            ("故障集群（拓扑根因已确认）" if lang == "zh" else "Incident Clusters (Topology Root-Cause Confirmed)") +
            "\n"
        )
        for cl in clusters:
            roots = cl.get("root_cause_candidates", [])
            chain = cl.get("cascade_chain", [])
            devices = cl.get("devices_affected", [])
            etypes = cl.get("event_types", {})
            start = cl.get("start_time", "")[:19].replace("T", " ")
            dur = cl.get("duration_mins", 0)

            root_str = ", ".join(roots) if roots else (devices[0] if devices else "unknown")
            if isinstance(chain, str):
                chain_str = chain  # already formatted by incident_engine
            elif chain:
                chain_str = " → ".join(chain)
            else:
                chain_str = ", ".join(devices[:4])
            etype_str = ", ".join(f"{k}×{v}" for k, v in etypes.items())
            seen_devices.update(devices)

            if lang == "zh":
                topo_label = f"拓扑仿真 \u2014 根因节点 `{root_str}`"
                prompt = (
                    f'olav -a ops "Cluster #{cl.get("cluster_id", prompt_index)} '
                    f'({start}, {dur}min): 故障链 {chain_str}。'
                    f'请用 networkx 模拟移除根因节点 [{root_str}] 后的拓扑影响，'
                    f'识别所有受影响的下游设备和链路，验证是否存在冗余路径，'
                    f'并给出恢复操作序列。事件类型分布：{etype_str}"'
                )
            else:
                topo_label = f"Topology simulation \u2014 root cause `{root_str}`"
                prompt = (
                    f'olav -a ops "Cluster #{cl.get("cluster_id", prompt_index)} '
                    f'({start}, {dur}min): fault chain {chain_str}. '
                    f'Use networkx to simulate removal of root node [{root_str}]: '
                    f'identify all affected downstream devices and links, '
                    f'verify redundant paths exist, and output recovery sequence. '
                    f'Event types: {etype_str}"'
                )
            lines.append(f"**{prompt_index}.** {topo_label}\n\n```bash\n{prompt}\n```\n")
            prompt_index += 1

    # ── Priority 2: High-severity job findings ───────────────────────────
    PRIORITY_JOBS = [
        ("BGP_Not_Established", _ops_prompt_bgp),
        ("BGP_Drift",           _ops_prompt_bgp_drift),
        ("Interface_Down",      _ops_prompt_interface),
        ("Interface_State_Drift", _ops_prompt_interface),
        ("OSPF_Not_Full",       _ops_prompt_ospf),
        ("OSPF_Drift",          _ops_prompt_ospf),
        ("CPU_Anomaly",         _ops_prompt_cpu),
        ("CPU_Drift",           _ops_prompt_cpu_drift),
        ("Memory_Anomaly",      _ops_prompt_cpu),
        ("Config_Drift",        _ops_prompt_config),
        ("STP_Drift",           _ops_prompt_stp),
        ("STP_Error_Disable",   _ops_prompt_stp),
    ]

    p2_lines: list[str] = []
    for job_name, builder in PRIORITY_JOBS:
        job_data = jobs.get(job_name, {})
        findings = job_data.get("findings", [])
        # Skip sentinel / empty
        if not findings or (len(findings) == 1 and "_warning" in findings[0]):
            continue
        for finding in findings[:3]:   # cap at 3 per job
            device = finding.get("device_name", finding.get("device", ""))
            if not device:
                continue
            prompt = builder(device, finding, lang)
            if prompt:
                p2_lines.append(f"**{prompt_index}.** `{device}` — {job_name}\n\n```bash\n{prompt}\n```\n")
                seen_devices.add(device)
                prompt_index += 1

    if p2_lines:
        lines.append(
            "\n### Priority 2 \u2014 " +
            ("设备级验证" if lang == "zh" else "Device-Level Verification") +
            "\n"
        )
        lines.extend(p2_lines)

    # ── Priority 3: Catch-all for any remaining devices in findings ───────
    all_finding_devices: set[str] = set()
    for job_data in jobs.values():
        for f in job_data.get("findings", []):
            d = f.get("device_name", f.get("device", ""))
            if d and "_warning" not in f:
                all_finding_devices.add(d)

    fallback_devices = all_finding_devices - seen_devices
    if fallback_devices:
        lines.append(
            "\n### Priority 3 \u2014 " +
            ("通用健康确认（剩余设备）" if lang == "zh" else "General Health Check (remaining devices)") +
            "\n"
        )
        for device in sorted(fallback_devices)[:5]:
            if lang == "zh":
                prompt = (
                    f'olav -a ops "对 {device} 执行快速健康确认：'
                    f'show logging last 50 | show interfaces summary | show processes cpu sorted | head 10，'
                    f'与 DuckDB 历史快照对比，确认巡检窗口内状态稳定"'
                )
                label = "通用健康确认"
            else:
                prompt = (
                    f'olav -a ops "Quick health check on {device}: '
                    f'show logging last 50, show interfaces summary, show processes cpu sorted | head 10. '
                    f'Compare against DuckDB historical snapshots and confirm stable state during inspection window."'
                )
                label = "General health check"
            lines.append(f"**{prompt_index}.** `{device}` \u2014 {label}\n\n```bash\n{prompt}\n```\n")
            prompt_index += 1

    if prompt_index == 1:
        lines.append(
            "\n\u2705 *" +
            ("本巡检窗口内所有指标正常，无需执行 Post-Check。*\n"
             if lang == "zh" else
             "No actionable post-checks required \u2014 all metrics within normal range.*\n")
        )

    lines.append(
        "\n> " +
        ("每条命令相互独立，可按优先级逐条执行。Ops Agent 会通过 SSH 并结合 networkx 拓扑模型给出判断，无需预先准备其他参数。"
         if lang == "zh" else
         "Each command is self-contained and can be run independently in any order. "
         "The Ops Agent will SSH to devices and apply networkx topology analysis \u2014 no prior setup required.")
        + "\n"
    )
    return "\n".join(lines)


# ── Per-job ops prompt builders ────────────────────────────────────────────

def _ops_prompt_bgp(device: str, f: dict, lang: str = "zh") -> str:
    neighbor = f.get("neighbor_ip", f.get("neighbor", ""))
    state = f.get("state", f.get("bgp_state", "unknown"))
    if lang == "zh":
        nb_part = f" 邻居 {neighbor}" if neighbor else ""
        return (
            f'olav -a ops "{device} BGP{nb_part} 状态异常({state})：'
            f'1)SSH执行 show bgp neighbor{" " + neighbor if neighbor else ""} 确认 Reset reason；'
            f'2)networkx 模拟该BGP会话断开后的路由影响范围；'
            f'3)检查对端接口和AS号匹配"'
        )
    else:
        nb_part = f" {neighbor}" if neighbor else ""
        return (
            f'olav -a ops "{device} BGP neighbor{nb_part} state anomaly ({state}): '
            f'1) SSH run \'show bgp neighbor{" " + neighbor if neighbor else ""}\' confirm Reset reason; '
            f'2) Use networkx to simulate BGP session down and analyze route impact; '
            f'3) Verify peer interface and AS number match"'
        )


def _ops_prompt_bgp_drift(device: str, f: dict, lang: str = "zh") -> str:
    snap_b = f.get("snap_before", "")
    snap_a = f.get("snap_after", "")
    if lang == "zh":
        return (
            f'olav -a ops "{device} BGP配置在快照 {snap_b}→{snap_a} 间发生变化：'
            f'对比两次快照的BGP邻居表，确认是否有邻居增加/删除，'
            f'用networkx验证路由收敛是否完整"'
        )
    else:
        return (
            f'olav -a ops "{device} BGP configuration changed between snapshots {snap_b}→{snap_a}: '
            f'Compare BGP neighbor tables, confirm if neighbors added/deleted, '
            f'use networkx to verify route convergence is complete"'
        )


def _ops_prompt_interface(device: str, f: dict, lang: str = "zh") -> str:
    iface = f.get("interface", f.get("if_name", ""))
    iface_part = f" {iface}" if iface else ""
    if lang == "zh":
        return (
            f'olav -a ops "{device} 接口{iface_part} 状态漂移：'
            f'1)SSH执行 show interfaces{iface_part} 确认 line protocol 和 input errors；'
            f'2)networkx检查该链路是否有冗余路径；'
            f'3)如疑似光衰执行 show interfaces{iface_part} transceiver"'
        )
    else:
        return (
            f'olav -a ops "{device} interface{iface_part} state drift: '
            f'1) SSH run \'show interfaces{iface_part}\' confirm line protocol and input errors; '
            f'2) Use networkx to check if this link has redundant paths; '
            f'3) If optical power issue suspected run \'show interfaces{iface_part} transceiver\'"'
        )


def _ops_prompt_ospf(device: str, f: dict, lang: str = "zh") -> str:
    neighbor = f.get("neighbor_id", f.get("neighbor_ip", ""))
    nb_part = f" {neighbor}" if neighbor else ""
    if lang == "zh":
        return (
            f'olav -a ops "{device} OSPF邻居{nb_part} 未达Full：'
            f'SSH执行 show ip ospf neighbor detail{nb_part}，检查 MTU/Hello/Dead interval，'
            f'networkx分析该OSPF区域内路由连通性"'
        )
    else:
        return (
            f'olav -a ops "{device} OSPF neighbor{nb_part} not in FULL state: '
            f'SSH run \'show ip ospf neighbor detail{nb_part}\' check MTU/Hello/Dead interval, '
            f'use networkx to analyze OSPF area routing connectivity"'
        )


def _ops_prompt_cpu(device: str, f: dict, lang: str = "zh") -> str:
    z = f.get("z_score", "")
    val = f.get("value", f.get("cpu", f.get("mem_pct", "")))
    mean = f.get("mean", "")
    metric = f.get("metric", "CPU/Memory")
    z_str = f"z={z:.2f}, " if isinstance(z, float) else ""
    val_str = f"当前={val:.1f}, 均值={mean:.1f}" if isinstance(val, float) and isinstance(mean, float) else ""
    if lang == "zh":
        return (
            f'olav -a ops "{device} {metric}统计异常({z_str}{val_str})：'
            f'SSH执行 show processes cpu sorted | head 20，'
            f'关联日志 show logging | include %CPU，'
            f'检查同时段BGP路由抖动和ACL命中计数"'
        )
    else:
        val_str_en = f"current={val:.1f}, mean={mean:.1f}" if isinstance(val, float) and isinstance(mean, float) else ""
        return (
            f'olav -a ops "{device} {metric} statistical anomaly ({z_str}{val_str_en}): '
            f'SSH run \'show processes cpu sorted | head 20\', '
            f'correlate with logs \'show logging | include CPU\', '
            f'check concurrent BGP route churn and ACL hit counts"'
        )


def _ops_prompt_cpu_drift(device: str, f: dict, lang: str = "zh") -> str:
    delta = f.get("cpu_delta_per_hour", f.get("cpu_delta", ""))
    gap = f.get("time_gap_h", "")
    delta_str = f"Δ={delta:.1f}/h, gap={gap:.1f}h" if isinstance(delta, float) else ""
    if lang == "zh":
        return (
            f'olav -a ops "{device} CPU漂移({delta_str})：'
            f'确认是计划性变更(如路由重收敛)还是异常负载，'
            f'show processes cpu history，检查是否与Config_Drift时间戳重合"'
        )
    else:
        return (
            f'olav -a ops "{device} CPU drift ({delta_str}): '
            f'Confirm if planned change (e.g. route convergence) or anomalous load, '
            f'show processes cpu history, check if correlates with Config_Drift timestamp"'
        )


def _ops_prompt_config(device: str, f: dict, lang: str = "zh") -> str:
    added = f.get("added_count", 0)
    removed = f.get("removed_count", 0)
    if lang == "zh":
        return (
            f'olav -a ops "{device} 配置变更(+{added}/-{removed}行)：'
            f'读取最新diff_content，判断是计划变更还是未授权变更，'
            f'如包含STP/VLAN变更则用networkx模拟生成树拓扑变化，输出合规性评估"'
        )
    else:
        return (
            f'olav -a ops "{device} configuration changed (+{added}/-{removed} lines): '
            f'Read latest diff_content, determine if planned or unauthorized change, '
            f'if STP/VLAN changes use networkx to simulate spanning tree changes and output compliance assessment"'
        )


def _ops_prompt_stp(device: str, f: dict, lang: str = "zh") -> str:
    iface = f.get("interface", f.get("if_name", ""))
    iface_part = f" {iface}" if iface else ""
    if lang == "zh":
        return (
            f'olav -a ops "{device} STP/err-disable 告警{iface_part}：'
            f'SSH执行 show spanning-tree detail | show interfaces{iface_part} status，'
            f'networkx模拟该VLAN生成树结构，确认根桥位置是否符合设计"'
        )
    else:
        return (
            f'olav -a ops "{device} STP/err-disable alert{iface_part}: '
            f'SSH run \'show spanning-tree detail | show interfaces{iface_part} status\', '
            f'use networkx to simulate this VLAN spanning tree structure and confirm root bridge position matches design"'
        )


def _load_text(path: Path, fallback: str = "") -> str:
    """Read a text file, returning fallback if it doesn't exist."""
    if path.exists():
        return path.read_text()
    logger.warning("Prompt file not found: %s — using fallback", path)
    return fallback


def _parse_profile_md(profile_path: Path) -> dict:
    """Parse YAML frontmatter from a Profile .md file.

    Returns a dict with a 'jobs' key mapping job_name → job_config dict.
    """
    import re

    content = profile_path.read_text()
    # Extract YAML frontmatter between --- delimiters
    match = re.match(r"^---\s*\n(.*?)\n---", content, re.DOTALL)
    if not match:
        return {"jobs": {}}

    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(match.group(1)) or {}
    except Exception:
        return {"jobs": {}}

    # Build job_name → job_config lookup
    jobs_lookup: dict[str, dict] = {}
    for job in raw.get("jobs", []):
        name = job.get("name")
        if name:
            jobs_lookup[name] = job

    # Expose top-level frontmatter fields (language, snapshot_resolution, etc.)
    top_level = {k: v for k, v in raw.items() if k != "jobs"}
    return {"jobs": jobs_lookup, **top_level}


def _get_section_prompt(profile_cfg: dict, job_name: str) -> str:
    job = profile_cfg.get("jobs", {}).get(job_name, {})
    return job.get("section_prompt", "Analyze the findings below. Identify anomalies, root causes, and provide remediation recommendations.")


def _format_source_suffix(src: dict | None) -> str:
    """ARCH-11 Phase 1: render a `_source` dict into a ``[src: …]`` tag.

    Returns the empty string for falsy / non-dict inputs so callers can
    unconditionally concatenate the result.

    Format (stable across versions — see :func:`parse_src_token`):
        [src: <table>[#<snapshot_id>][; device=<name>][; row=<n>]]
    """
    if not isinstance(src, dict) or not src:
        return ""
    parts: list[str] = []
    table = src.get("table")
    snap = src.get("snapshot_id")
    if table and snap:
        parts.append(f"{table}#{snap}")
    elif table:
        parts.append(str(table))
    if src.get("device"):
        parts.append(f"device={src['device']}")
    if "row_index" in src:
        parts.append(f"row={src['row_index']}")
    return f"[src: {'; '.join(parts)}]" if parts else ""


# ARCH-11 Round 44 — parse_src_token: inverse of _format_source_suffix.
# Foundation for a future ``olav explain <token>`` CLI (ARCH-11 gap #3).
# The CLI will parse the token, re-run the underlying query, and surface
# the raw rows so operators can verify an LLM-generated finding without
# writing SQL themselves.
_SRC_TOKEN_RE = __import__("re").compile(r"\[src:\s*(?P<body>[^\]]+)\]")


def parse_src_token(tag: str) -> dict | None:
    """Parse a ``[src: …]`` tag into a source dict (ARCH-11 Phase 3 groundwork).

    Inverse of :func:`_format_source_suffix`. Handles the format::

        [src: <table>[#<snapshot_id>][; device=<name>][; row=<n>]]

    Args:
        tag: A string potentially containing one ``[src: …]`` tag. Leading
            / trailing whitespace is tolerated. If the string carries
            additional text, only the first token is parsed.

    Returns:
        A dict with any of ``{table, snapshot_id, device, row_index}`` set,
        or ``None`` if the string does not contain a recognisable token.

    Round-trip invariant:
        ``_format_source_suffix(parse_src_token(s)) == s`` for every ``s``
        produced by :func:`_format_source_suffix` (pinned by
        ``tests/governance/test_round44_arch11_reconcile.py``).
    """
    if not isinstance(tag, str) or not tag:
        return None
    m = _SRC_TOKEN_RE.search(tag)
    if not m:
        return None
    body = m.group("body").strip()
    if not body:
        return None
    out: dict = {}
    segments = [s.strip() for s in body.split(";") if s.strip()]
    if not segments:
        return None
    head = segments[0]
    # head is either "<table>#<snapshot_id>" or "<table>"
    if "#" in head:
        table, snap = head.split("#", 1)
        out["table"] = table.strip()
        out["snapshot_id"] = snap.strip()
    else:
        out["table"] = head
    for seg in segments[1:]:
        if "=" not in seg:
            continue
        key, _, val = seg.partition("=")
        key = key.strip()
        val = val.strip()
        if key == "device":
            out["device"] = val
        elif key == "row":
            try:
                out["row_index"] = int(val)
            except ValueError:
                continue
    return out or None


def _build_evidence_block(findings: list[dict]) -> str:
    """Render a markdown bullet list of `[src: …]` tags outside the JSON block.

    Keeping the citations outside the fenced JSON ensures the LLM (which
    parses the JSON literally) still receives them as free-form markdown
    it can quote in its output.
    """
    tags: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        suffix = _format_source_suffix(f.get("_source"))
        if suffix:
            tags.append(f"- {suffix}")
    if not tags:
        return ""
    return "## Evidence\n" + "\n".join(tags) + "\n\n"


def _assemble_prompt(system_envelope: str, section_prompt: str, findings: list[dict], lang: str = "en") -> str:
    """Build the full prompt for a single Job section."""
    lang_override = (
        "**LANGUAGE OVERRIDE**: You MUST write this entire section in Chinese (Simplified). "
        "所有文字内容必须为中文，技术术语 BGP/OSPF/CPU/STP/ACL 保持英文。"
        if lang == "zh" else
        "**LANGUAGE OVERRIDE**: You MUST write this entire section in English."
    )
    findings_json = json.dumps(findings, ensure_ascii=False, indent=2)
    evidence_block = _build_evidence_block(findings)
    return (
        f"{lang_override}\n\n"
        f"{system_envelope}\n\n"
        f"---\n\n"
        f"## Rendering Guidelines (Business Rules)\n{section_prompt}\n\n"
        f"---\n\n"
        f"{evidence_block}"
        f"## Detection Data (JSON)\n```json\n{findings_json}\n```"
    )


def _detect_report_language(profile_cfg: dict) -> str:
    """Detect the dominant language of this profile's section_prompts.

    Returns "zh" if the majority of section_prompts contain Chinese characters,
    "en" otherwise.  This drives ALL LLM calls and placeholder text so the
    entire report is in one consistent language.

    Design rationale: language should be a property of the *profile* (which was
    authored by the designer in the user's language), not of the LLM's runtime
    content detection (which is unreliable when the report is mixed mid-run).
    """
    import re
    chinese_re = re.compile(r"[\u4e00-\u9fff]")
    zh_count = 0
    total = 0
    for job in profile_cfg.get("jobs", {}).values():
        prompt_text = job.get("section_prompt", "")
        if prompt_text:
            total += 1
            if chinese_re.search(prompt_text):
                zh_count += 1
    # Also check profile-level language override in frontmatter
    explicit = profile_cfg.get("language", "").lower()
    if explicit in ("zh", "chinese", "cn"):
        return "zh"
    if explicit in ("en", "english"):
        return "en"
    return "zh" if (total > 0 and zh_count / total >= 0.5) else "en"


def _empty_section(job_name: str, lang: str = "en") -> str:
    """Return a localized empty-section placeholder without calling LLM."""
    if lang == "zh":
        return f"\n## {job_name}\n\n\u2705 {job_name}：本巡检窗口内未发现异常。\n"
    return f"\n## {job_name}\n\n✅ {job_name}: No anomalies detected in this window.\n"


def _append_to_file(path: Path, content: str) -> None:
    """Append content to a file, creating it if necessary."""
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + content.rstrip() + "\n")


def _prepend_to_file(path: Path, content: str) -> None:
    """Prepend content to an existing file."""
    existing = path.read_text() if path.exists() else ""
    path.write_text(content + existing)


# Minimal fallback if correlation_pass.md is missing
_DEFAULT_CORR_TEMPLATE = (
    "You are a senior WAN architect. Read the full inspection report below and produce an "
    "Executive Summary containing: (1) cross-section fault correlations, "
    "(2) Top-3 Action Items ordered Critical → Warning, and "
    "(3) a one-sentence overall health verdict (🔴 Critical / ⚠️ Warning / ✅ Healthy)."
)

_render_report_tool = StructuredTool.from_function(render_report)
