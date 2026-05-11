"""Atomic CAB lab validation pipeline (Patch L).

Folds the 5+ step lab validation flow into a single composite call so
the lab agent makes ONE skill_script invocation instead of orchestrating
each step itself.  Solves ISSUE-CAB-AGENT-DRIVEN-LAB-VALIDATION-LOOPS:
small models stuck in the multi-step decision loop spent 12+ minutes
on tcf_load_for_lab alone before the runner timed out.

Phases (each phase failure short-circuits to ``destroy``):

    0. load      — tcf_load_for_lab(spec_path)
    1. topology  — generate_clab_topology(**r88_args)
    2. srl       — generate_srl_lab_config(**r89_args)
    3. save      — save_lab_config per node
    4. deploy    — deploy_and_push_lab
    5. verify    — exec each post_check, match against expected_pattern
    6. record    — tcf_record_lab_run with verdict + journal + step verdicts
    7. destroy   — destroy_lab (always attempted, even on phase failure)

Returns one envelope with all evidence.  Caller never has to thread
intermediate results between calls.
"""

from __future__ import annotations

import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .tcf_io import tcf_load
from .tcf_lab import tcf_load_for_lab, tcf_record_lab_run


def _resolve_spec_path(spec_path: str | Path) -> Path:
    """Best-effort resolve a TCF spec path that may have been mangled
    by a weak LLM agent.

    Patch D' Step 6 (2026-05-08): gemma4 nothink reliably turns a
    relative ``exports/cab/<id>/spec.tcf.yaml`` into an absolute
    ``/exports/cab/<id>/spec.tcf.yaml`` in tool args.  The caller's
    intent is the file under cwd, but the mangled absolute path
    doesn't exist.  Resolve by trying multiple candidates:

      1. As-given (Path constructor)
      2. If absolute and missing, strip the leading ``/`` and re-resolve
         relative to cwd
      3. If still missing, try relative to ``OLAV_HOME`` env var

    Returns the FIRST candidate that exists; otherwise returns
    Path(spec_path) (caller surfaces FileNotFoundError as before so
    error envelope stays informative).
    """
    p = Path(spec_path)
    if p.exists():
        return p

    # LLM-mangling fallback: absolute path with leading /, missing on disk
    sp = str(spec_path)
    if sp.startswith("/"):
        rel = Path(sp.lstrip("/"))
        if rel.exists():
            return rel
        # Also try cwd-relative
        cwd_rel = Path.cwd() / sp.lstrip("/")
        if cwd_rel.exists():
            return cwd_rel

    # OLAV_HOME-rooted fallback for fully-relative paths
    import os
    olav_home = os.environ.get("OLAV_HOME")
    if olav_home:
        rooted = Path(olav_home) / sp.lstrip("/")
        if rooted.exists():
            return rooted

    return p


_REGEX_METACHAR_HINT = re.compile(r"\\[sdwbDSW]|\.\*|\.\+|\[\^?")


def _looks_like_regex(pattern: str) -> bool:
    """Heuristic: pattern contains regex metacharacters that would be
    interpreted literally by substring match (``.*``, ``\\s``, ``\\d``,
    character classes).  Used to forgive analyzer-emitted patterns
    that omit the ``re:`` prefix — common because LLM sim agents
    write regex-style patterns naturally."""
    return bool(_REGEX_METACHAR_HINT.search(pattern))


def _match_pattern(actual: str, expected: str) -> bool:
    """Per PostCheck schema: bare string → substring match (case-insensitive),
    ``re:<regex>`` prefix → regex match.  Patch M+N: also auto-detect
    bare patterns that contain regex metacharacters and try regex
    matching as a fallback (sim agents often emit ``a.*b.*c`` without
    the ``re:`` prefix, expecting it to match — this fallback keeps
    those specs working without forcing a sim-side rewrite).
    """
    if not isinstance(actual, str):
        return False
    if expected.startswith("re:"):
        try:
            return bool(re.search(expected[3:], actual, re.I | re.M))
        except re.error:
            return False
    # Substring (canonical bare-pattern semantics)
    if expected.lower() in actual.lower():
        return True
    # Forgiving regex fallback when the bare pattern looks like a regex
    if _looks_like_regex(expected):
        try:
            return bool(re.search(expected, actual, re.I | re.M))
        except re.error:
            return False
    return False


