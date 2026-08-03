"""Governance — SKILL.md structural invariants.

Enforces the CLAUDE.md SKILL.md Authoring Rules section.  Catches the four
failure modes that caused silent bugs in rounds before the @tool → scripts
migration:

  1. ``system: $ref:`` dead config — never read by the framework; root cause
     was scaffold_skill.py template emitting it on every new agent.  Fixed
     2026-05-31.  This test prevents re-introduction.

  2. scripts: path-form entries — ``- path: ./scripts/foo.py`` syntax that
     SkillsMiddleware cannot parse, so the LLM never sees the description.

  3. script ``file:`` path traversal — ``../`` or ``/`` in the file value is
     silently rejected by skill_runner at runtime.

  4. script file missing from disk — declared in SKILL.md but
     ``<skill_dir>/scripts/<file>`` does not exist; call fails at runtime.

  5. execute_skill_script absent from tools: — scripts are injected into the
     system prompt by SkillsMiddleware but are uncallable without this tool.

  6. netops SKILL.md drift — the dev mirror (.olav/workspace/netops/) and the
     authoritative copy (olav-netops/.olav/workspace/netops/) must stay
     byte-identical per the two-workspace sync rule.

Framework components used
--------------------------
* ``olav.core.platform_registry._parse_frontmatter`` — the canonical
  frontmatter parser used by the workspace loader.  Governance tests delegate
  here instead of re-implementing YAML parsing so that any change to the
  production parser is automatically reflected in the tests.

* ``olav.core.skill_runner._read_script_metadata`` — the exact runtime code
  path that ``execute_skill_script`` uses to locate a script's metadata entry
  in SKILL.md.  Using it in tests proves governance ≈ production behavior:
  if the runtime cannot find a script entry, the test fails too.
"""

from __future__ import annotations

from pathlib import Path

import pytest

# Framework components — use the same parsers the runtime uses.
from olav.core.platform_registry import _parse_frontmatter as _fw_parse_frontmatter
from olav.core.skill_runner import _read_script_metadata

REPO = Path(__file__).resolve().parents[2]
ROOT_WORKSPACE = REPO / ".olav" / "workspace"
NETOPS_WORKSPACE = REPO / "olav-netops" / ".olav" / "workspace" / "netops"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _all_skill_mds(root: Path = ROOT_WORKSPACE) -> list[Path]:
    return sorted(root.rglob("SKILL.md"))


def _parse_frontmatter(path: Path) -> dict:
    """Thin wrapper: read file, delegate to the framework's canonical parser.

    ``platform_registry._parse_frontmatter`` uses ``text.find("\\n---", 3)``
    to locate the closing delimiter — more robust than split("---", 2) because
    it requires a newline before the closing dashes.  This matches what the
    workspace loader sees.
    """
    meta, _ = _fw_parse_frontmatter(path.read_text(encoding="utf-8"))
    return meta


def _rel(path: Path) -> str:
    return str(path.relative_to(REPO))


# ---------------------------------------------------------------------------
# Pre-existing known violations.  Each entry must cite a round or ADR that
# documents *why* the violation exists and when it is expected to be fixed.
# Extend this dict only when the issue is genuinely pre-existing (not newly
# introduced); a new violation without a justification is a real failure.
# ---------------------------------------------------------------------------

# (relative SKILL.md path from repo root, script name) → rationale
# Empty: all pre-existing violations resolved 2026-05-31 (collector take_snapshot +
# search_commands copied into collector/scripts/ and file: changed to bare filenames).
_KNOWN_SCRIPT_FILE_VIOLATIONS: dict[tuple[str, str], str] = {}


# ---------------------------------------------------------------------------
# 1. No dead `system: $ref:` config
# ---------------------------------------------------------------------------


