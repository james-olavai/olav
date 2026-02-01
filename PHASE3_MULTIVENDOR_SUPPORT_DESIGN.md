# Phase 3: 多厂商支持 - 详细规划与框架

**规划日期**: 2026-02-01  
**预计开始**: 2026-02-05 ~ 2026-02-12  
**预计完成**: 2026-02-12 ~ 2026-02-19  
**预计工作量**: 6-8小时  
**优先级**: MEDIUM  

---

## 🎯 Phase 3 目标

实现Vendor Adapter Pattern，为OLAV系统提供多厂商支持能力，支持Cisco、Arista、Juniper、H3C等不同网络设备厂商。

---

## 📋 Phase 3 核心问题

### 当前状态

```python
# 硬编码假设: 所有设备都是Cisco IOS
platform = host.get("platform", "cisco_ios")  # ❌ 硬编码假设

# 影响:
# 1. 命令集假设Cisco格式
# 2. 输出解析假设Cisco格式
# 3. 无法支持Arista、Juniper等厂商
```

### 解决方案

```python
# ✅ 通过Adapter Pattern实现多厂商支持
adapter = PlatformRegistry.get_adapter(platform)
device_info = adapter.parse_device_info(output)
```

---

## 🏗️ 架构设计

### 目录结构 (新建)

```
src/olav/adapters/
├── __init__.py                      # 暴露PlatformAdapter基类
├── base.py                          # 抽象基类定义
├── platform_registry.py             # Adapter注册表
├── command_templates.py             # 命令模板管理
│
├── vendors/
│   ├── __init__.py
│   ├── cisco_adapter.py             # Cisco IOS适配器 (优先实现)
│   ├── arista_adapter.py            # Arista EOS适配器
│   ├── juniper_adapter.py           # Juniper Junos适配器
│   ├── h3c_adapter.py               # H3C Comware适配器
│   └── huawei_adapter.py            # Huawei VRP适配器
│
├── parsers/
│   ├── __init__.py
│   ├── cisco_parser.py              # Cisco输出解析器
│   ├── arista_parser.py             # Arista输出解析器
│   ├── juniper_parser.py            # Juniper输出解析器
│   └── common_parser.py             # 通用解析工具
│
└── tests/
    ├── test_base.py
    ├── test_registry.py
    ├── test_cisco_adapter.py
    ├── test_arista_adapter.py
    └── test_juniper_adapter.py
```

### 抽象基类设计