def _exec_check(
    lab_name: str,
    lab_node: str,
    command: str,
    *,
    timeout: float,
) -> dict[str, Any]:
    """Run one post_check command on a CLAB node — same wrapping as
    the ``exec_on_node`` @tool (sr_cli auto-wrapping with base64 stdin).
    """
    import base64 as _b64

    from olav.platform.services.client import service_call

    container = f"clab-{lab_name}-{lab_node}"
    cmd = command.strip()
    if cmd.startswith("sr_cli") and not cmd.startswith("bash -c"):
        m = re.match(r"""^sr_cli\s+(?:-c\s+)?['"](.*)['"]\s*$""", cmd, re.DOTALL)
        srl_content = m.group(1) if m else re.sub(r"^sr_cli\s+(?:-c\s+)?", "", cmd)
        b64 = _b64.b64encode((srl_content.strip() + "\n").encode()).decode()
        cmd = f"bash -c 'echo {b64} | base64 -d | sr_cli 2>&1'"

    body = service_call(
        "containerlab",
        method="POST",
        path=f"/api/v1/labs/{lab_name}/exec",
        params={"nodeFilter": container},
        body={"command": cmd},
        confirmed=True,
        timeout=float(timeout),
    )

    if isinstance(body, dict):
        node_results = body.get(container, body.get(lab_node, []))
        if isinstance(node_results, list) and node_results:
            r = node_results[0]
            return {
                "stdout": r.get("stdout", ""),
                "stderr": r.get("stderr", ""),
                "return_code": r.get("return-code", 0),
            }
    return {"stdout": str(body), "stderr": "", "return_code": 0}