class TestNoDeadSystemRef:
    """``system: $ref:`` is never processed by the framework (the key the
    framework reads is ``system_prompt_file:``).  Its presence is always a
    copy-paste artefact from the old scaffold_skill.py template."""

    def test_no_system_ref_in_any_skill_md(self):
        offenders: list[str] = []
        for p in _all_skill_mds():
            text = p.read_text(encoding="utf-8")
            # Check only the raw frontmatter block — not the body.
            if text.startswith("---"):
                end = text.find("\n---", 3)
                fm_block = text[3:end] if end != -1 else ""
                if "system: $ref:" in fm_block:
                    offenders.append(_rel(p))
        assert not offenders, (
            "SKILL.md files contain dead 'system: $ref:' config — "
            "framework never reads this key.  Use 'system_prompt_file: prompts/system.md' "
            "or rely on the SKILL.md body as the system prompt.\n"
            "Offenders:\n  " + "\n  ".join(offenders)
        )

    def test_scaffold_skill_template_uses_skill_md_body(self):
        """scaffold_skill.py must embed system prompt in SKILL.md body, not emit system_prompt_file: or system: $ref:."""
        scaffold = (
            ROOT_WORKSPACE / "admin" / "editor" / "scripts" / "scaffold_skill.py"
        )
        if not scaffold.exists():
            pytest.skip("scaffold_skill.py not found")
        text = scaffold.read_text(encoding="utf-8")
        assert "system: $ref:" not in text, (
            "scaffold_skill.py template still emits dead 'system: $ref:' config."
        )
        assert "system_prompt_file:" not in text, (
            "scaffold_skill.py must NOT emit 'system_prompt_file:' — "
            "system prompt belongs in the SKILL.md body, not a separate prompts/ file."
        )
        assert "execute_skill_script" in text, (
            "scaffold_skill.py template must include 'execute_skill_script' in tools: "
            "so new agents can call scripts from the start."
        )


# ---------------------------------------------------------------------------
# 2. scripts: entries must use name-form (name + description + file)
# ---------------------------------------------------------------------------


class TestScriptsNameForm:
    """Every ``scripts:`` entry must be a dict with ``name``, ``description``,
    and ``file`` keys.  String entries (path-form) and dicts with only
    ``path:`` are invisible to SkillsMiddleware — the LLM never learns the
    description and may not know to call the script at all."""

    def test_all_scripts_entries_are_name_form(self):
        violations: list[str] = []
        for p in _all_skill_mds():
            fm = _parse_frontmatter(p)
            for entry in fm.get("scripts") or []:
                rel = _rel(p)
                if isinstance(entry, str):
                    violations.append(
                        f"{rel}: string entry {entry!r} (path-form — use name/description/file dict)"
                    )
                elif isinstance(entry, dict):
                    name = entry.get("name", "<unnamed>")
                    missing = [k for k in ("name", "description", "file") if k not in entry]
                    if missing:
                        violations.append(
                            f"{rel}: script {name!r} missing keys: {missing}"
                        )
                    if "path" in entry and "name" not in entry:
                        violations.append(
                            f"{rel}: script uses path-form only (path={entry['path']!r})"
                        )
        assert not violations, (
            "scripts: entries must use name-form (name + description + file).\n"
            "Violations:\n  " + "\n  ".join(violations)
        )


# ---------------------------------------------------------------------------
# 3 + 4. script file: must be a bare filename AND resolvable at runtime
# ---------------------------------------------------------------------------


