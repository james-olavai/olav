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
from datetime import UTC, datetime, timedelta, timezone
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

    # 1. Init LLM once via config-driven factory.
    #
    # ISSUE-AUDIT-LLM-OUTPUT-NONDETERMINISTIC (P3, 2026-05-12): force
    # temperature=0 so two runs over the same findings JSON produce
    # near-identical prose. Most providers (OpenAI, Anthropic, Ollama)
    # honor this to within token-tie-breaking noise; combined with the
    # evidence-only correlation prompt (P1.1) this is enough to make
    # audit reports diff-able across runs without a full Jinja rewrite.
    llm = LLMFactory.get_chat_model(agent_id="auditor", temperature=0)

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

    # ── ISSUE-AUDIT-LLM-OUTPUT-NONDETERMINISTIC (B follow-up, 2026-05-12) ─
    # Profile-level narrative_mode knob:
    #   * "llm"   (default): per-section + correlation pass go through
    #             LLM (existing behaviour, near-deterministic via T=0)
    #   * "jinja": ALL prose generated from Jinja templates against
    #             findings JSON — byte-identical across runs (modulo
    #             timestamp in path). Required for archived audits
    #             that need digital signatures / regression diffs.
    narrative_mode = str(profile_cfg.get("narrative_mode", "llm")).strip().lower()
    if narrative_mode not in ("llm", "jinja"):
        logger.warning(
            "render_report: unknown narrative_mode %r, falling back to 'llm'",
            narrative_mode,
        )
        narrative_mode = "llm"

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

        # Truncation pre-amble (shared across narrative modes)
        if job_data.get("truncated"):
            shown = job_data.get("shown_count", len(findings_list))
            total = job_data.get("total_count", "?")
            if lang == "zh":
                trunc_note = (
                    f"> ⚠️ **结果截断**：仅显示前 {shown} 条 finding（共 {total} 条）。"
                    f" 调高 profile 的 `max_findings_per_job` 以查看更多。\n\n"
                )
            else:
                trunc_note = (
                    f"> ⚠️ **Results truncated**: showing {shown} of {total} findings. "
                    f"Raise the profile's `max_findings_per_job` to see more.\n\n"
                )
        else:
            trunc_note = ""

        if job_data["count"] == 0:
            # No LLM call — write localized placeholder directly
            placeholder = _empty_section(job_name, lang)
            _append_to_file(report_path, trunc_note + placeholder if trunc_note else placeholder)
            continue
        if narrative_mode == "jinja":
            # Deterministic Jinja path — no LLM call.
            section_content = _render_section_jinja(
                job_name=job_name, job_data=job_data, lang=lang,
            )
            _append_to_file(report_path, trunc_note + section_content)
            continue
        if is_sentinel:
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
            _append_to_file(report_path, trunc_note + note if trunc_note else note)
        else:
            prompt = _assemble_prompt(system_envelope, section_prompt, findings_list, lang)
            section_content = llm.invoke(prompt).content
            _append_to_file(report_path, trunc_note + section_content if trunc_note else section_content)

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
    #
    # ISSUE-AUDIT-INCIDENT-CORRELATION-DEGRADED (P3, 2026-05-12): the
    # cluster-priority rules used to be hard-coded into correlation_pass.md
    # and shipped to the LLM on every run, even when 99% of audits have
    # no clusters (run_incident_clustering defaults to false). Now the
    # cluster context AND the rules for processing it are injected
    # only when clusters exist — saves ~150 prompt tokens per run on
    # small-budget models like gemma4.
    clusters = audit_json.get("incident_clusters", [])
    cluster_context = ""
    if clusters:
        cluster_rules = (
            "\n\n**Incident Cluster priority** (clusters present in this run):\n"
            "- State the `root_cause_candidates` device(s) as the inferred origin.\n"
            "- Describe the `cascade_chain` in plain language (quote literally — do not embellish).\n"
            "- Use `event_types` to characterise the blast radius.\n"
            "- Timestamp the cluster with `start_time` / `duration_mins`."
        )
        cluster_context = (
            cluster_rules
            + "\n\n---\n\n**Incident Clusters (topology root-cause engine output):**\n```json\n"
            + json.dumps(clusters, ensure_ascii=False, indent=2, default=str)
            + "\n```"
        )

    # ISSUE-AUDIT-FRESHNESS-GATE-MISSING (P1): tell the LLM about stale
    # data so the executive summary can't write "✅ Healthy" on snapshots
    # that are 11 days old.
    freshness_warning = audit_json.get("freshness_warning")
    freshness_directive = ""
    if isinstance(freshness_warning, dict) and freshness_warning.get("message"):
        freshness_directive = (
            "\n\n**⚠️ STALE DATA — HARD CONSTRAINT**: "
            + freshness_warning["message"]
            + " The verdict line at the END of your Executive Summary MUST NOT "
              "be `✅ Healthy`. Use `⚠️ At Risk (stale data)` or `🔴 Critical "
              "(unverified)` depending on findings. Action item #1 MUST be "
              "'restore data collection / re-run snapshot'."
        )

    if narrative_mode == "jinja":
        # Deterministic executive summary — no LLM call.
        summary = _render_executive_summary_jinja(
            audit_json=audit_json,
            profile_cfg=profile_cfg,
            lang=lang,
        )
    else:
        summary_prompt = lang_directive + freshness_directive + "\n\n" + corr_template + "\n\n---\n\n" + full_report + cluster_context
        summary = llm.invoke(summary_prompt).content

    # ── ISSUE-AUDIT-FRESHNESS-GATE-MISSING (P1, 2026-05-12) ─────────────
    # If map_engine flagged stale data, prepend a deterministic banner
    # ABOVE the LLM-written summary. The banner is non-LLM, so it cannot
    # be hallucinated away or rephrased into "everything looks healthy".
    freshness_warning = audit_json.get("freshness_warning")
    freshness_banner = ""
    if isinstance(freshness_warning, dict) and freshness_warning.get("message"):
        if lang == "zh":
            freshness_banner = (
                "> 🔴 **数据陈旧警告**：" + freshness_warning["message"]
                .replace("Newest data is", "最新数据已 ")
                .replace("h old", "h（小时）")
                .replace("threshold:", "阈值:")
                .replace("All findings below reflect that snapshot — they DO NOT prove current network state.",
                         "下方所有发现仅反映该快照状态，**无法证明当前网络的实际状态**。")
                .replace("Re-collect before treating any '✅ Healthy' finding as authoritative.",
                         "在视任何 '✅ Healthy' 发现为权威之前，请重新采集数据。")
                + "\n\n"
            )
        else:
            freshness_banner = "> 🔴 **Stale Data Warning**: " + freshness_warning["message"] + "\n\n"

    _prepend_to_file(report_path, freshness_banner + summary + "\n\n")

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

    # ── ISSUE-AUDIT-NO-ALERTING-CHANNEL (P2, 2026-05-12) ────────────────
    # Push critical findings to OLAV_ALERT_WEBHOOK_URL if set. Best-
    # effort: webhook failures are logged, NOT raised — audit must
    # still produce its report even if the alerting receiver is down.
    _post_critical_alert(
        audit_json=audit_json,
        profile_name=audit_json.get("profile", "unknown"),
        report_path=str(report_path),
        executive_summary=summary,
    )

    # Extract Executive Summary + freshness banner for immediate display.
    executive_summary = ""
    stale_banner = ""
    try:
        report_text = report_path.read_text(encoding="utf-8")
        import re as _re
        _match = _re.search(
            r'##\s*(?:Executive\s+Summary|Summary|Overview)\s*\n(.*?)(?=\n##|\n---|\Z)',
            report_text, _re.DOTALL | _re.IGNORECASE,
        )
        if _match:
            executive_summary = _match.group(1).strip()
        # ISSUE-AUDIT-FRESHNESS-GATE-MISSING (P1, 2026-05-12): extract the
        # blockquote banner prepended above the summary so the CLI surface
        # can show it before the (possibly misleading) summary text.
        _banner = _re.search(
            r'^(>\s+(?:🔴|⚠️)\s*\*\*[^*]+\*\*[^\n]*)',
            report_text, _re.MULTILINE,
        )
        if _banner:
            stale_banner = _banner.group(1).strip()
    except Exception:
        pass

    if not executive_summary:
        return str(report_path)
    _summary_block = f"## Executive Summary\n\n{executive_summary}"
    if stale_banner:
        _summary_block = stale_banner + "\n\n" + _summary_block
    return f"Report saved: {report_path}\n\n{_summary_block}"


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