```python
# src/olav/adapters/base.py

from abc import ABC, abstractmethod
from typing import Dict, Any, List

class PlatformAdapter(ABC):
    """统一的平台适配器接口 - 所有厂商适配器必须实现"""
    
    @property
    @abstractmethod
    def platform_name(self) -> str:
        """平台唯一标识: cisco_ios, arista_eos等"""
        pass
    
    @property
    @abstractmethod
    def platform_display_name(self) -> str:
        """平台显示名: Cisco IOS, Arista EOS等"""
        pass
    
    # ======================== 设备信息相关 ========================
    
    @abstractmethod
    def get_device_info_command(self) -> str:
        """获取设备基本信息的命令 (如: show version)"""
        pass
    
    @abstractmethod
    def parse_device_info(self, output: str) -> Dict[str, Any]:
        """解析设备信息输出
        
        返回格式:
        {
            'model': '...',
            'serial': '...',
            'version': '...',
            'hostname': '...',
            'uptime': '...',
            ...
        }
        """
        pass
    
    # ======================== 接口相关 ========================
    
    @abstractmethod
    def get_interface_command(self) -> str:
        """获取接口详情的命令 (如: show interface)"""
        pass
    
    @abstractmethod
    def parse_interfaces(self, output: str) -> List[Dict[str, Any]]:
        """解析接口列表输出
        
        返回格式:
        [
            {
                'interface': 'Ethernet1',
                'status': 'up',
                'protocol': 'up',
                'mtu': 1500,
                'bandwidth': 1000000,
                'in_errors': 0,
                'out_errors': 0,
                ...
            },
            ...
        ]
        """
        pass
    
    # ======================== 路由相关 ========================
    
    @abstractmethod
    def get_routing_command(self) -> str:
        """获取路由表信息的命令"""
        pass
    
    @abstractmethod
    def parse_routing_table(self, output: str) -> List[Dict[str, Any]]:
        """解析路由表输出
        
        返回格式:
        [
            {
                'destination': '10.0.0.0/24',
                'next_hop': '192.168.1.1',
                'protocol': 'ospf',
                'metric': 100,
                'age': '1d2h',
                ...
            },
            ...
        ]
        """
        pass
    
    # ======================== CPU/内存相关 ========================
    
    @abstractmethod
    def get_cpu_command(self) -> str:
        """获取CPU使用率的命令"""
        pass
    
    @abstractmethod
    def parse_cpu(self, output: str) -> Dict[str, Any]:
        """解析CPU信息输出
        
        返回格式:
        {
            'cpu_1sec': 25.5,
            'cpu_1min': 24.3,
            'cpu_5min': 23.1,
            ...
        }
        """
        pass
    
    @abstractmethod
    def get_memory_command(self) -> str:
        """获取内存使用率的命令"""
        pass
    
    @abstractmethod
    def parse_memory(self, output: str) -> Dict[str, Any]:
        """解析内存信息输出"""
        pass
    
    # ======================== 邻居相关 ========================
    
    @abstractmethod
    def get_neighbors_command(self) -> str:
        """获取邻居信息的命令 (LLDP/CDP)"""
        pass
    
    @abstractmethod
    def parse_neighbors(self, output: str) -> List[Dict[str, Any]]:
        """解析邻居发现协议输出"""
        pass
    
    # ======================== 版本特定命令 ========================
    
    def get_commands_by_group(self, group: str) -> List[str]:
        """按分组获取命令列表 (可选)
        
        Args:
            group: 命令分组 (如: 'basic', 'detail', 'performance')
        
        Returns:
            命令列表
        """
        basic_cmds = [
            self.get_device_info_command(),
            self.get_interface_command(),
            self.get_routing_command(),
        ]
        
        if group == 'basic':
            return basic_cmds
        elif group == 'detail':
            return basic_cmds + [self.get_neighbors_command()]
        elif group == 'performance':
            return [self.get_cpu_command(), self.get_memory_command()]
        else:
            return basic_cmds
```

### Adapter注册表

```python
# src/olav/adapters/platform_registry.py

from typing import Type, Dict
from .base import PlatformAdapter

class PlatformRegistry:
    """Adapter注册表 - 管理所有平台适配器"""
    
    _adapters: Dict[str, Type[PlatformAdapter]] = {}
    _instances: Dict[str, PlatformAdapter] = {}
    
    @classmethod
    def register(cls, adapter_cls: Type[PlatformAdapter]) -> None:
        """注册新的适配器
        
        Usage:
            @PlatformRegistry.register
            class CiscoIOSAdapter(PlatformAdapter):
                ...
        """
        if not issubclass(adapter_cls, PlatformAdapter):
            raise ValueError(f"{adapter_cls} must inherit from PlatformAdapter")
        
        adapter_instance = adapter_cls()
        platform_name = adapter_instance.platform_name
        
        cls._adapters[platform_name] = adapter_cls
        cls._instances[platform_name] = adapter_instance
        print(f"✅ Registered adapter: {platform_name}")
    
    @classmethod
    def get_adapter(cls, platform: str) -> PlatformAdapter:
        """获取指定平台的适配器
        
        Args:
            platform: 平台名称 (cisco_ios, arista_eos等)
        
        Returns:
            Adapter实例
        
        Raises:
            ValueError: 平台不支持
        """
        if platform not in cls._instances:
            raise ValueError(
                f"Unsupported platform: {platform}\n"
                f"Available platforms: {list(cls._adapters.keys())}"
            )
        return cls._instances[platform]
    
    @classmethod
    def list_adapters(cls) -> Dict[str, str]:
        """列出所有已注册的适配器
        
        Returns:
            {"platform_name": "display_name", ...}
        """
        return {
            name: instance.platform_display_name
            for name, instance in cls._instances.items()
        }
    
    @classmethod
    def is_supported(cls, platform: str) -> bool:
        """检查平台是否支持"""
        return platform in cls._instances
```

