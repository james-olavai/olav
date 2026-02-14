"""Skill Loader - 从 Markdown frontmatter 加载和索引技能.

v0.10.1+: 支持skill级配置加载
- skill/config/*.yaml 自动加载
- 统一配置管理机制
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from config.settings import settings


@dataclass
class Skill:
    """技能数据结构.

    支持两种格式:
    - OLAV 格式: id 字段
    - Claude Code 格式: name 字段 (自动转换为 id)
    """

    id: str
    intent: str  # query | diagnose | inspect | config
    complexity: str  # simple | medium | complex
    description: str
    examples: list[str]
    file_path: str
    content: str | None = None  # 延迟加载
    frontmatter: dict[str, Any] | None = None  # Frontmatter 数据 (延迟加载)
    config: dict[str, Any] | None = None  # Skill级配置 (延迟加载, v0.10.1+)


class SkillLoader:
    """技能加载器 - 解析frontmatter、生成索引、延迟加载内容."""

    def __init__(self, skills_dir: Path) -> None:
        self.skills_dir = Path(skills_dir)
        self._index: dict[str, Skill] = {}
        self._content_cache: dict[str, str] = {}

    def load_all(self) -> dict[str, Skill]:
        """扫描并加载所有技能索引 - 支持两种格式.

        支持格式:
        1. Claude Code 标准: skills/*/SKILL.md
        2. OLAV 传统格式: skills/*.md
        """
        if self._index:
            return self._index

        # Format 1: Claude Code 标准 (skills/*/SKILL.md)
        for skill_dir in self.skills_dir.iterdir():
            if skill_dir.is_dir() and not skill_dir.name.startswith("_"):
                skill_file = skill_dir / "SKILL.md"
                if skill_file.exists():
                    skill = self._parse_skill_header(skill_file)
                    if skill:
                        self._index[skill.id] = skill

        # Format 2: OLAV 传统 (skills/*.md)
        for md_file in self.skills_dir.glob("*.md"):
            # 跳过已处理的 SKILL.md 和禁用文件
            if md_file.name == "SKILL.md":
                continue
            if md_file.name.startswith("_") or ".draft" in md_file.name:
                continue

            skill = self._parse_skill_header(md_file)
            if skill:
                # 避免覆盖已加载的 Claude Code 格式技能
                if skill.id not in self._index:
                    self._index[skill.id] = skill

        return self._index

    def _parse_skill_header(self, file_path: Path) -> Skill | None:
        """解析单个技能文件的 frontmatter (不加载完整内容).

        支持两种格式:
        - OLAV 格式: id 字段
        - Claude Code 格式: name 字段 (自动转换为 id)
        """
        try:
            content = file_path.read_text(encoding="utf-8")

            # 提取 frontmatter
            fm = self._extract_frontmatter(content)
            if not fm:
                return None

            # 兼容 id 和 name 字段
            skill_id = fm.get("id") or fm.get("name")
            if not skill_id:
                # 如果都没有，从文件名生成
                skill_id = (
                    file_path.stem.replace("-", " ").replace("_", " ").lower().replace(" ", "-")
                )

            # 验证必需字段
            if "description" not in fm:
                return None

            # 检查 enabled 标志 - 默认启用（除非显式禁用）
            if fm.get("enabled", True) is False:
                return None

            # Normalize skill_id: lowercase with hyphens
            skill_id = skill_id.lower().replace(" ", "-").replace("_", "-")

            return Skill(
                id=skill_id,
                intent=fm.get("intent", "unknown"),
                complexity=fm.get("complexity", "medium"),
                description=fm["description"],
                examples=fm.get("examples", fm.get("triggers", [])),
                file_path=str(file_path),
                frontmatter=fm,  # Store frontmatter for output config access
            )
        except Exception as e:
            print(f"Error parsing skill {file_path}: {e}")
            return None

    def _extract_frontmatter(self, content: str) -> dict[str, Any] | None:
        """从 Markdown 内容中提取 YAML frontmatter."""
        if not content.startswith("---"):
            return None

        # 找到第二个 ---
        end_idx = content.find("---", 3)
        if end_idx == -1:
            return None

        fm_str = content[3:end_idx].strip()
        try:
            return yaml.safe_load(fm_str) or {}
        except yaml.YAMLError:
            return None

    def get_skill(self, skill_id: str) -> Skill | None:
        """获取单个技能 (延迟加载内容)."""
        if not self._index:
            self.load_all()

        if skill_id not in self._index:
            return None

        skill = self._index[skill_id]

        # 延迟加载完整内容
        if not skill.content:
            try:
                skill.content = Path(skill.file_path).read_text(encoding="utf-8")
            except Exception as e:
                print(f"Error loading skill content {skill_id}: {e}")

        return skill

    def get_skills_by_intent(self, intent: str) -> list[Skill]:
        """按意图过滤技能."""
        if not self._index:
            self.load_all()

        return [s for s in self._index.values() if s.intent == intent]

    def get_index_summary(self) -> dict[str, Any]:
        """生成索引摘要 (用于LLM路由)."""
        if not self._index:
            self.load_all()

        return {
            "total": len(self._index),
            "generated_at": None,  # TODO: 添加时间戳
            "skills": {
                skill_id: {
                    "complexity": skill.complexity,
                    "description": skill.description,
                    "examples": skill.examples[:3],  # 只保留前3个示例
                }
                for skill_id, skill in self._index.items()
            },
        }

    def load_system_prompt(self, skill_id: str, prompt_key: str = "system", template_vars: dict[str, str] | None = None) -> str:
        """加载 skill 的系统提示词 (v0.12.0+).
        
        支持:
        - 从 SKILL.md frontmatter 中的 prompts.{prompt_key} 字段加载
        - 解析 $ref:./prompts/system.md 引用
        - 模板变量注入 (e.g., {schema}, {warnings})
        
        Args:
            skill_id: Skill ID (e.g., "network-query")
            prompt_key: 提示词键名 (默认 "system")，可选值: "system", "sql_generator" 等
            template_vars: 模板变量字典 (e.g., {"schema": "SELECT...", "warnings": "..."})
        
        Returns:
            系统提示词字符串，找不到返回空字符串
        
        Examples:
            # 基础加载
            prompt = loader.load_system_prompt("network-query")
            
            # 加载不同的提示词
            prompt = loader.load_system_prompt("network-query", prompt_key="sql_generator")
            
            # 带模板变量
            prompt = loader.load_system_prompt(
                "network-query",
                prompt_key="sql_generator",
                template_vars={"schema": "devices: 6 rows", "warnings": "..."}
            )
        """
        if skill_id not in self._index:
            return ""
        
        skill = self._index[skill_id]
        
        # 获取 frontmatter
        if not skill.frontmatter:
            return ""
        
        # 检查 prompts.{prompt_key} 配置
        prompts_config = skill.frontmatter.get("prompts", {})
        if not isinstance(prompts_config, dict):
            return ""
        
        prompt_ref = prompts_config.get(prompt_key)
        if not prompt_ref:
            return ""
        
        # 解析 $ref 引用
        if isinstance(prompt_ref, str) and prompt_ref.startswith("$ref:"):
            prompt_text = self._resolve_prompt_ref(skill_id, prompt_ref)
        else:
            prompt_text = prompt_ref
        
        if not prompt_text:
            return ""
        
        # 注入模板变量
        template_vars = template_vars or {}
        for key, value in template_vars.items():
            placeholder = "{" + key + "}"
            prompt_text = prompt_text.replace(placeholder, str(value))
        
        return prompt_text
    
    def _resolve_prompt_ref(self, skill_id: str, ref: str) -> str:
        """解析 $ref:./path/to/file.md 引用.
        
        Args:
            skill_id: Skill ID
            ref: 引用字符串，格式为 "$ref:./prompts/system.md"
        
        Returns:
            文件内容
        """
        import re
        
        # 提取相对路径
        match = re.match(r"\$ref:(.+)", ref)
        if not match:
            return ""
        
        rel_path = match.group(1).strip()
        
        skill = self._index.get(skill_id)
        if not skill:
            return ""
        
        skill_dir = Path(skill.file_path).parent
        file_path = skill_dir / rel_path
        
        if not file_path.exists():
            print(f"Warning: Reference file not found: {file_path}")
            return ""
        
        try:
            content = file_path.read_text(encoding="utf-8")
            # 如果是 markdown 文件，移除代码块标记
            if file_path.suffix == ".md":
                content = content.strip()
                # 移除开头的 markdown 代码块标记
                if content.startswith("```"):
                    lines = content.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines and lines[-1] == "```":
                        lines = lines[:-1]
                    content = "\n".join(lines).strip()
                # 移除 markdown 标题
                if content.startswith("#"):
                    lines = content.split("\n")
                    # 找到第一个非标题行
                    start_idx = 0
                    for i, line in enumerate(lines):
                        if not line.startswith("#"):
                            start_idx = i
                            break
                    content = "\n".join(lines[start_idx:]).strip()
            return content
        except Exception as e:
            print(f"Warning: Failed to load prompt file {file_path}: {e}")
            return ""
    
    def load_skill_config(self, skill_id: str, config_name: str | None = None) -> dict[str, Any]:
        """加载skill级别的配置文件 (v0.10.1+).
        
        路径解析:
            .olav/skills/{skill_id}/config/{config_name}.yaml
        
        Args:
            skill_id: Skill ID (e.g., "network-expert")
            config_name: 配置文件名（不含.yaml后缀），None则加载所有配置
        
        Returns:
            配置字典，找不到返回空dict
        
        Examples:
            # 加载单个配置
            thresholds = loader.load_skill_config("network-expert", "thresholds")
            
            # 加载所有配置
            all_configs = loader.load_skill_config("network-expert")
            # Returns: {"thresholds": {...}, "models": {...}}
        """
        if skill_id not in self._index:
            return {}
        
        skill = self._index[skill_id]
        skill_dir = Path(skill.file_path).parent
        config_dir = skill_dir / "config"
        
        if not config_dir.exists():
            return {}
        
        # 加载单个配置文件
        if config_name:
            config_file = config_dir / f"{config_name}.yaml"
            if not config_file.exists():
                return {}
            
            try:
                with open(config_file, encoding="utf-8") as f:
                    return yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: Failed to load {config_file}: {e}")
                return {}
        
        # 加载所有配置文件
        all_configs = {}
        for config_file in config_dir.glob("*.yaml"):
            config_key = config_file.stem  # 文件名（不含.yaml）
            try:
                with open(config_file, encoding="utf-8") as f:
                    all_configs[config_key] = yaml.safe_load(f) or {}
            except Exception as e:
                print(f"Warning: Failed to load {config_file}: {e}")
        
        return all_configs


def get_skill_loader(skills_dir: Path | None = None) -> SkillLoader:
    """获取全局 SkillLoader 实例 (单例)."""
    if not hasattr(get_skill_loader, "_instance"):
        if skills_dir is None:
            skills_dir = Path(settings.runtime.get_skills_dir())
        # Use a module-level variable for singleton (type: ignore for function attribute)
        get_skill_loader._instance = SkillLoader(skills_dir)  # type: ignore[attr-defined]
    return get_skill_loader._instance  # type: ignore[attr-defined]