# ── B. Jinja-first narrative rendering (2026-05-12) ────────────────────
#
# Deterministic alternative to LLM-rendered prose. Opt-in via profile
# frontmatter `narrative_mode: jinja`. Two runs over identical findings
# JSON produce byte-identical reports (modulo the timestamp in the file
# name itself) — required for archived audits / digital signatures /
# regression diffs.
_SEVERITY_ICON = {"critical": "🔴", "warning": "⚠️", "info": "✅"}


def _render_section_jinja(job_name: str, job_data: dict, lang: str = "en") -> str:
    """Deterministic per-section render: heading + findings table + 1-line
    summary of severity counts. No LLM call."""
    findings = job_data.get("findings", []) or []
    if not findings:
        return _empty_section(job_name, lang)

    _hidden = {"severity_hint", "_source", "_warning"}
    columns: list[str] = []
    for f in findings:
        if not isinstance(f, dict):
            continue
        for k in f.keys():
            if k.startswith("_") or k in _hidden:
                continue
            if k not in columns:
                columns.append(k)
    if not columns:
        columns = ["device"]

    pinned = [c for c in ("device", "device_name", "interface",
                          "metric_name", "metric_value") if c in columns]
    rest = sorted(c for c in columns if c not in pinned)
    columns = pinned + rest

    header_label = {"zh": "严重度", "en": "Severity"}.get(lang, "Severity")
    header_cells = list(columns) + [header_label]
    lines = [f"## {job_name}", "", "| " + " | ".join(header_cells) + " |",
             "| " + " | ".join(["---"] * len(header_cells)) + " |"]
    crit = warn = info = 0
    for f in findings:
        if not isinstance(f, dict):
            continue
        hint = (f.get("severity_hint") or "info").lower()
        if hint == "critical":
            crit += 1
        elif hint == "warning":
            warn += 1
        else:
            info += 1
        cells = [str(f.get(c, "")) for c in columns]
        cells.append(f"{_SEVERITY_ICON.get(hint, '·')} {hint.capitalize()}")
        lines.append("| " + " | ".join(cells) + " |")

    if lang == "zh":
        tally = f"\n本节统计：{crit} 严重 / {warn} 警告 / {info} 信息。"
    else:
        tally = f"\nSection tally: {crit} Critical / {warn} Warning / {info} Info."
    lines.append(tally)
    lines.append("")
    return "\n".join(lines) + "\n"


