# 硬编码问题 - 后续改进计划

**状态**: 第1批修复完成 ✅ | 第2-4批规划中 ⏳

---

## 📈 改进阶段概览

```
Phase 1: 配置层次改进 ✅ COMPLETE
├─ settings.py 添加health_score_config
├─ SKILL.md 添加scoring配置
├─ CLI移除硬编码"test"
├─ inspector.py读取SKILL/settings
└─ report_formatter.py读取SKILL/settings

Phase 2: 路径配置化 ⏳ READY
├─ 审计代码中的硬编码路径
├─ 统一迁移到config/paths.py
├─ 更新所有文件读写操作
└─ 验证所有报告/快照保存路径

Phase 3: 多厂商支持 ⏳ PLANNED
├─ 创建src/olav/adapters/目录结构
├─ 实现vendor adapter interface
├─ 为cisco/arista/juniper编写adapter
├─ 实现platform_registry
└─ 从device_capabilities读取platform

Phase 4: 命令参数化 ⏳ LONG-TERM
├─ SQL查询从SKILL完全参数化
├─ 创建.olav/config/inspection_queries.yaml
├─ 支持查询模板和参数替换
└─ 实现自定义查询UI
```

---

## Phase 2: 路径配置化 (MEDIUM优先级)

### 问题分析

**当前状态**: 路径硬编码在多个文件中

```bash
# 统计硬编码路径
grep -r "exports/" src/ --include="*.py" | wc -l  # ~8处
grep -r "\.olav/" src/ --include="*.py" | wc -l   # ~5处
grep -r "snapshots" src/ --include="*.py" | wc -l # ~3处
```

**违反原则**: "配置不硬编码" + "三层配置架构"

### 改进方案

**Step 1**: 审计所有硬编码路径
```bash
# 需要检查的文件
src/olav/cli/cli_main.py:       exports/
src/olav/tools/report_formatter.py: exports/reports
src/olav/tools/sync_tools.py:   exports/snapshots
src/olav/agents/inspector.py:   exports/reports
config/paths.py:                已存在但使用不一致
```

**Step 2**: 统一到config/paths.py (已存在)
```python
# config/paths.py - 现有内容
PROJECT_ROOT = Path(__file__).parent.parent
EXPORTS_DIR = PROJECT_ROOT / "exports"
REPORTS_DIR = EXPORTS_DIR / "reports"
SNAPSHOTS_DIR = EXPORTS_DIR / "snapshots"
CONFIG_DIR = PROJECT_ROOT / ".olav" / "config"
SKILLS_DIR = PROJECT_ROOT / ".olav" / "skills"

# 在settings中引用
from config.paths import REPORTS_DIR, SNAPSHOTS_DIR
```

**Step 3**: 更新所有使用路径的代码
```python
# ❌ 之前
report_path = "exports/reports/report_" + timestamp + ".md"

# ✅ 之后
from config.paths import REPORTS_DIR
report_path = REPORTS_DIR / f"report_{timestamp}.md"
```

### 影响范围

| 文件 | 行号 | 改动 | 优先级 |
|------|------|------|--------|
| cli_main.py | ~680 | `.olav/config/` → AGENT_DIR / "config" | HIGH |
| report_formatter.py | ~420 | `exports/reports/` → REPORTS_DIR | HIGH |
| sync_tools.py | ~300 | `exports/snapshots/` → SNAPSHOTS_DIR | MEDIUM |
| inspector.py | ~260 | `exports/reports/` → REPORTS_DIR | MEDIUM |

### 实施时间估算

- 审计: 15分钟
- 修改: 30分钟
- 测试: 20分钟
- **总计**: ~1小时

---

## Phase 3: 多厂商支持 (MEDIUM优先级)

### 问题分析

**当前硬编码**:
```python
# src/olav/tools/sync_tools.py:106
platform = host.get("platform", "cisco_ios")  # 假设所有设备是Cisco

# 影响:
# - 无法支持Arista、Juniper、H3C等厂商
# - 命令集硬编码为Cisco IOS格式
# - 解析逻辑假设Cisco输出格式
```

### 改进方案

**Step 1**: 设计Vendor Adapter界面

```python
# src/olav/adapters/__init__.py
from abc import ABC, abstractmethod

class PlatformAdapter(ABC):
    """统一的平台适配器接口"""
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """返回平台名称: cisco_ios, arista_eos等"""
        pass
    
    @abstractmethod
    def get_device_info_command(self) -> str:
        """返回获取设备信息的命令"""
        pass
    
    @abstractmethod
    def parse_device_info(self, output: str) -> dict:
        """解析设备信息输出"""
        pass
    
    @abstractmethod
    def get_interface_command(self) -> str:
        """返回获取接口信息的命令"""
        pass
    
    @abstractmethod
    def parse_interfaces(self, output: str) -> list[dict]:
        """解析接口输出"""
        pass
    
    # ... 更多适配方法
```