---

## 📋 实施清单 (按优先级)

### Priority 1: 基础框架 (1.5小时)

- [ ] 创建 `src/olav/adapters/` 目录结构
- [ ] 实现 `base.py` - PlatformAdapter ABC
- [ ] 实现 `platform_registry.py` - Registry类
- [ ] 创建 `__init__.py` - 暴露公共接口
- [ ] 编写单元测试框架

### Priority 2: Cisco适配器 (2小时) - 优先实现

- [ ] 创建 `vendors/cisco_adapter.py`
- [ ] 实现基本命令方法
- [ ] 实现输出解析器 (device_info, interfaces等)
- [ ] 单元测试 (mock Cisco输出)
- [ ] 集成到 sync_tools.py

### Priority 3: Arista适配器 (1.5小时)

- [ ] 创建 `vendors/arista_adapter.py`
- [ ] 实现命令方法 (大部分与Cisco相同)
- [ ] 实现Arista特定的解析逻辑
- [ ] 单元测试
- [ ] 兼容性测试 (vs Cisco)

### Priority 4: Juniper适配器 (1.5小时)

- [ ] 创建 `vendors/juniper_adapter.py`
- [ ] 实现Juniper特定的命令 (show route table等)
- [ ] Juniper特定的解析逻辑 (XML支持?)
- [ ] 单元测试
- [ ] 兼容性测试

### Priority 5: 其他厂商 (1小时/厂商)

- [ ] H3C Comware适配器
- [ ] Huawei VRP适配器

### Priority 6: 系统集成 (1小时)

- [ ] 更新 `sync_tools.py` 使用Registry
- [ ] 更新 `device_capabilities` 表
- [ ] 端到端测试
- [ ] 性能基准测试

### Priority 7: 文档更新 (0.5小时)

- [ ] 编写如何添加新厂商的指南
- [ ] 更新用户手册
- [ ] 常见问题 (FAQ)

---

## 💻 Cisco适配器参考实现