class TestScriptFileValidity:
    """The ``file:`` value in a ``scripts:`` entry must be a bare Python
    filename (no ``/`` or ``..``).  skill_runner explicitly rejects path
    traversal.  The file must also exist under ``<skill_dir>/scripts/``.

    Disk existence is verified via ``skill_runner._read_script_metadata`` —
    the same code path that ``execute_skill_script`` uses at runtime.  If
    the metadata roundtrip fails (returns ``{}``) or the file is absent from
    disk, the script cannot be called.
    """

    def _check_all(self) -> tuple[list[str], list[str]]:
        traversal_violations: list[str] = []
        missing_violations: list[str] = []

        for p in _all_skill_mds():
            fm = _parse_frontmatter(p)
            rel_skill = _rel(p)
            skill_dir = p.parent

            for entry in fm.get("scripts") or []:
                if not isinstance(entry, dict):
                    continue
                name = entry.get("name", "<unnamed>")
                file_val = entry.get("file", "")
                if not file_val:
                    continue

                # Check 1: bare filename — skill_runner rejects "/" or ".." at runtime
                if "/" in file_val or ".." in file_val:
                    key = (rel_skill, name)
                    if key not in _KNOWN_SCRIPT_FILE_VIOLATIONS:
                        traversal_violations.append(
                            f"{rel_skill}: script {name!r} has path traversal "
                            f"in file: {file_val!r} — skill_runner rejects this; "
                            "use a bare filename"
                        )
                    continue  # Cannot check disk existence for traversal paths

                # Check 2: runtime metadata roundtrip via skill_runner._read_script_metadata.
                # This is the exact code path execute_skill_script uses to locate the entry.
                # If it returns {} the runtime cannot find the script metadata even though
                # we see it declared above — indicates a parser inconsistency.
                meta = _read_script_metadata(skill_dir, file_val)

                # Check 3: file must exist under <skill_dir>/scripts/ (runtime resolves
                # script_path = scripts_dir / script_name and calls resolve(strict=True))
                script_path = skill_dir / "scripts" / file_val

                if not meta or not script_path.exists():
                    key = (rel_skill, name)
                    if key not in _KNOWN_SCRIPT_FILE_VIOLATIONS:
                        reason = (
                            "metadata roundtrip failed (skill_runner._read_script_metadata "
                            f"returned {{}} for {file_val!r})"
                            if not meta
                            else f"scripts/{file_val} not found on disk"
                        )
                        missing_violations.append(
                            f"{rel_skill}: script {name!r} — {reason}"
                        )

        return traversal_violations, missing_violations

    def test_no_path_traversal_in_file_values(self):
        traversal, _ = self._check_all()
        assert not traversal, (
            "scripts: file: values with '/' or '..' are rejected by skill_runner "
            "at runtime.  Use a bare filename; copy shared scripts into the agent's "
            "scripts/ directory.\n"
            "Violations (not in _KNOWN_SCRIPT_FILE_VIOLATIONS):\n  "
            + "\n  ".join(traversal)
        )

    def test_script_files_exist_on_disk(self):
        _, missing = self._check_all()
        assert not missing, (
            "scripts: file: values cannot be resolved at runtime.\n"
            "Either the metadata roundtrip via skill_runner._read_script_metadata "
            "failed, or the file is missing from scripts/.\n"
            "Violations (not in _KNOWN_SCRIPT_FILE_VIOLATIONS):\n  "
            + "\n  ".join(missing)
        )

    def test_known_violations_are_still_broken(self):
        """Canary: if a known violation is fixed, remove it from the allowlist.

        This test fails when someone fixes a pre-existing violation but forgets
        to remove it from _KNOWN_SCRIPT_FILE_VIOLATIONS — keeping stale
        entries gives false confidence that the allowlist is still current.
        """
        now_ok: list[str] = []

        for (rel_skill, name), _rationale in _KNOWN_SCRIPT_FILE_VIOLATIONS.items():
            p = REPO / rel_skill
            if not p.exists():
                continue
            fm = _parse_frontmatter(p)
            entry = next(
                (e for e in (fm.get("scripts") or [])
                 if isinstance(e, dict) and e.get("name") == name),
                None,
            )
            if entry is None:
                now_ok.append(
                    f"{rel_skill}: script {name!r} no longer declared — "
                    "remove from _KNOWN_SCRIPT_FILE_VIOLATIONS"
                )
                continue
            file_val = entry.get("file", "")
            if "/" in file_val or ".." in file_val:
                continue  # Still broken (traversal)
            skill_dir = p.parent
            meta = _read_script_metadata(skill_dir, file_val)
            disk_ok = (skill_dir / "scripts" / file_val).exists()
            if meta and disk_ok:
                now_ok.append(
                    f"{rel_skill}: script {name!r} is now valid — "
                    "remove from _KNOWN_SCRIPT_FILE_VIOLATIONS"
                )

        assert not now_ok, (
            "Pre-existing violations in _KNOWN_SCRIPT_FILE_VIOLATIONS have been "
            "fixed but the allowlist entry was not removed.  Clean it up:\n  "
            + "\n  ".join(now_ok)
        )


# ---------------------------------------------------------------------------
# 5. execute_skill_script must be in tools: when scripts: is non-empty
# ---------------------------------------------------------------------------


