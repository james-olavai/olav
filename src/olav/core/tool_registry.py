"""
Tool Registry - Skill-Centric 工具注册中心

职责:
1. 从 .olav/skills/*/SKILL.md 读取工具配置
2. 动态加载工具模块
3. 提供统一的工具调用接口
4. 缓存已加载的工具
5. 支持工具热重载（开发调试）

架构原则:
- Skill-Centric: 工具配置在 SKILL.md，代码在 .olav/skills/
- 配置驱动: 新增工具只需修改 SKILL.md，无需改代码
- 单例模式: 全局统一的工具注册表
- 零侵入: 现有工具实现保持不变
"""

from pathlib import Path
from typing import Any, Callable, Dict, Optional
import sys
import importlib
import yaml

from config.paths import SKILLS_DIR
from config.logging import get_logger

logger = get_logger(__name__)


class ToolRegistry:
    """工具注册中心 - 管理所有 skill 工具的生命周期"""
    
    _instance: Optional['ToolRegistry'] = None
    _tools: Dict[str, Callable] = {}
    _modules: Dict[str, Any] = {}
    _skill_paths: set[str] = set()
    
    def __new__(cls):
        """单例模式：确保全局只有一个 ToolRegistry 实例"""
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self):
        """初始化注册表 - 仅在首次创建时加载工具"""
        if not self._tools:
            self._load_all_tools()
    
    def _load_all_tools(self) -> None:
        """扫描所有 skill 目录，加载工具配置"""
        skills_path = Path(SKILLS_DIR)
        
        if not skills_path.exists():
            logger.warning(f"Skills directory does not exist: {skills_path}")
            return
        
        logger.info(f"Loading tools from skills directory: {skills_path}")
        
        for skill_dir in skills_path.iterdir():
            if not skill_dir.is_dir() or skill_dir.name.startswith('.'):
                continue
            
            skill_md = skill_dir / "SKILL.md"
            if skill_md.exists():
                self._load_skill_tools(skill_dir, skill_md)
                logger.debug(f"Loaded skill from: {skill_md}")
        
        logger.info(f"Tool Registry initialized with {len(self._tools)} tools")
    
    def _load_skill_tools(self, skill_dir: Path, skill_md: Path) -> None:
        """从 SKILL.md 加载单个 skill 的工具配置
        
        SKILL.md 格式:
        ---
        skill_name: shared_tools
        tools:
          - name: nornir_execute
            module: tools.network
            function: nornir_execute
            description: 执行 Nornir 批量命令
          - name: format_and_export
            module: tools.data_export
            function: format_and_export
            description: 格式化并导出数据
        ---
        
        # Skill 文档...
        """
        try:
            content = skill_md.read_text(encoding='utf-8')
            
            # 提取 YAML frontmatter
            if content.startswith('---'):
                parts = content.split('---', 2)
                if len(parts) >= 3:
                    try:
                        frontmatter = yaml.safe_load(parts[1])
                    except yaml.YAMLError as yaml_err:
                        # 跳过包含自定义标签（如 !include）的 SKILL.md
                        if "could not determine a constructor for the tag" in str(yaml_err):
                            logger.debug(f"Skipping {skill_md.name} - contains custom YAML tags")
                            return
                        raise
                    
                    if not frontmatter or not isinstance(frontmatter, dict):
                        return
                    
                    tools_config = frontmatter.get('tools', [])
                    if not tools_config:
                        return
                    
                    for tool_config in tools_config:
                        # 跳过非字典类型的工具配置
                        if not isinstance(tool_config, dict):
                            logger.debug(f"Skipping tool config (not a dict) in {skill_md.name}")
                            continue
                        self._register_tool(skill_dir, tool_config)
        
        except Exception as e:
            logger.warning(
                f"Failed to load skill tools from {skill_md}: {e}"
            )
    
    def _register_tool(self, skill_dir: Path, tool_config: Dict[str, str]) -> None:
        """注册单个工具
        
        Args:
            skill_dir: skill 目录路径
            tool_config: 工具配置 {name, module, function, description}
        """
        try:
            # 防御性检查：确保 tool_config 是字典
            if not isinstance(tool_config, dict):
                logger.debug(f"Skipping non-dict tool config: {tool_config}")
                return
            
            tool_name = tool_config.get('name')
            module_path = tool_config.get('module')
            function_name = tool_config.get('function')
            
            if not all([tool_name, module_path, function_name]):
                logger.warning(
                    f"Incomplete tool config in {skill_dir}: {tool_config}"
                )
                return
            
            # 添加 skill 目录到 sys.path（如果尚未添加）
            skill_path_str = str(skill_dir)
            if skill_path_str not in self._skill_paths:
                sys.path.insert(0, skill_path_str)
                self._skill_paths.add(skill_path_str)
            
            # 动态导入模块
            if module_path not in self._modules:
                module = importlib.import_module(module_path)
                self._modules[module_path] = module
                logger.debug(f"Loaded module: {module_path}")
            else:
                module = self._modules[module_path]
            
            # 获取函数引用
            tool_func = getattr(module, function_name)
            self._tools[tool_name] = tool_func
            
            description = tool_config.get('description', 'No description')
            logger.debug(f"Registered tool: {tool_name} ({description})")
            
        except (ImportError, AttributeError) as e:
            logger.warning(
                f"Failed to register tool '{tool_config.get('name') if isinstance(tool_config, dict) else 'unknown'}' "
                f"from {tool_config.get('module') if isinstance(tool_config, dict) else 'unknown'}: {e}"
            )
        except Exception as e:
            logger.warning(
                f"Unexpected error registering tool: {e}"
            )
    
    def get_tool(self, tool_name: str) -> Optional[Callable]:
        """获取已注册的工具函数
        
        Args:
            tool_name: 工具名称
            
        Returns:
            工具函数，如果不存在返回 None
        """
        tool = self._tools.get(tool_name)
        if tool is None:
            logger.warning(f"Tool not found: {tool_name}")
        return tool
    
    def list_tools(self) -> list[str]:
        """列出所有已注册的工具"""
        return sorted(list(self._tools.keys()))
    
    def reload(self) -> None:
        """重新加载所有工具（用于开发调试）
        
        注意: 在生产环境中应谨慎使用此方法
        """
        logger.info("Reloading Tool Registry...")
        self._tools.clear()
        self._modules.clear()
        self._skill_paths.clear()
        self._load_all_tools()
        logger.info(f"Tool Registry reloaded with {len(self._tools)} tools")
    
    def has_tool(self, tool_name: str) -> bool:
        """检查工具是否已注册"""
        return tool_name in self._tools
    
    def get_tools_by_skill(self, skill_name: str) -> Dict[str, Callable]:
        """获取指定 skill 的所有工具（需要从 SKILL.md 重新解析）"""
        # 这个方法可以后续增强，用于按 skill 查询工具
        # 当前实现简化为直接返回所有工具的子集
        pass


# ============================================================================
# 全局单例实例和便捷函数
# ============================================================================

_registry = ToolRegistry()


def get_tool(tool_name: str) -> Optional[Callable]:
    """便捷函数：获取工具
    
    使用示例:
        nornir_execute = get_tool('nornir_execute')
        if nornir_execute:
            result = nornir_execute(...)
    """
    return _registry.get_tool(tool_name)


def list_tools() -> list[str]:
    """便捷函数：列出所有已注册的工具"""
    return _registry.list_tools()


def reload_tools() -> None:
    """便捷函数：重新加载所有工具（开发调试用）"""
    _registry.reload()


def has_tool(tool_name: str) -> bool:
    """便捷函数：检查工具是否已注册"""
    return _registry.has_tool(tool_name)
