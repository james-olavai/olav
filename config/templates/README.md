# Custom TextFSM Templates

将自定义 TextFSM 模板文件放在此目录下。

## 目录结构

```
config/templates/
├── index                          # 模板索引文件 (必需)
├── cisco_ios_show_custom.textfsm  # 示例: Cisco 自定义命令模板
└── huawei_show_bgp.textfsm        # 示例: 华为 BGP 模板
```

## index 文件格式

```
# Template, Hostname, Platform, Command
cisco_ios_show_custom.textfsm, .*, cisco_ios, show custom
huawei_show_bgp.textfsm, .*, huawei, show bgp peer
```

## 模板搜索顺序

1. 此目录下的自定义模板
2. ntc-templates 包的内置模板

可以通过相同文件名覆盖内置模板。