def _render_executive_summary_jinja(
    audit_json: dict, profile_cfg: dict, lang: str
) -> str:
    """Deterministic executive summary: severity tallies + top-N action
    items + verdict line. No LLM call."""
    crit_findings: list[tuple] = []
    warn_findings: list[tuple] = []
    for job_name, job_data in audit_json.get("jobs", {}).items():
        for f in job_data.get("findings", []) or []:
            if not isinstance(f, dict):
                continue
            hint = (f.get("severity_hint") or "").lower()
            if hint == "critical":
                crit_findings.append((job_name, f))
            elif hint == "warning":
                warn_findings.append((job_name, f))
    freshness = audit_json.get("freshness_warning")
    fresh_present = isinstance(freshness, dict) and bool(freshness)

    def _device_key(item):
        f = item[1]
        return ((f.get("device") or f.get("device_name") or ""), item[0])
    crit_findings.sort(key=_device_key)
    warn_findings.sort(key=_device_key)

    if fresh_present:
        verdict = "🔴 Critical (unverified)" if crit_findings else "⚠️ At Risk (stale data)"
        verdict_zh = "🔴 严重（数据未验证）" if crit_findings else "⚠️ 风险（数据陈旧）"
    elif crit_findings:
        verdict = "🔴 Critical"
        verdict_zh = "🔴 严重"
    elif warn_findings:
        verdict = "⚠️ At Risk"
        verdict_zh = "⚠️ 风险"
    else:
        verdict = "✅ Healthy"
        verdict_zh = "✅ 健康"

    lines: list[str] = ["## Executive Summary", ""]
    if lang == "zh":
        lines.append(
            f"本次审计共发现 {len(crit_findings)} 项严重、{len(warn_findings)} 项警告。"
        )
        if fresh_present:
            lines.append("⚠️ 数据陈旧——下列发现仅反映陈旧快照，无法证明当前网络状态。")
        lines.append("")
        lines.append("**优先处理项**")
    else:
        lines.append(
            f"This audit surfaced {len(crit_findings)} Critical and "
            f"{len(warn_findings)} Warning finding(s)."
        )
        if fresh_present:
            lines.append(
                "⚠️ Data is stale — findings reflect the captured snapshot, "
                "NOT the current network state."
            )
        lines.append("")
        lines.append("**Prioritized Action Items**")

    items: list[str] = []
    if fresh_present:
        hrs = freshness.get("max_hours_since_last_seen", "?")
        if lang == "zh":
            items.append(f"1. 🔴 全局——数据已陈旧 {hrs}h——恢复采集 / 重新跑快照。")
        else:
            items.append(f"1. 🔴 Global — Stale data ({hrs}h) — restore data collection / re-run snapshot.")
    seen_devices: set = set()
    rank = len(items) + 1
    for job_name, f in crit_findings:
        if rank > 3:
            break
        dev = f.get("device") or f.get("device_name") or "?"
        if dev in seen_devices:
            continue
        seen_devices.add(dev)
        metric = f.get("metric_name", job_name)
        val = f.get("metric_value", "")
        if lang == "zh":
            items.append(f"{rank}. 🔴 {dev} — {metric}={val} — 请按 {job_name} 章节调查。")
        else:
            items.append(f"{rank}. 🔴 {dev} — {metric}={val} — investigate per {job_name}.")
        rank += 1
    for job_name, f in warn_findings:
        if rank > 3:
            break
        dev = f.get("device") or f.get("device_name") or "?"
        if dev in seen_devices:
            continue
        seen_devices.add(dev)
        metric = f.get("metric_name", job_name)
        val = f.get("metric_value", "")
        if lang == "zh":
            items.append(f"{rank}. ⚠️ {dev} — {metric}={val} — 请按 {job_name} 章节复核。")
        else:
            items.append(f"{rank}. ⚠️ {dev} — {metric}={val} — review per {job_name}.")
        rank += 1
    if not items:
        items.append(
            "✅ No action items required for this inspection window."
            if lang != "zh" else "✅ 本次审计无需处理。"
        )
    lines.extend(items)
    lines.append("")
    if lang == "zh":
        lines.append(f"**网络健康**：{verdict_zh}")
    else:
        lines.append(f"**Network Health**: {verdict}")
    lines.append("")
    lines.append("---")
    return "\n".join(lines) + "\n"