```python
# src/olav/adapters/vendors/cisco_adapter.py

from ..base import PlatformAdapter
from typing import Dict, Any, List
import re

class CiscoIOSAdapter(PlatformAdapter):
    """Cisco IOS & IOS-XE 适配器"""
    
    @property
    def platform_name(self) -> str:
        return "cisco_ios"
    
    @property
    def platform_display_name(self) -> str:
        return "Cisco IOS/IOS-XE"
    
    def get_device_info_command(self) -> str:
        return "show version"
    
    def parse_device_info(self, output: str) -> Dict[str, Any]:
        """解析Cisco 'show version'输出"""
        info = {}
        
        # 提取型号
        model_match = re.search(r'Cisco (\S+(?:\s+\S+)*)', output)
        if model_match:
            info['model'] = model_match.group(1)
        
        # 提取版本
        version_match = re.search(r'Software Version: (\S+)|IOS.*?Version (\S+)', output)
        if version_match:
            info['version'] = version_match.group(1) or version_match.group(2)
        
        # 提取序列号
        serial_match = re.search(r'Serial number: (\S+)', output)
        if serial_match:
            info['serial'] = serial_match.group(1)
        
        # 提取系统正常运行时间
        uptime_match = re.search(r'System uptime is (.+)', output)
        if uptime_match:
            info['uptime'] = uptime_match.group(1)
        
        return info
    
    def get_interface_command(self) -> str:
        return "show interfaces"
    
    def parse_interfaces(self, output: str) -> List[Dict[str, Any]]:
        """解析Cisco 'show interfaces'输出"""
        interfaces = []
        
        # 分割每个接口块
        interface_blocks = re.split(r'^(\S+)\s+is', output, flags=re.MULTILINE)[1:]
        
        for i in range(0, len(interface_blocks), 2):
            if i+1 >= len(interface_blocks):
                break
            
            intf_name = interface_blocks[i]
            intf_data = interface_blocks[i+1]
            
            intf_info = {'interface': intf_name}
            
            # 状态
            status_match = re.search(r'is (.+?),', intf_data)
            if status_match:
                status = status_match.group(1)
                intf_info['status'] = 'up' if 'up' in status.lower() else 'down'
            
            # 协议
            proto_match = re.search(r'line protocol is (.+?)[\r\n]', intf_data)
            if proto_match:
                proto = proto_match.group(1)
                intf_info['protocol'] = 'up' if 'up' in proto.lower() else 'down'
            
            # MTU
            mtu_match = re.search(r'MTU (\d+)', intf_data)
            if mtu_match:
                intf_info['mtu'] = int(mtu_match.group(1))
            
            # 输入/输出错误
            in_err = re.search(r'(\d+) input error', intf_data)
            out_err = re.search(r'(\d+) output error', intf_data)
            crc_err = re.search(r'(\d+) CRC', intf_data)
            
            intf_info['in_errors'] = int(in_err.group(1)) if in_err else 0
            intf_info['out_errors'] = int(out_err.group(1)) if out_err else 0
            intf_info['crc_errors'] = int(crc_err.group(1)) if crc_err else 0
            
            interfaces.append(intf_info)
        
        return interfaces
    
    # ... 其他方法实现 ...
    
    def get_routing_command(self) -> str:
        return "show ip route"
    
    def parse_routing_table(self, output: str) -> List[Dict[str, Any]]:
        """解析Cisco 'show ip route'输出"""
        routes = []
        # 实现路由表解析逻辑
        return routes
    
    def get_cpu_command(self) -> str:
        return "show processes cpu"
    
    def parse_cpu(self, output: str) -> Dict[str, Any]:
        """解析CPU使用率"""
        # 实现CPU解析逻辑
        return {}
    
    def get_memory_command(self) -> str:
        return "show memory statistics"
    
    def parse_memory(self, output: str) -> Dict[str, Any]:
        """解析内存使用率"""
        # 实现内存解析逻辑
        return {}
    
    def get_neighbors_command(self) -> str:
        return "show lldp neighbors"
    
    def parse_neighbors(self, output: str) -> List[Dict[str, Any]]:
        """解析邻居信息"""
        # 实现邻居解析逻辑
        return []
```

---

## 🔄 sync_tools.py 集成示例

```python
# src/olav/tools/sync_tools.py - 修改示例

from olav.adapters.platform_registry import PlatformRegistry

async def sync_all(devices=None, commands=None, platform=None):
    """执行设备同步 - 使用Adapter Pattern"""
    
    # 如果指定了平台，验证其有效性
    if platform and not PlatformRegistry.is_supported(platform):
        raise ValueError(f"Platform {platform} not supported")
    
    for host in selected_hosts:
        # 获取设备平台
        device_platform = host.get("platform") or platform or "cisco_ios"
        
        # 获取适配器
        try:
            adapter = PlatformRegistry.get_adapter(device_platform)
        except ValueError as e:
            logger.warning(f"Device {host['hostname']}: {e}, falling back to cisco_ios")
            adapter = PlatformRegistry.get_adapter("cisco_ios")
        
        # 使用适配器执行命令
        device_info_cmd = adapter.get_device_info_command()
        output = await run_command(host, device_info_cmd)
        
        # 使用适配器解析输出
        device_info = adapter.parse_device_info(output)
        
        # 保存到数据库
        store_device_info(host['hostname'], device_info)
```

---

