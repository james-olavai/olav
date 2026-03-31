from pathlib import Path


def test_platform_doc_declares_claude_export_layer() -> None:
    platform_text = Path("dev_docs/olav_platform.md").read_text(encoding="utf-8")

    assert "olav export claude-skills" in platform_text
    assert "olav export claude-plugin" in platform_text
    assert "不引入 `install-skill` agent" in platform_text


def test_platform_doc_enforces_progressive_disclosure_layers() -> None:
    platform_text = Path("dev_docs/olav_platform.md").read_text(encoding="utf-8")

    assert "descriptor / playbook / reference" in platform_text
    assert "渐进式披露" in platform_text


def test_api_discovery_doc_requires_schema_mutation_service() -> None:
    discovery_text = Path("dev_docs/api_discovery.md").read_text(encoding="utf-8")

    assert "SchemaMutationService" in discovery_text
    assert "不再主张 direct DB write 例外" in discovery_text
    assert "domain.duckdb" in discovery_text


def test_api_discovery_doc_uses_domain_prefixed_mapping_collection() -> None:
    discovery_text = Path("dev_docs/api_discovery.md").read_text(encoding="utf-8")

    assert "<domain>_field_mappings" in discovery_text