def _post_critical_alert(
    audit_json: dict,
    profile_name: str,
    report_path: str,
    executive_summary: str,
) -> None:
    """ISSUE-AUDIT-NO-ALERTING-CHANNEL (P2, 2026-05-12).

    POST a JSON payload to ``OLAV_ALERT_WEBHOOK_URL`` when the audit
    contains at least one Critical finding (or stale-data warning).
    Payload format is webhook-receiver-agnostic — the caller chooses
    whether to translate to PagerDuty / Slack / Discord on the receiver
    side.

    Behaviour:
      * No webhook URL → no-op (returns silently).
      * No Critical / stale-data signal → no-op (avoids noise).
      * Webhook 4xx/5xx / timeout → logged, NOT raised. The audit's
        local .md report still gets produced.

    Threshold knob: ``OLAV_ALERT_SEVERITY`` env var; one of
    ``critical`` (default) / ``warning`` / ``info``. Anything ≥ the
    threshold triggers a POST.
    """
    import os
    webhook_url = os.environ.get("OLAV_ALERT_WEBHOOK_URL", "").strip()
    if not webhook_url:
        return  # not configured

    threshold = os.environ.get("OLAV_ALERT_SEVERITY", "critical").strip().lower()
    severity_rank = {"info": 0, "warning": 1, "critical": 2}
    threshold_rank = severity_rank.get(threshold, 2)

    # Collect severities present in findings.
    max_severity_rank = -1
    critical_findings: list[dict] = []
    warning_findings: list[dict] = []
    for job_name, job_data in audit_json.get("jobs", {}).items():
        for finding in job_data.get("findings", []) or []:
            if not isinstance(finding, dict):
                continue
            hint = (finding.get("severity_hint") or "").lower()
            rank = severity_rank.get(hint, -1)
            if rank > max_severity_rank:
                max_severity_rank = rank
            if hint == "critical":
                critical_findings.append({"job": job_name, **finding})
            elif hint == "warning":
                warning_findings.append({"job": job_name, **finding})

    freshness = audit_json.get("freshness_warning")
    has_freshness_critical = isinstance(freshness, dict) and bool(freshness)

    if max_severity_rank < threshold_rank and not has_freshness_critical:
        return  # nothing to alert on

    # ── Webhook dedup (2026-05-12 follow-up) ─────────────────────────
    # Compute a stable fingerprint over (profile, set-of-critical-
    # (device, metric_name) tuples, freshness_present). Identical
    # critical conditions in the same dedup window → swallow the POST
    # to prevent alert fatigue. Window default 3600s; override via
    # ``OLAV_ALERT_DEDUP_WINDOW_SECONDS=0`` to disable, or any positive
    # int to tune.
    dedup_window = int(os.environ.get("OLAV_ALERT_DEDUP_WINDOW_SECONDS", "3600"))
    state_path = Path(report_path).parent / ".audit_alert_state.json"
    fingerprint = _alert_fingerprint(
        profile_name=profile_name,
        critical_findings=critical_findings,
        freshness_present=has_freshness_critical,
    )
    if dedup_window > 0 and _is_duplicate_alert(state_path, fingerprint, dedup_window):
        logger.info(
            "render_report: alert webhook SKIPPED (dedup, profile=%s, "
            "fingerprint=%s..., window=%ds)",
            profile_name, fingerprint[:12], dedup_window,
        )
        return

    payload = {
        "profile": profile_name,
        "report_path": report_path,
        "generated_at": audit_json.get("generated_at"),
        "freshness_warning": freshness,
        "executive_summary": executive_summary[:4000],
        "critical_count": len(critical_findings),
        "warning_count": len(warning_findings),
        "critical_findings": critical_findings[:20],  # cap to keep payload small
        "fingerprint": fingerprint,
    }
    try:
        import urllib.request
        import json as _json
        req = urllib.request.Request(
            webhook_url,
            data=_json.dumps(payload, default=str).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=5) as resp:
            logger.info(
                "render_report: alert webhook → HTTP %d (profile=%s)",
                resp.status, profile_name,
            )
        # Record the successful send for future dedup checks.
        if dedup_window > 0:
            _record_alert_sent(state_path, fingerprint, profile_name)
    except Exception as exc:
        # Webhook is best-effort; never block the audit.
        logger.warning(
            "render_report: alert webhook POST failed (profile=%s): %s: %s",
            profile_name, type(exc).__name__, exc,
        )


