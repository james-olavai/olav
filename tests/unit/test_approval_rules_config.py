"""
TDD: CC-04 — 声明式危险规则配置

验收标准:
  1. load_approval_rules() 在无 YAML 时回退到内置规则
  2. 存在 YAML 时从文件加载规则（可新增，也可覆盖同名规则）
  3. env_overrides 支持环境级规则（lab / production）
  4. 恶意/无效 YAML 时回退到内置规则，不崩溃
  5. 加载的规则被 _COMPILED_RULES 使用（approve_command 行为正确）
"""

from __future__ import annotations

import textwrap
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Unit tests: load_approval_rules()
# ---------------------------------------------------------------------------


class TestLoadApprovalRules:
    def test_returns_builtin_rules_when_no_yaml(self, tmp_path, monkeypatch):
        """Falls back to built-in rules when YAML file is absent."""
        from olav.platform.safety import approval

        monkeypatch.setattr(approval, "_RULES_YAML_PATH", tmp_path / "nonexistent.yaml")
        rules = approval.load_approval_rules()
        assert isinstance(rules, list)
        assert len(rules) > 0
        # Each rule is a 3-tuple: (pattern, severity, description)
        for r in rules:
            assert len(r) == 3

    def test_loads_rules_from_yaml(self, tmp_path, monkeypatch):
        """Loads rules from YAML file when present."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text(
            textwrap.dedent("""\
            rules:
              - pattern: '(?i)^\\s*test-danger-command'
                severity: "high"
                description: "Test danger rule from YAML"
            """)
        )
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        rules = approval.load_approval_rules()
        assert any(r[2] == "Test danger rule from YAML" for r in rules), (
            f"YAML rule not found in loaded rules: {[r[2] for r in rules]}"
        )

    def test_yaml_rules_extend_builtins(self, tmp_path, monkeypatch):
        """YAML rules extend (add to) built-in rules by default."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text(
            textwrap.dedent("""\
            rules:
              - pattern: "(?i)extra-custom-rule"
                severity: "medium"
                description: "Extra custom rule"
            """)
        )
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        rules = approval.load_approval_rules()
        descs = [r[2] for r in rules]
        # Both YAML rule and at least one builtin (reload) should be present
        assert "Extra custom rule" in descs
        assert any("reload" in d.lower() or "Reload" in d for d in descs)

    def test_env_override_lab(self, tmp_path, monkeypatch):
        """env_overrides.lab replaces rules when env='lab'."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text(
            textwrap.dedent("""\
            rules:
              - pattern: "(?i)base-rule"
                severity: "high"
                description: "Base rule"
            env_overrides:
              lab:
                - pattern: "(?i)lab-only-rule"
                  severity: "low"
                  description: "Lab only rule"
            """)
        )
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        lab_rules = approval.load_approval_rules(env="lab")
        descs = [r[2] for r in lab_rules]
        assert "Lab only rule" in descs
        # lab env overrides completely replace the YAML rules section
        # (but builtins are always present unless override_builtins=true)

    def test_invalid_yaml_falls_back_to_builtins(self, tmp_path, monkeypatch):
        """Malformed YAML falls back to built-in rules without crashing."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text("{{{{ not valid yaml at all ::::")
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        rules = approval.load_approval_rules()
        # Should still return built-in rules
        assert len(rules) > 0


# ---------------------------------------------------------------------------
# Integration: approve_command uses dynamically loaded rules
# ---------------------------------------------------------------------------


class TestApproveCommandWithDynamicRules:
    def test_custom_yaml_rule_blocks_command(self, tmp_path, monkeypatch):
        """A rule loaded from YAML causes approve_command to flag it."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text(
            textwrap.dedent("""\
            rules:
              - pattern: '(?i)^\\s*no\\s+banana\\b'
                severity: "high"
                description: "No banana rule — test"
            """)
        )
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        # Force reload of compiled rules
        approval._reload_compiled_rules()

        result = approval.approve_command("no banana vlan")
        assert result.requires_approval, (
            "Custom YAML rule should have flagged 'no banana vlan'"
        )

    def test_builtin_rule_still_works_after_yaml_load(self, tmp_path, monkeypatch):
        """Built-in reload rule still works after loading a YAML with extra rules."""
        from olav.platform.safety import approval

        yaml_path = tmp_path / "approval_rules.yaml"
        yaml_path.write_text(
            textwrap.dedent("""\
            rules:
              - pattern: "(?i)^custom-only"
                severity: "low"
                description: "Custom only"
            """)
        )
        monkeypatch.setattr(approval, "_RULES_YAML_PATH", yaml_path)
        approval._reload_compiled_rules()

        result = approval.approve_command("reload")
        assert result.requires_approval, "Built-in reload rule must still trigger"