**Step 2**: 实现具体适配器

```python
# src/olav/adapters/cisco_adapter.py
class CiscoIOSAdapter(PlatformAdapter):
    @property
    def platform_name(self) -> str:
        return "cisco_ios"
    
    def get_device_info_command(self) -> str:
        return "show version"
    
    def parse_device_info(self, output: str) -> dict:
        # 解析Cisco的'show version'输出
        # 返回: {model, serial, version, ...}
        pass

# src/olav/adapters/arista_adapter.py
class AristaEOSAdapter(PlatformAdapter):
    @property
    def platform_name(self) -> str:
        return "arista_eos"
    
    def get_device_info_command(self) -> str:
        return "show version"  # 命令相同
    
    def parse_device_info(self, output: str) -> dict:
        # 解析Arista的'show version'输出格式
        # (与Cisco格式不同!)
        pass
```

**Step 3**: 实现Adapter Registry

```python
# src/olav/adapters/platform_registry.py
class PlatformRegistry:
    _adapters: dict[str, type[PlatformAdapter]] = {}
    
    @classmethod
    def register(cls, adapter_cls: type[PlatformAdapter]):
        cls._adapters[adapter_cls.platform_name] = adapter_cls
    
    @classmethod
    def get_adapter(cls, platform: str) -> PlatformAdapter:
        if platform not in cls._adapters:
            raise ValueError(f"Unsupported platform: {platform}")
        return cls._adapters[platform]()

# 注册所有适配器
PlatformRegistry.register(CiscoIOSAdapter)
PlatformRegistry.register(AristaEOSAdapter)
PlatformRegistry.register(JuniperAdapter)
```

**Step 4**: 更新sync_tools.py

```python
# ❌ 之前
platform = host.get("platform", "cisco_ios")

# ✅ 之后
from src.olav.adapters.platform_registry import PlatformRegistry

platform_name = host.get("platform", "cisco_ios")
adapter = PlatformRegistry.get_adapter(platform_name)

# 使用adapter来执行命令
device_info_cmd = adapter.get_device_info_command()
device_info = adapter.parse_device_info(output)
```

### 支持的厂商

| 厂商 | 模型 | 状态 | Adapter类 |
|------|------|------|-----------|
| Cisco | IOS/IOS-XE/IOS-XR | 已支持 | CiscoIOSAdapter |
| Arista | EOS | 可优化 | AristaEOSAdapter (待实现) |
| Juniper | Junos | 计划中 | JuniperAdapter (待实现) |
| H3C | Comware | 计划中 | H3CAdapter (待实现) |
| Huawei | VRP | 计划中 | HuaweiAdapter (待实现) |

### 目录结构

```
src/olav/adapters/
├── __init__.py              # 暴露PlatformAdapter基类
├── base.py                  # PlatformAdapter ABC
├── platform_registry.py     # 适配器注册表
├── cisco_adapter.py         # Cisco适配器
├── arista_adapter.py        # Arista适配器 (待实现)
├── juniper_adapter.py       # Juniper适配器 (待实现)
├── h3c_adapter.py           # H3C适配器 (待实现)
└── tests/
    ├── test_cisco.py
    ├── test_arista.py
    └── test_registry.py
```

### 实施时间估算

- 设计: 30分钟
- 实现基类: 1小时
- 实现Cisco适配器: 1小时
- 实现其他厂商: 2-3小时 (每个1小时)
- 测试: 1小时
- **总计**: 6-8小时

---

## Phase 4: 命令参数化 (LOW优先级)

### 问题分析

**当前硬编码**:
```python
# SKILL.md中的SQL查询
sql: |
  SELECT device, cpu_utilization as cpu, 'up' as status, '30 days' as uptime
  FROM v_device_status

# 问题:
# - 假设v_device_status存在且有特定列名
# - 'up'和'30 days'是硬编码的文字值
# - 不同环境可能表结构不同
```

### 改进方案

**创建**: `.olav/config/inspection_queries.yaml`

```yaml
# 查询定义分层
layers:
  L1_Physical:
    # 可选: 来源表名
    source: v_device_status
    
    # 字段映射: 检查项 → 数据源
    fields:
      - name: device
        source: field:device
        
      - name: cpu
        source: field:cpu_utilization
        
      - name: status
        source: literal:"up"  # 文字值
        
      - name: uptime
        source: config:default_uptime  # 从config读取
        default: "30 days"
    
    # 条件过滤
    where:
      - field: device
        operator: "!="
        value: null

  L2_Interfaces:
    source: v_interfaces
    fields:
      - name: device
        source: field:device
      - name: interface
        source: field:interface
      - name: status
        source: field:status
      - name: in_errors
        source: field:InErrors
        default: 0

# 全局配置
defaults:
  default_uptime: "30 days"
  default_status: "up"
```