def _alert_fingerprint(
    profile_name: str,
    critical_findings: list[dict],
    freshness_present: bool,
) -> str:
    """Stable hash over the dedup-relevant audit signal.

    Uses (profile_name, sorted set of (device, metric_name) tuples,
    freshness_present). Deliberately excludes: timestamps, exact
    counter values, executive_summary prose — those rotate every run
    even when the underlying condition is unchanged.
    """
    import hashlib
    keys = sorted({
        (
            (f.get("device") or f.get("device_name") or ""),
            (f.get("metric_name") or f.get("job") or ""),
        )
        for f in critical_findings
        if isinstance(f, dict)
    })
    payload = f"{profile_name}|{keys}|fresh={int(freshness_present)}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_duplicate_alert(state_path: Path, fingerprint: str, window_seconds: int) -> bool:
    """Return True if this fingerprint was sent within window_seconds."""
    import json as _json
    if not state_path.exists():
        return False
    try:
        state = _json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return False
    entry = state.get(fingerprint)
    if not isinstance(entry, dict):
        return False
    last_sent = entry.get("last_sent")
    if not last_sent:
        return False
    try:
        last_dt = datetime.fromisoformat(last_sent)
    except Exception:
        return False
    now = datetime.now(tz=UTC)
    return (now - last_dt).total_seconds() < window_seconds


def _record_alert_sent(state_path: Path, fingerprint: str, profile_name: str) -> None:
    """Persist a successful alert send so the next run can dedup."""
    import json as _json
    state: dict = {}
    if state_path.exists():
        try:
            state = _json.loads(state_path.read_text(encoding="utf-8"))
        except Exception:
            state = {}
    now_iso = datetime.now(tz=UTC).isoformat()
    entry = state.get(fingerprint) or {}
    entry["last_sent"] = now_iso
    if "first_sent" not in entry:
        entry["first_sent"] = now_iso
    entry["sent_count"] = int(entry.get("sent_count", 0)) + 1
    entry["profile"] = profile_name
    state[fingerprint] = entry
    # Prune entries older than 14 days to keep the file bounded.
    cutoff = datetime.now(tz=UTC) - timedelta(days=14)
    state = {
        k: v for k, v in state.items()
        if not v.get("last_sent")
        or _safe_fromisoformat(v["last_sent"]) > cutoff
    }
    try:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(_json.dumps(state, indent=2), encoding="utf-8")
    except Exception as exc:
        logger.warning(
            "render_report: failed to persist alert state %s: %s",
            state_path, exc,
        )


def _safe_fromisoformat(s: str) -> datetime:
    """Parse ISO timestamps with tolerance; fall back to epoch on failure."""
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return datetime.fromtimestamp(0, tz=UTC)


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

_render_report_tool = StructuredTool.from_function(
    render_report,
    # Terminal tool: the return string IS the final user-facing reply
    # (report path + executive summary). With return_direct=True langgraph
    # exits the agent loop after this tool call instead of doing a second
    # LLM round-trip to "format the response" — which on small models
    # (gemma4) reliably caused 2-3× paraphrase duplication of the same
    # executive summary. See dev_docs/00 (verbatim-passthrough fix, 2026-05-12).
    return_direct=True,
)