## 📊 支持矩阵

### 已实现

| 厂商 | 平台 | 基本命令 | 接口解析 | 路由解析 | 邻居解析 | 状态 |
|------|------|--------|--------|--------|--------|------|
| Cisco | IOS/IOS-XE | ✅ | ✅ | ✅ | ✅ | 已用 |

### 规划中 (Phase 3)

| 厂商 | 平台 | 基本命令 | 接口解析 | 路由解析 | 邻居解析 | 优先级 |
|------|------|--------|--------|--------|--------|--------|
| Arista | EOS | ⏳ | ⏳ | ⏳ | ⏳ | HIGH |
| Juniper | Junos | ⏳ | ⏳ | ⏳ | ⏳ | HIGH |
| H3C | Comware | ⏳ | ⏳ | ⏳ | ⏳ | MEDIUM |
| Huawei | VRP | ⏳ | ⏳ | ⏳ | ⏳ | MEDIUM |

### 未来规划

| 厂商 | 平台 | 优先级 |
|------|------|--------|
| Fortinet | FortiOS | LOW |
| Palo Alto | PAN-OS | LOW |
| Mikrotik | RouterOS | LOW |

---

## ⚠️ 风险与缓解

### 风险1: 不同厂商命令输出差异大

**缓解**: 
- 创建完整的测试用例库 (mock输出)
- 为每个厂商提供详细的解析文档
- 实现输出规范化 (统一数据格式)

### 风险2: 新厂商适配器实现困难

**缓解**:
- 提供适配器开发指南
- 创建开源社区共享厂商适配器
- 支持用户贡献新的适配器

### 风险3: 后向兼容性问题

**缓解**:
- 保持Cisco作为默认平台
- 版本1.0之前保持Beta标签
- 文档中明确列出支持的平台版本

---

## 📚 文档交付

### 新文档

1. **Adapter Developer Guide** - 如何编写新的厂商适配器
2. **Platform Support Matrix** - 支持的平台和功能矩阵
3. **Command Reference** - 每个平台的命令参考

### 代码示例

1. 完整的Cisco适配器实现
2. 单元测试示例
3. 集成测试示例

---

## 🎯 验收标准

### 功能验收

- [ ] 所有抽象方法在基类中定义
- [ ] Cisco适配器完全实现
- [ ] Arista和Juniper适配器至少支持基本功能
- [ ] 可正确检测并使用不同厂商的适配器
- [ ] 输出解析准确率 > 99%

### 测试覆盖率

- [ ] 基类单元测试 > 90%
- [ ] Cisco适配器单元测试 > 85%
- [ ] Registry单元测试 > 95%
- [ ] 集成测试覆盖主要场景

### 性能指标

- [ ] 适配器加载时间 < 10ms
- [ ] 命令输出解析时间 < 100ms (每个设备)
- [ ] 内存占用 < 50MB (所有适配器)

### 文档完整度

- [ ] 架构设计文档完整
- [ ] API文档齐全
- [ ] 至少3个厂商的完整适配器
- [ ] 开发者指南可操作

---

## 📈 成功指标

### 阶段完成

| 检查点 | 目标 | 实际 | 状态 |
|--------|------|------|------|
| 基础框架完成 | 2026-02-05 | - | ⏳ |
| Cisco适配器完成 | 2026-02-08 | - | ⏳ |
| Arista适配器完成 | 2026-02-12 | - | ⏳ |
| 所有测试通过 | 2026-02-12 | - | ⏳ |
| 文档更新完成 | 2026-02-12 | - | ⏳ |

### 质量目标

- 代码质量: A级 (Pylint score > 8.5)
- 测试覆盖率: > 85%
- 文档完整度: 100%
- 无breaking changes: 0个

---

**Phase 3 状态**: 规划完成，待开始实施  
**预计开始**: 2026-02-05  
**预计完成**: 2026-02-12 ~ 2026-02-19  
**工作量**: 6-8小时