def validate_tcf_in_lab(
    spec_path: str | Path,
    *,
    destroy_on_finish: bool = True,
    skip_record: bool = False,
    exec_timeout: float = 30.0,
    deploy_wait_seconds: int = 40,
    post_commit_wait_seconds: int = 30,
    convergence_wait_seconds: int = 5,
) -> dict[str, Any]:
    """Run the full CAB lab validation pipeline atomically.

    Args:
        spec_path: Path to the TCF spec yaml.
        destroy_on_finish: Tear down the CLAB lab when done (default True).
            Set False for debugging — caller must destroy manually.
        skip_record: Don't write verdict + journal back to the TCF spec.
            Useful for dry-run / probe modes.
        exec_timeout: Per-post_check exec timeout.
        deploy_wait_seconds: First-deploy wait passed to ``deploy_and_push_lab``.
        post_commit_wait_seconds: Post-config-commit settle passed to
            ``deploy_and_push_lab``.
        convergence_wait_seconds: Extra grace before running post_checks
            (BGP/OSPF still converging after the post_commit_wait).

    Returns: envelope with
        ``status`` (ok / error), ``phase`` (which phase failed if error),
        ``verdict`` (PASS / FAIL — only present when at least the
        deploy + verify phases ran), ``lab_name``, ``spec_path``,
        ``post_check_results`` (list of per-check dicts with ``passed``,
        ``actual``, ...), ``tvt_results`` (matched by check_id ↔ test_id),
        ``journal`` (list of phase records), ``tcf_recorded``,
        ``lab_destroyed``, ``errors`` (cumulative non-fatal warnings).
    """
    spec_path = _resolve_spec_path(spec_path)
    journal: list[dict[str, Any]] = []
    errors: list[str] = []
    lab_name = ""
    lab_destroyed = False
    deploy_was_attempted = False

    def _journal(step: str, phase: str, args: dict, summary: dict) -> None:
        journal.append({
            "step": step,
            "args": args,
            "result_summary": {**summary, "phase": phase},
            "timestamp": datetime.now(UTC).isoformat(),
        })

    def _attempt_destroy() -> None:
        nonlocal lab_destroyed
        if not destroy_on_finish or not lab_name or not deploy_was_attempted:
            return
        try:
            from olav.core.lab.deploy_io import destroy_lab
            d = destroy_lab(lab_name, timeout=exec_timeout)
            lab_destroyed = bool(d.get("destroyed") or d.get("status") == "ok")
            _journal("destroy_lab", "destroy", {"lab_name": lab_name},
                     {"destroyed": lab_destroyed})
        except Exception as exc:  # noqa: BLE001
            errors.append(f"destroy_lab failed: {type(exc).__name__}: {exc}")

    # ── Phase 0: load ─────────────────────────────────────────────────
    loaded = tcf_load_for_lab(spec_path)
    if loaded.get("status") != "ok":
        return {
            "status": "error",
            "phase": "load",
            "error": loaded.get("error", "tcf_load_for_lab failed"),
            "spec_path": str(spec_path),
            "journal": journal,
            "errors": errors,
            "tcf_recorded": False,
            "lab_destroyed": False,
        }
    r88_args = loaded["r88_args"]
    r89_args = loaded["r89_args"]
    lab_name = r88_args["lab_name"]
    pre_check_specs = loaded.get("pre_check", [])
    post_check_specs = loaded["post_check"]
    tvt_specs = loaded["tvt"]
    # Patch M needs the full CabTcf for prod→lab IP map (implementation
    # CLI lines aren't part of the tcf_load_for_lab envelope).
    tcf_full = tcf_load(spec_path)
    _journal("tcf_load_for_lab", "load",
             {"spec_path": str(spec_path)},
             {"change_id": loaded["change_id"], "lab_name": lab_name})

    # freeform_cli: skip R89, use prose-mode LLM translator instead
    # (2026-05-11, post rev 247 — see freeform_translator.py for the
    # empirical motivation: tool-calling channel cannot produce raw
    # SRL text; isolated single-turn prose call can).
    use_freeform_translator = (
        r89_args is None
        and tcf_full.intent.type == "freeform_cli"
    )
    if r89_args is None and not use_freeform_translator:
        msg = loaded.get("r89_error", "intent not supported by R89")
        return {
            "status": "error", "phase": "load", "error": msg,
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": False,
        }

    # ── Phase 1: topology (R88-A) ─────────────────────────────────────
    try:
        from olav.core.lab.topology import generate_clab_topology
        yaml_content = generate_clab_topology(**r88_args)
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "topology",
            "error": f"generate_clab_topology failed: {exc}",
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    if yaml_content.lstrip().startswith("# ERROR"):
        _attempt_destroy()
        return {
            "status": "error", "phase": "topology",
            "error": yaml_content.split("\n", 1)[0],
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("generate_clab_topology", "topology", r88_args,
             {"yaml_lines": len(yaml_content.splitlines())})

    # ── Phase 2: SRL render — R89 (ebgp_direct) OR prose translator (freeform_cli) ──
    configs: dict[str, list[str]] = {}
    if use_freeform_translator:
        from olav.core.cab.freeform_translator import translate_prod_cli_to_srl
        from olav.core.cab.postcheck_translate import build_prod_to_lab_ip_map

        # Build prod→lab IP map for freeform_cli (mimics what Patch M
        # does for ebgp_direct via r89_args). Synthesise the required
        # args from r88 + intent so the existing helper can run.
        # 2026-05-11 (rev 252): fixes ISSUE-CAB-FREEFORM-PROD-IP-LEAK —
        # prod IPs (10.1.13.x) referenced in sim's CLI must be substituted
        # for the device's actual lab IP (e.g. 192.0.2.61) before the SRL
        # config is pushed, otherwise next-hops are unreachable in lab.
        intent_extras = tcf_full.intent.model_dump()
        lab_subnet_for_map = (
            intent_extras.get("lab_subnet")
            or r88_args.get("lab_subnet")
            or "172.16.99.0/30"
        )

        # Compute lab IPs per node from lab_subnet (mimics R89 allocation).
        import ipaddress as _ipaddr
        import re as _re
        try:
            _net = _ipaddr.ip_network(lab_subnet_for_map, strict=False)
            _hosts = [str(h) for h in _net.hosts()]
        except Exception:
            _hosts = []
        _device_names = [d.name for d in tcf_full.devices]
        lab_ip_by_node: dict[str, str] = {}
        for idx, name in enumerate(_device_names):
            if idx < len(_hosts):
                lab_ip_by_node[name] = _hosts[idx]

        # Loopbacks survive verbatim (R89/SRL reuses prod loopback as system0)
        loopbacks: set[str] = set()
        for d in tcf_full.devices:
            if getattr(d, "prod_loopback", None):
                loopbacks.add(str(d.prod_loopback))

        # Scan each device's CLI for IPv4 literals in NEXT-HOP /
        # NEIGHBOR / INTERFACE-ADDRESS context only. Destination
        # prefixes (e.g. `route 192.0.2.0/24`) are NOT mapped — the
        # destination network stays the same in prod and lab.
        # Patterns matched (IP captured as group 1):
        #   IOS:    "ip address <IP> <MASK>"
        #   IOS:    "ip route <PFX> <MASK> <NEXTHOP>"
        #   IOS:    "neighbor <IP> remote-as ..."
        #   Junos:  "next-hop <IP>"
        #   Junos:  "address <IP>/<MASK>"
        #   Junos:  "peer-address <IP>"
        _IPCTX_PATTERNS = [
            # IOS "ip route X Y NEXTHOP" — captures NEXTHOP only
            _re.compile(
                r"\bip\s+route\s+\d+\.\d+\.\d+\.\d+\s+\d+\.\d+\.\d+\.\d+\s+"
                r"(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
            ),
            # IOS "neighbor X remote-as Y"
            _re.compile(
                r"\bneighbor\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
            ),
            # Junos / SRL "next-hop X"
            _re.compile(
                r"\bnext-hop\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
            ),
            # Junos / SRL "peer-address X" / "peer X"
            _re.compile(
                r"\b(?:peer-address|peer)\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\b"
            ),
            # "ip address X Y" (IOS interface)
            _re.compile(
                r"\bip\s+address\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})\s+\d+\.\d+\.\d+\.\d+"
            ),
            # Junos "address X/MASK"
            _re.compile(
                r"\baddress\s+(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})/\d{1,2}\b"
            ),
        ]
        freeform_ip_map: dict[str, str] = {}
        impl_by_device: dict[str, list[str]] = {}
        for impl in tcf_full.implementation:
            impl_by_device.setdefault(impl.device, []).extend(
                impl.cli if isinstance(impl.cli, list) else [impl.cli]
            )

        if len(_device_names) == 2 and len(lab_ip_by_node) == 2:
            a, b = _device_names[0], _device_names[1]
            peer_lab = {a: lab_ip_by_node[b], b: lab_ip_by_node[a]}
            for name in _device_names:
                for ln in impl_by_device.get(name, []):
                    if not isinstance(ln, str):
                        continue
                    # Collect IPs only from next-hop/neighbor/address
                    # contexts (skip destination prefixes).
                    for pat in _IPCTX_PATTERNS:
                        for ip in pat.findall(ln):
                            if ip in loopbacks:
                                continue
                            if ip in freeform_ip_map:
                                continue
                            try:
                                obj = _ipaddr.IPv4Address(ip)
                                if obj.is_multicast or obj.is_unspecified or obj.is_reserved:
                                    continue
                            except ValueError:
                                continue
                            freeform_ip_map[ip] = peer_lab[name]
        # For 1-device or >2-device specs, fall back to the
        # interface-aware Patch M helper (handles ip-address /
        # subinterface-style CLI better).
        elif len(_device_names) >= 1:
            try:
                freeform_ip_map = build_prod_to_lab_ip_map(
                    tcf_full,
                    {"nodes": _device_names, "lab_subnet": lab_subnet_for_map},
                )
            except Exception:  # noqa: BLE001
                freeform_ip_map = {}

        def _substitute_ips(lines: list[str]) -> list[str]:
            if not freeform_ip_map:
                return lines
            out: list[str] = []
            for ln in lines:
                if not isinstance(ln, str):
                    out.append(ln)
                    continue
                replaced = ln
                # Replace longest IPs first to avoid prefix collisions.
                for prod_ip in sorted(freeform_ip_map, key=len, reverse=True):
                    if prod_ip in replaced:
                        replaced = replaced.replace(prod_ip, freeform_ip_map[prod_ip])
                out.append(replaced)
            return out

        # Compute lab subnet prefix-length for base interface config.
        _net_for_mask = _ipaddr.ip_network(lab_subnet_for_map, strict=False)
        _prefixlen = _net_for_mask.prefixlen

        def _base_srl_lines(node_name: str) -> list[str]:
            """Base SRL config a freeform_cli change relies on: link
            interface with the device's lab IP + system0 loopback +
            interface placed in default network-instance. Mirrors what
            R89 builds for ebgp_direct so static routes / OSPF
            adjacencies on top of it actually resolve in lab.

            2026-05-11 (rev 252 follow-up): R88 only sets up empty
            SRL containers with L2 links; without this base block
            the translator's CLI (e.g. static route next-hop) has
            no IP-layer foundation and the route fails to install.
            """
            lab_ip = lab_ip_by_node.get(node_name)
            if not lab_ip:
                return []
            lo = ""
            for d in tcf_full.devices:
                if d.name == node_name and getattr(d, "prod_loopback", None):
                    lo = str(d.prod_loopback)
                    break
            lines = [
                "enter candidate",
                "set / interface ethernet-1/1 admin-state enable",
                "set / interface ethernet-1/1 subinterface 0 admin-state enable",
                "set / interface ethernet-1/1 subinterface 0 ipv4 admin-state enable",
                f"set / interface ethernet-1/1 subinterface 0 ipv4 address {lab_ip}/{_prefixlen}",
            ]
            if lo:
                lines += [
                    "set / interface system0 admin-state enable",
                    "set / interface system0 subinterface 0 admin-state enable",
                    "set / interface system0 subinterface 0 ipv4 admin-state enable",
                    f"set / interface system0 subinterface 0 ipv4 address {lo}/32",
                ]
            lines += [
                "set / network-instance default type default",
                "set / network-instance default interface ethernet-1/1.0",
            ]
            if lo:
                lines.append("set / network-instance default interface system0.0")
            lines.append("commit save")
            return lines

        translation_summaries: dict[str, dict] = {}
        for dev in tcf_full.devices:
            # Find implementation CLI for this device
            dev_cli: list[str] = []
            for impl in tcf_full.implementation:
                if impl.device == dev.name:
                    dev_cli.extend(impl.cli if isinstance(impl.cli, list) else [impl.cli])
            if not dev_cli:
                _attempt_destroy()
                return {
                    "status": "error", "phase": "translate",
                    "error": f"no implementation CLI for device {dev.name!r}",
                    "spec_path": str(spec_path), "lab_name": lab_name,
                    "journal": journal, "errors": errors,
                    "tcf_recorded": False, "lab_destroyed": lab_destroyed,
                }
            # Substitute prod IPs → lab IPs BEFORE handing to LLM
            dev_cli_lab = _substitute_ips(dev_cli)
            # Pass loopback IP + peer loopbacks as extra context so the
            # translator can resolve placeholder slots (e.g. iBGP rule's
            # <LOCAL_LOOPBACK>, <ROUTER_ID>) when the source CLI only
            # mentions them by interface name (`update-source Loopback0`).
            extra_ctx_lines: list[str] = []
            own_lo = getattr(dev, "prod_loopback", None)
            if own_lo:
                extra_ctx_lines.append(
                    f"This device's loopback IP (use as <LOCAL_LOOPBACK> "
                    f"or <ROUTER_ID>): {own_lo}"
                )
            for other in tcf_full.devices:
                if other.name != dev.name and getattr(other, "prod_loopback", None):
                    extra_ctx_lines.append(
                        f"Peer device {other.name}'s loopback IP: {other.prod_loopback}"
                    )
            extra_ctx = "\n".join(extra_ctx_lines)
            result = translate_prod_cli_to_srl(
                dev_cli_lab, dev.platform or "unknown",
                extra_context=extra_ctx,
            )
            translation_summaries[dev.name] = {
                "status": result["status"],
                "elapsed_s": result.get("elapsed_s"),
                "model": result.get("model"),
                "validation_reason": result.get("validation_reason"),
            }
            if result["status"] != "ok":
                _attempt_destroy()
                return {
                    "status": "error", "phase": "translate",
                    "error": (
                        f"freeform_cli translation failed for {dev.name!r}: "
                        f"{result.get('error')} ({result.get('validation_reason', '')})"
                    ),
                    "spec_path": str(spec_path), "lab_name": lab_name,
                    "journal": journal, "errors": errors,
                    "tcf_recorded": False, "lab_destroyed": lab_destroyed,
                    "translation_summaries": translation_summaries,
                }
            # Lab node name = lowercased prod hostname
            # Prepend base config (interface IPs + loopback + network-
            # instance attach) so the translator's change CLI has
            # IP-layer foundation to operate on.
            base = _base_srl_lines(dev.name)
            srl_change = result["srl_lines"]
            # Strip the change block's leading "enter candidate" /
            # trailing "commit save" if base already wraps it — keep
            # only one commit at the end.
            srl_change_inner = [
                ln for ln in srl_change
                if ln.strip().lower() not in ("enter candidate", "commit save")
            ]
            combined = base[:-1] + srl_change_inner + ["commit save"] if base else srl_change
            configs[dev.name.lower()] = combined
        _journal("freeform_translator", "translate",
                 {"devices": [d.name for d in tcf_full.devices]},
                 {"summaries": translation_summaries,
                  "lines_per_node": {n: len(c) for n, c in configs.items()}})
    else:
        try:
            from olav.core.lab.srl_render import generate_srl_lab_config
            srl_raw = generate_srl_lab_config(**r89_args)
            srl_result = json.loads(srl_raw)
        except Exception as exc:  # noqa: BLE001
            _attempt_destroy()
            return {
                "status": "error", "phase": "srl",
                "error": f"generate_srl_lab_config failed: {exc}",
                "spec_path": str(spec_path), "lab_name": lab_name,
                "journal": journal, "errors": errors,
                "tcf_recorded": False, "lab_destroyed": lab_destroyed,
            }
        if srl_result.get("status") != "ok":
            _attempt_destroy()
            return {
                "status": "error", "phase": "srl",
                "error": srl_result.get("error", "SRL render failed"),
                "spec_path": str(spec_path), "lab_name": lab_name,
                "journal": journal, "errors": errors,
                "tcf_recorded": False, "lab_destroyed": lab_destroyed,
            }
        configs = srl_result["configs"]  # dict[lab_node, list[str]]
        _journal("generate_srl_lab_config", "srl", r89_args,
                 {"nodes": list(configs.keys()),
                  "lines_per_node": {n: len(c) for n, c in configs.items()}})

    # ── Phase 3: save_lab_config per node ─────────────────────────────
    try:
        from olav.core.lab.deploy_io import save_lab_config
        for lab_node, cfg_lines in configs.items():
            lines = cfg_lines if isinstance(cfg_lines, list) else \
                str(cfg_lines).splitlines()
            r = save_lab_config(lab_name, lab_node, lines)
            if not r.get("saved"):
                raise RuntimeError(
                    f"save_lab_config({lab_node}) failed: {r.get('error')}"
                )
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "save",
            "error": str(exc),
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("save_lab_config", "save", {"nodes": list(configs.keys())},
             {"saved": len(configs)})

    # ── Phase 4: deploy_and_push_lab ──────────────────────────────────
    deploy_was_attempted = True
    try:
        from olav.core.lab.deploy_and_push import deploy_and_push_lab
        deploy_result = deploy_and_push_lab(
            lab_name=lab_name,
            yaml_content=yaml_content,
            configs={},  # empty → auto-load from save_lab_config dropbox
            wait_seconds=deploy_wait_seconds,
            post_commit_wait_seconds=post_commit_wait_seconds,
        )
    except Exception as exc:  # noqa: BLE001
        _attempt_destroy()
        return {
            "status": "error", "phase": "deploy",
            "error": f"deploy_and_push_lab raised: {exc}",
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }

    if isinstance(deploy_result, str):
        try:
            deploy_result = json.loads(deploy_result)
        except json.JSONDecodeError:
            deploy_result = {"raw": deploy_result}

    if not deploy_result.get("deployed") and not deploy_result.get("lab_reused"):
        _attempt_destroy()
        return {
            "status": "error", "phase": "deploy",
            "error": "deploy_and_push_lab did not deploy or reuse lab",
            "deploy_result": deploy_result,
            "spec_path": str(spec_path), "lab_name": lab_name,
            "journal": journal, "errors": errors,
            "tcf_recorded": False, "lab_destroyed": lab_destroyed,
        }
    _journal("deploy_and_push_lab", "deploy",
             {"lab_name": lab_name, "yaml_lines": len(yaml_content.splitlines())},
             {"deployed": deploy_result.get("deployed", False),
              "committed": deploy_result.get("committed", False),
              "lab_reused": deploy_result.get("lab_reused", False)})

    if convergence_wait_seconds > 0:
        time.sleep(convergence_wait_seconds)

    # ── Phase 5: verify each post_check (with Patch M prod→SRL xlation) ──
    from .postcheck_translate import (
        build_prod_to_lab_ip_map,
        translate_post_check,
    )

    # For freeform_cli (r89_args is None), reuse the same prod→lab IP
    # map we built earlier in the freeform translator branch so
    # post_check patterns referencing prod IPs (e.g. "next-hop 10.1.13.1")
    # are translated to the lab equivalent. Patch M handles this for
    # ebgp_direct via r89_args; freeform branch builds it from
    # tcf_full.intent.lab_subnet + device list.
    if r89_args:
        ip_map = build_prod_to_lab_ip_map(tcf_full, r89_args)
    elif use_freeform_translator:
        ip_map = locals().get("freeform_ip_map", {})
    else:
        ip_map = {}
    _journal("translate_post_checks", "verify",
             {"prod_ip_count": len(ip_map)},
             {"ip_map": ip_map, "phase": "verify-prep"})

    # ── Phase 4.5: pre_check evaluation (ARCH-34) ─────────────────────
    # Lab semantics for pre_check: informational. The lab is freshly
    # deployed so most pre_check assertions ("subnet not routed",
    # "interface unconfigured") trivially hold AFTER deploy too — sim's
    # configs add the routes/interfaces the pre_check asserts absent.
    # Running pre_check here therefore checks whether sim's pre_check
    # COMMANDS execute cleanly + their patterns match expected polarity.
    # Failure here = malformed pre_check spec, NOT a deploy blocker.
    # Production-side runner will execute pre_check BEFORE pushing
    # implementation; that's the actual gate.
    pre_check_results: list[dict[str, Any]] = []
    for spec in pre_check_specs:
        device = spec["device"]
        lab_node = device.lower()
        translated = translate_post_check(spec, ip_map)
        cmd_for_exec = translated["command_translated"]
        pattern_for_match = translated["expected_pattern_translated"]
        must_match = bool(spec.get("must_match", True))
        try:
            r = _exec_check(
                lab_name, lab_node, cmd_for_exec, timeout=exec_timeout
            )
            actual = r.get("stdout", "")
        except Exception as exc:  # noqa: BLE001
            actual = f"<exec error: {type(exc).__name__}: {exc}>"
            errors.append(f"exec pre_check {spec['check_id']} on {lab_node}: {exc}")
        # Flip polarity per must_match: True = pattern present; False = absent
        match = _match_pattern(actual, pattern_for_match)
        passed = match if must_match else (not match)
        pre_check_results.append({
            "check_id": spec["check_id"],
            "device": device,
            "lab_node": lab_node,
            "command": spec["command"],
            "command_executed": cmd_for_exec,
            "expected_pattern": spec["expected_pattern"],
            "expected_pattern_matched": pattern_for_match,
            "must_match": must_match,
            "translation_notes": translated["translation_notes"],
            "actual": actual,
            "passed": passed,
        })
    _journal("verify_pre_check", "verify",
             {"checks": len(pre_check_results)},
             {"passed": sum(1 for r in pre_check_results if r["passed"]),
              "failed": sum(1 for r in pre_check_results if not r["passed"]),
              "informational": True})

    post_check_results: list[dict[str, Any]] = []
    for spec in post_check_specs:
        device = spec["device"]
        lab_node = device.lower()  # SRL render lowercases prod → lab
        translated = translate_post_check(spec, ip_map)
        cmd_for_exec = translated["command_translated"]
        pattern_for_match = translated["expected_pattern_translated"]
        try:
            r = _exec_check(
                lab_name, lab_node, cmd_for_exec, timeout=exec_timeout
            )
            actual = r.get("stdout", "")
        except Exception as exc:  # noqa: BLE001
            actual = f"<exec error: {type(exc).__name__}: {exc}>"
            errors.append(f"exec {spec['check_id']} on {lab_node}: {exc}")
        passed = _match_pattern(actual, pattern_for_match)
        post_check_results.append({
            "check_id": spec["check_id"],
            "device": device,
            "lab_node": lab_node,
            "command": spec["command"],
            "command_executed": cmd_for_exec,
            "expected_pattern": spec["expected_pattern"],
            "expected_pattern_matched": pattern_for_match,
            "translation_notes": translated["translation_notes"],
            "actual": actual,
            "passed": passed,
        })
    # Verdict semantics:
    #   * "PASS"        — at least one check ran AND all passed
    #   * "FAIL"        — at least one check ran AND some failed
    #   * "NO_CHECKS"   — spec has no post_check; can't form opinion
    if not post_check_results:
        verdict = "NO_CHECKS"
    elif all(r["passed"] for r in post_check_results):
        verdict = "PASS"
    else:
        verdict = "FAIL"
    _journal("verify_post_check", "verify",
             {"checks": len(post_check_results)},
             {"verdict": verdict,
              "passed": sum(1 for r in post_check_results if r["passed"]),
              "failed": sum(1 for r in post_check_results if not r["passed"])})

    # ── Phase 5b: tvt mapping (Patch N — 3-tier fallback) ───────────
    # Tier 1 (preferred): TvtRow.evidence_check_ids explicitly lists which
    #   post_check.check_id(s) prove this test row.  Sim emits the link;
    #   composite consumes it deterministically.
    # Tier 2 (real-world specs without the link field): if test_id and
    #   check_id share device mention in description / role, match by
    #   device — for ebgp_direct's typical 1-test-per-device shape.
    # Tier 3 (minimum viable): when len(post_check) == len(tvt rows
    #   listed in required_tests), zip by index.  This is heuristic but
    #   gets the demo7 case working.  Logged in journal as "by_index".
    check_by_id = {r["check_id"]: r for r in post_check_results}
    tvt_test_ids: list[str] = []
    tvt_actuals: list[str] = []
    tvt_statuses: list[str] = []
    tvt_results: list[dict[str, Any]] = []
    link_strategy = "exact"

    def _record_match(trow: dict, match: dict) -> None:
        snippet = match["actual"][:200] if match["actual"] else ""
        status = "PASS" if match["passed"] else "FAIL"
        tvt_test_ids.append(trow["test_id"])
        tvt_actuals.append(snippet)
        tvt_statuses.append(status)
        tvt_results.append({
            "test_id": trow["test_id"],
            "expected": trow["expected"],
            "actual_lab": snippet,
            "status": status,
            "from_check_id": match["check_id"],
        })

    # Tier 1: explicit evidence_check_ids (extra="allow" on TvtRow)
    explicit_used = False
    for trow in tvt_specs:
        evidence = trow.get("evidence_check_ids") or []
        if evidence:
            explicit_used = True
            for cid in evidence:
                m = check_by_id.get(cid)
                if m is not None:
                    _record_match(trow, m)
                    break
    if explicit_used:
        link_strategy = "evidence_check_ids"

    # Tier 1b (also-exact): test_id == check_id when no explicit link
    if not tvt_results:
        for trow in tvt_specs:
            m = check_by_id.get(trow["test_id"])
            if m is not None:
                _record_match(trow, m)

    # Tier 2: device-mention match in tvt.description
    if not tvt_results and post_check_results:
        device_to_check = {r["device"]: r for r in post_check_results}
        for trow in tvt_specs:
            desc = (trow.get("description") or "").upper()
            for dev, m in device_to_check.items():
                if dev.upper() in desc.split():  # whole-token match
                    _record_match(trow, m)
                    link_strategy = "by_device_in_description"
                    break

    # Tier 3: index-zip when cardinalities line up
    if not tvt_results and post_check_results:
        # Prefer the required_tests subset of tvt rows for the zip
        required = set(loaded.get("required_tests", []))
        candidates = [t for t in tvt_specs if t["test_id"] in required] \
                     if required else list(tvt_specs)
        if len(candidates) == len(post_check_results):
            for trow, m in zip(candidates, post_check_results, strict=True):
                _record_match(trow, m)
            link_strategy = "by_index"

    _journal("tvt_link", "verify",
             {"tvt_count": len(tvt_specs),
              "post_check_count": len(post_check_results)},
             {"matched": len(tvt_results),
              "strategy": link_strategy if tvt_results else "none"})

    # step_verdicts is reserved for cross-verifying spec.implementation
    # vs lab.implementation_lab (per StepVerdict schema); the composite
    # doesn't push lab CLI back so leave empty — diff_spec_vs_lab is
    # the right tool to populate this later.
    step_verdicts: list[dict[str, Any]] = []

    # ── Phase 6: record back to TCF ──────────────────────────────────
    tcf_recorded = False
    if not skip_record:
        diagnosis = ""
        if verdict == "FAIL":
            failed = [r["check_id"] for r in post_check_results
                      if not r["passed"]]
            diagnosis = (
                f"Lab post_check FAIL on {len(failed)} of "
                f"{len(post_check_results)} checks: {failed}. "
                f"Inspect post_check_results.actual for details."
            )

        rec = tcf_record_lab_run(
            spec_path,
            verdict=verdict,
            lab_name=lab_name,
            tvt_test_ids=tvt_test_ids,
            tvt_actual_lab=tvt_actuals,
            tvt_status=tvt_statuses,
            journal=journal,
            diagnosis=diagnosis,
            step_verdicts=step_verdicts,
        )
        tcf_recorded = rec.get("status") == "ok"
        if not tcf_recorded:
            errors.append(
                f"tcf_record_lab_run: {rec.get('error', 'unknown')}"
            )

    # ── Phase 7: destroy ─────────────────────────────────────────────
    _attempt_destroy()

    return {
        "status": "ok",
        "phase": "complete",
        "verdict": verdict,
        "spec_path": str(spec_path),
        "lab_name": lab_name,
        "pre_check_results": pre_check_results,
        "post_check_results": post_check_results,
        "tvt_results": tvt_results,
        "journal": journal,
        "tcf_recorded": tcf_recorded,
        "lab_destroyed": lab_destroyed,
        "errors": errors,
    }