class TestExecuteSkillScriptWiring:
    """If a SKILL.md declares scripts, the LLM needs execute_skill_script in
    its tools: list to actually call them.  Without it, scripts appear in the
    system prompt (via SkillsMiddleware) but are uncallable — the LLM either
    hallucinates a call or produces XML-format tool tokens."""

    def test_execute_skill_script_present_when_scripts_declared(self):
        violations: list[str] = []
        for p in _all_skill_mds():
            fm = _parse_frontmatter(p)
            scripts = fm.get("scripts") or []
            tools = fm.get("tools") or []
            if scripts and "execute_skill_script" not in tools:
                violations.append(_rel(p))
        assert not violations, (
            "SKILL.md files declare scripts: but are missing execute_skill_script "
            "from tools:.  The LLM cannot call scripts without this tool.\n"
            "Add 'execute_skill_script' to the tools: list, or remove scripts: "
            "if they are pipeline-only (not LLM-callable).\n"
            "Violations:\n  " + "\n  ".join(violations)
        )


# ---------------------------------------------------------------------------
# 6. netops SKILL.md two-workspace sync
# ---------------------------------------------------------------------------


class TestNetopsWorkspaceSync:
    """The dev mirror (.olav/workspace/netops/) and the authoritative copy
    (olav-netops/.olav/workspace/netops/) must be byte-identical for SKILL.md
    files.  Edits to one copy must be synced to the other before committing.
    """

    def _collect_skill_mds(self, root: Path) -> dict[Path, Path]:
        """Return {relative_path: absolute_path} for all SKILL.md under root."""
        if not root.exists():
            return {}
        return {p.relative_to(root): p for p in root.rglob("SKILL.md")}

    def test_both_workspace_copies_exist(self):
        root = ROOT_WORKSPACE / "netops"
        if not NETOPS_WORKSPACE.exists():
            pytest.skip("olav-netops not checked out alongside root")
        assert root.exists(), ".olav/workspace/netops/ missing"

    def test_no_skill_md_only_in_dev_mirror(self):
        if not NETOPS_WORKSPACE.exists():
            pytest.skip("olav-netops not checked out")
        dev = self._collect_skill_mds(ROOT_WORKSPACE / "netops")
        authoritative = self._collect_skill_mds(NETOPS_WORKSPACE)
        # `netops/lab` is routed as a netops sub-agent but ships with
        # **olav-ent** (dev_docs/112); `olav agent install olav-ent` deploys it
        # into the runtime mirror, so it is legitimately here and not in
        # olav-netops. Everything else under netops/ must still match.
        only_dev = {p for p in (set(dev) - set(authoritative))
                    if p.parts[:1] != ("lab",)}
        assert not only_dev, (
            "SKILL.md files present in .olav/workspace/netops/ but missing in "
            "olav-netops/.olav/workspace/netops/.  Sync the authoritative copy:\n  "
            + "\n  ".join(str(p) for p in sorted(only_dev))
        )

    def test_no_skill_md_only_in_authoritative(self):
        if not NETOPS_WORKSPACE.exists():
            pytest.skip("olav-netops not checked out")
        dev = self._collect_skill_mds(ROOT_WORKSPACE / "netops")
        authoritative = self._collect_skill_mds(NETOPS_WORKSPACE)
        only_auth = set(authoritative) - set(dev)
        assert not only_auth, (
            "SKILL.md files present in olav-netops/.olav/workspace/netops/ but "
            "missing in .olav/workspace/netops/.  Sync the dev mirror:\n  "
            + "\n  ".join(str(p) for p in sorted(only_auth))
        )

    def test_skill_md_content_is_byte_identical(self):
        if not NETOPS_WORKSPACE.exists():
            pytest.skip("olav-netops not checked out")
        dev = self._collect_skill_mds(ROOT_WORKSPACE / "netops")
        authoritative = self._collect_skill_mds(NETOPS_WORKSPACE)
        shared = set(dev) & set(authoritative)
        divergent: list[str] = []
        for rel in sorted(shared):
            if dev[rel].read_bytes() != authoritative[rel].read_bytes():
                divergent.append(str(rel))
        assert not divergent, (
            "SKILL.md content divergence between .olav/workspace/netops/ and "
            "olav-netops/.olav/workspace/netops/.  Edit one copy and sync "
            "the other before committing:\n  " + "\n  ".join(divergent)
        )