**在SKILL.md中引用**:

```yaml
# SKILL.md
inspection:
  layers:
    - name: L1_Physical
      description: "设备基础健康检查"
      query_config: inspection_queries.yaml#L1_Physical
      # 代替硬编码SQL
```

**Python中读取**:

```python
# src/olav/agents/inspector.py
import yaml

query_config = yaml.safe_load(
    open(".olav/config/inspection_queries.yaml")
)
layer_config = query_config["layers"]["L1_Physical"]
fields = layer_config["fields"]

# 动态构建SQL
sql = "SELECT " + ", ".join(
    f"{f['source']} as {f['name']}"
    for f in fields
) + f" FROM {layer_config['source']}"
```

### 优势

- ✅ SQL查询完全参数化
- ✅ 支持不同数据库schema
- ✅ 无需改代码即可调整查询
- ✅ 支持多个查询配置 (开发/测试/生产)

### 实施时间估算

- 设计YAML schema: 30分钟
- 实现查询生成器: 1小时
- 创建示例配置: 30分钟
- 测试: 30分钟
- **总计**: ~2.5小时

---

## 🎯 优先级排序建议

### 推荐实施顺序

```
1️⃣ Phase 2 (路径配置化)
   ├─ 复杂度: 低
   ├─ 收益: 中等 (更易部署)
   └─ 时间: 1小时
   
2️⃣ Phase 3 (多厂商支持)
   ├─ 复杂度: 高
   ├─ 收益: 高 (支持新厂商)
   └─ 时间: 6-8小时
   
3️⃣ Phase 4 (命令参数化)
   ├─ 复杂度: 中
   ├─ 收益: 中 (高级用户特性)
   └─ 时间: 2.5小时
```

### 快速赢点 (Quick Wins)

如果时间紧张，优先做:
1. **Phase 2** - 将10分钟集成到现有path系统
2. **Phase 3.1-3.2** - 只做基类和Cisco适配器，其他厂商后续
3. 跳过Phase 4 - 等待用户反馈

---

## 📝 检查清单

### Phase 2 路径配置化
- [ ] 审计所有硬编码路径
- [ ] 检查config/paths.py是否完整
- [ ] 更新cli_main.py
- [ ] 更新report_formatter.py
- [ ] 更新sync_tools.py
- [ ] 更新inspector.py
- [ ] 修改.gitignore排除生成的路径
- [ ] 测试所有报告和快照保存
- [ ] 更新文档

### Phase 3 多厂商支持
- [ ] 设计PlatformAdapter ABC
- [ ] 创建platform_registry.py
- [ ] 实现CiscoIOSAdapter
- [ ] 创建单元测试框架
- [ ] 实现AristaEOSAdapter
- [ ] 实现JuniperAdapter
- [ ] 更新sync_tools.py使用adapter
- [ ] 集成测试
- [ ] 编写多厂商支持文档

### Phase 4 命令参数化
- [ ] 设计inspection_queries.yaml schema
- [ ] 实现QueryBuilder类
- [ ] 创建示例配置文件
- [ ] 更新SKILL.md参考新schema
- [ ] 单元测试
- [ ] 集成测试
- [ ] 性能基准测试
- [ ] 用户文档

---

## 💬 相关问题与答案

**Q: 为什么不一次做完所有改进？**
A: 遵循"增量改进"原则:
- Phase 1 (已完成) - 快速赢点，配置层次改进
- Phase 2 (建议下次) - 简单改进，路径统一
- Phase 3 (中期) - 复杂改进，需要设计和测试
- Phase 4 (长期) - 高级特性，等待用户需求

**Q: 如何验证改进是否工作？**
A: 创建test cases:
```bash
# Phase 2 验证
export REPORTS_DIR=/tmp/custom_reports
olav inspect --test
ls /tmp/custom_reports/  # 应该有报告

# Phase 3 验证
# 配置Arista设备
olav snapshot --group arista_devices
# 应该使用AristaEOSAdapter

# Phase 4 验证
# 编辑inspection_queries.yaml
# 修改字段名称
olav inspect --test
# 应该生成相应字段的报告
```

**Q: 如何处理向后兼容性？**
A: 
- 保持现有接口不变
- 新代码采用configurable方式
- 提供migration script帮助用户升级
- 文档中说明deprecated的做法

---

**下次改进目标**: Phase 2 路径配置化 (优先级MEDIUM)  
**预计时间**: 下一个sprint (1-2周)  
**所有者**: TBD
